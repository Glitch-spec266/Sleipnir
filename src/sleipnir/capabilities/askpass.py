"""The GUI password prompt, and the one place plaintext is allowed on a pipe.

``sudo -A`` asks an external program for a password and reads it from that
program's standard output.  That is the protocol; there is no variant of it
where the value stays private to the process that typed it.  So this module is
a deliberate, single exception to the rule the rest of the capability code
follows — ``secrets.py`` types a credential into the target window and never
returns it, and that remains true everywhere else.

The exception is contained three ways.  The plaintext exists only in a
short-lived helper process; it is written to exactly one file descriptor; and
the caller that can reach it is the operator's own ``sudo``, never a dispatched
task.  That last one is not a convention — ``resolve`` refuses outright when it
sees the worker marker, and the agent socket address is stripped from every
worker environment.

The dialog is ``pinentry``, GnuPG's prompt, because it is the one program on a
Linux desktop built so a password never reaches argv, a log file, or swap.
Which pinentry gets used is decided by *trying* them: on the development
machine two of the three installed are broken and only ``pinentry-gtk`` runs,
so choosing by desktop environment would have failed at the exact moment a
password was needed.  Same lesson as ``grim`` on KWin.
"""

from __future__ import annotations

import contextlib
import functools
import os
import re
import shlex
import shutil
import subprocess
import uuid

from pathlib import Path

from sleipnir.capabilities import agent, audit

#: Set in every dispatched worker's environment. ``resolve`` refuses on it.
WORKER_MARKER_ENV = "SLEIPNIR_WORKER"
#: Where the helper finds the agent. Stripped from worker environments.
AGENT_SOCKET_ENV = "SLEIPNIR_AGENT_SOCK"

MAX_LABEL_CHARS = agent.MAX_LABEL_CHARS
MAX_ASSUAN_LINE = 900

# Ordered by how likely each is to be the desktop's native dialog, but the
# order is only a preference — `find_pinentry` probes each one before using it.
PINENTRY_CANDIDATES = (
    "pinentry-qt",
    "pinentry-gnome3",
    "pinentry-gtk",
    "pinentry-gtk-2",
    "pinentry",
)


class AskpassError(RuntimeError):
    """No dialog could be shown, or the dialog failed."""


class AskpassCancelled(AskpassError):
    """The operator dismissed the prompt.

    Distinct from an empty answer on purpose: an empty password is a password,
    and treating a cancel as one would cache the wrong thing forever.
    """


class AskpassRefused(AskpassError):
    """A caller that may not reach the credential cache asked for a credential."""


# ---------------------------------------------------------------------------
# labels
# ---------------------------------------------------------------------------

_SUDO_PATTERNS = (
    re.compile(r"^\[sudo\]\s*password\s+for\b", re.IGNORECASE),
    re.compile(r"^password\s*:?\s*$", re.IGNORECASE),
    re.compile(r"^.{0,32}'s\s+password\s*:?\s*$", re.IGNORECASE),
)
_SSH_KEY = re.compile(r"enter\s+passphrase\s+for\s+key\s+'([^']+)'", re.IGNORECASE)
_PASSWORD_FOR = re.compile(r"password\s+for\s+(\S+?)\s*:?\s*$", re.IGNORECASE)


def normalise_label(prompt: str) -> str:
    """Collapse a tool's prompt text into one stable cache key.

    sudo phrases its prompt differently depending on the user, the locale and
    ``/etc/sudoers``; the same password behind three spellings would mean three
    dialogs for one credential, which defeats the whole feature.

    The result is also the key of a dict and part of a line in a line-oriented
    protocol, and the prompt is text Sleipnir did not author.  It is stripped
    of anything non-printable and clipped.
    """
    text = " ".join((prompt or "").split())
    if not text:
        return "credential"
    key_match = _SSH_KEY.search(text)
    if key_match:
        label = f"ssh:{key_match.group(1)}"
    elif any(pattern.match(text) for pattern in _SUDO_PATTERNS):
        label = "sudo"
    else:
        target = _PASSWORD_FOR.search(text)
        label = target.group(1) if target else text
    label = "".join(ch for ch in label if ch.isprintable() and ch not in " \t")
    return (label or "credential")[:MAX_LABEL_CHARS]


# ---------------------------------------------------------------------------
# pinentry
# ---------------------------------------------------------------------------


def _handshake_ok(path: str) -> bool:
    """Does this pinentry actually start? Two of three on the dev box do not."""
    try:
        result = subprocess.run(
            [path],
            input=b"GETINFO version\nBYE\n",
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.stdout.startswith(b"OK")


@functools.lru_cache(maxsize=1)
def find_pinentry() -> str:
    """The first pinentry on this machine that answers, not the first installed."""
    seen: list[str] = []
    for name in PINENTRY_CANDIDATES:
        path = shutil.which(name)
        if path is None or path in seen:
            continue
        seen.append(path)
        if _handshake_ok(path):
            return path
    raise AskpassError(
        "no working pinentry found; install one of " + ", ".join(PINENTRY_CANDIDATES)
    )


def _unescape(value: str | bytes) -> bytearray:
    """Decode Assuan escapes as octets, preserving non-ASCII credentials.

    `%C3%A9` represents the UTF-8 bytes for `é`. Decoding each escape with
    ``chr`` and then encoding that string again double-encodes those bytes and
    silently changes the password.
    """
    source = value.encode("utf-8") if isinstance(value, str) else value
    out = bytearray()
    index = 0
    while index < len(source):
        octet = source[index]
        if octet == ord("%") and index + 2 < len(source):
            try:
                out.append(int(source[index + 1 : index + 3], 16))
                index += 3
                continue
            except ValueError:
                pass
        out.append(octet)
        index += 1
    return out


def _assuan_safe(text: str, *, limit: int) -> str:
    """One line, printable only.

    The description is shown in a GUI and travels as an Assuan command line, so
    an embedded newline would inject a second command and a control byte would
    reach a terminal. Same reasoning as the TUI's ``_clip``.
    """
    flat = "".join(ch for ch in " ".join((text or "").split()) if ch.isprintable())
    escaped: list[str] = []
    used = 0
    for char in flat:
        token = "%25" if char == "%" else char
        encoded_length = len(token.encode("utf-8"))
        if used + encoded_length > limit:
            break
        escaped.append(token)
        used += encoded_length
    return "".join(escaped)


def prompt_gui(
    label: str,
    *,
    description: str = "",
    prompt_text: str = "Password:",
    title: str = "Sleipnir",
) -> bytearray:
    """Show the dialog and return the typed bytes.

    Returns a ``bytearray`` rather than ``str`` so the caller can zero it; see
    ``secrets.Secret`` for why an immutable ``str`` is the wrong container for
    a credential.
    """
    binary = find_pinentry()
    lines = [
        # pinentry-gtk closes its dialog on an internal timeout and answers
        # `ERR 83886142 Timeout`. The operator may be walking back to the
        # keyboard; the enclosing subprocess timeout is the real bound.
        "SETTIMEOUT 0",
        f"SETTITLE {_assuan_safe(title, limit=120)}",
        f"SETPROMPT {_assuan_safe(prompt_text, limit=120)}",
        f"SETDESC {_assuan_safe(description or f'Sleipnir needs the {label} password.', limit=MAX_ASSUAN_LINE - 10)}",
        "GETPIN",
        "BYE",
    ]
    try:
        result = subprocess.run(
            [binary],
            input=("\n".join(lines) + "\n").encode("utf-8"),
            capture_output=True,
            timeout=300,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise AskpassError(f"pinentry failed: {type(error).__name__}") from error

    # A `D` line is the answer; an `ERR` only means cancelled when no answer
    # arrived. pinentry emits ERR for a rejected option too, and treating that
    # as a dismissal would report the operator's action for Sleipnir's fault.
    value: bytearray | None = None
    error_line = b""
    for line in result.stdout.splitlines():
        if line.startswith(b"D "):
            value = _unescape(line[2:])
        elif line.startswith(b"ERR") and not error_line:
            error_line = line
    if value is not None:
        return value
    if b"cancel" in error_line.lower():
        raise AskpassCancelled("the operator dismissed the password prompt")
    if error_line:
        diagnostic = error_line.decode("utf-8", errors="replace")
        raise AskpassError(
            f"pinentry refused the request: {_assuan_safe(diagnostic, limit=160)}"
        )
    raise AskpassCancelled("no password was entered")


# ---------------------------------------------------------------------------
# resolve
# ---------------------------------------------------------------------------


def _refuse_if_worker() -> None:
    if os.environ.get(WORKER_MARKER_ENV):
        raise AskpassRefused(
            "credentials are an operator capability; a dispatched task may not request one"
        )


def resolve(
    prompt: str,
    *,
    client: agent.AgentClient | None = None,
    description: str = "",
) -> bytearray:
    """Return the credential for ``prompt``, asking only on a cache miss.

    This is the whole feature in one function: the first sudo of a session
    opens a dialog, every later one is served from the agent.
    """
    _refuse_if_worker()
    label = normalise_label(prompt)
    if client is not None:
        cache = client
    else:
        configured_socket = os.environ.get(AGENT_SOCKET_ENV)
        cache = (
            agent.ensure_running(socket_path=Path(configured_socket))
            if configured_socket
            else agent.ensure_running()
        )
    cached = cache.get(label)
    if cached is not None:
        try:
            audit.record("askpass.served", {"label": label, "source": "agent"})
        except Exception:
            wipe(cached)
            raise
        return cached

    value = prompt_gui(label, description=description, prompt_text=_assuan_safe(prompt, limit=120))
    try:
        cache.set(label, value)
        plaintext = bytearray(value)
    finally:
        wipe(value)
    try:
        audit.record(
            "askpass.prompted",
            {"label": label, "length": len(plaintext), "remembered": True},
        )
    except Exception:
        with contextlib.suppress(Exception):
            cache.drop(label)
        wipe(plaintext)
        raise
    return plaintext


def wipe(value: bytearray) -> None:
    for index in range(len(value)):
        value[index] = 0
    value.clear()


# ---------------------------------------------------------------------------
# sudo wiring
# ---------------------------------------------------------------------------

_HELPER = """#!/bin/sh
# Written by Sleipnir. SUDO_ASKPASS takes a program path and passes the prompt
# as the single argument, so this shim exists only to bind that calling
# convention to `sleipnir askpass`.
exec {command} "$@"
"""


def write_helper(*, directory: Path | None = None, executable: str | None = None) -> Path:
    """Create the executable ``SUDO_ASKPASS`` points at."""
    import sys

    folder = Path(directory) if directory else Path.home() / ".sleipnir"
    if folder.exists() and (folder.is_symlink() or not folder.is_dir()):
        raise AskpassError(f"unsafe askpass directory: {folder}")
    folder.mkdir(parents=True, exist_ok=True)
    # Bind the helper to this installation. Looking up `sleipnir` on PATH can
    # select an older global install (or a replaced executable) after the
    # helper has already become sudo's credential boundary.
    argv = (
        [executable, "askpass"]
        if executable is not None
        else [sys.executable, "-m", "sleipnir.cli", "askpass"]
    )
    path = folder / "askpass.sh"
    body = _HELPER.format(command=shlex.join(argv)).encode("utf-8")
    temporary = folder / f".askpass-{uuid.uuid4().hex}.tmp"
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o700,
    )
    try:
        os.write(descriptor, body)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def sudo_env(
    env: dict[str, str] | None = None,
    *,
    directory: Path | None = None,
    executable: str | None = None,
) -> dict[str, str]:
    """A copy of ``env`` with the askpass hook and agent address added."""
    result = dict(env if env is not None else os.environ)
    result["SUDO_ASKPASS"] = str(write_helper(directory=directory, executable=executable))
    result[AGENT_SOCKET_ENV] = str(agent.default_socket_path())
    return result


__all__ = [
    "AGENT_SOCKET_ENV",
    "MAX_ASSUAN_LINE",
    "MAX_LABEL_CHARS",
    "PINENTRY_CANDIDATES",
    "WORKER_MARKER_ENV",
    "AskpassCancelled",
    "AskpassError",
    "AskpassRefused",
    "find_pinentry",
    "normalise_label",
    "prompt_gui",
    "resolve",
    "sudo_env",
    "wipe",
    "write_helper",
]
