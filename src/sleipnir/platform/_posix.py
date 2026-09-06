"""POSIX backend for the platform seam.

Every function here is a direct lift of behaviour that used to live inline in
``runlog.py``, ``process.py``, ``chat.py``, ``capabilities/browser.py`` and
``console.py`` before this port. Nothing here changes what Linux does; it only
moves the code so ``platform/_windows.py`` has something exact to match.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import shutil
import signal
import sys
import termios
import tty
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import IO, Any

from sleipnir.platform import LockUnavailable

# ---------------------------------------------------------------------------
# File locking -- runlog.py's RunLock and run_is_active()
# ---------------------------------------------------------------------------


def try_lock_exclusive(handle: IO[Any]) -> None:
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        raise LockUnavailable(str(exc)) from exc


def unlock(handle: IO[Any]) -> None:
    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


# ---------------------------------------------------------------------------
# Process liveness -- executor.py's crash-recovery probe
# ---------------------------------------------------------------------------


def pid_is_alive(pid: int) -> bool:
    """Probe process existence without sending a signal that changes state."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


# ---------------------------------------------------------------------------
# Console encoding and colour
# ---------------------------------------------------------------------------


def prepare_stdio_encoding() -> None:
    """No-op on POSIX: terminal encoding is UTF-8 almost everywhere already,
    and reconfiguring here would fight a user's deliberate ``LANG``/``LC_ALL``
    choice for no benefit."""


def enable_ansi(stream: Any) -> bool:
    """POSIX terminals already understand ANSI; nothing to enable."""
    isatty = getattr(stream, "isatty", None)
    return bool(isatty and isatty())


def colour_is_supported(stream: Any) -> bool:
    """``NO_COLOR`` is honoured (https://no-color.org); ``TERM=dumb`` means a
    real terminal that has told us not to bother."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("TERM") in (None, "", "dumb"):
        return False
    isatty = getattr(stream, "isatty", None)
    return bool(isatty and isatty())


# ---------------------------------------------------------------------------
# Child process spawn and tree kill
# ---------------------------------------------------------------------------

#: ``setsid()``. Own process group, so a group-wide signal reaches whatever
#: the provider CLI spawned, not just the CLI itself.
CHILD_SPAWN_KWARGS: dict[str, Any] = {"start_new_session": True}


def create_guarded_launch(argv: list[str]):
    """Wrap ``argv`` with ``process_guard.py`` when this platform has a real
    parent-death guard to offer (Linux only -- see ``WRAPS_CHILDREN``).

    Import is local to avoid a cycle: ``process.py`` imports ``platform``,
    and ``process_guard.py`` lives next to it in the same package.
    """
    from sleipnir.platform import GuardedLaunch, WRAPS_CHILDREN, guard_script_path

    if not WRAPS_CHILDREN:
        return GuardedLaunch(argv, close=lambda: None)
    wrapped = [sys.executable, str(guard_script_path()), "--", *argv]
    return GuardedLaunch(wrapped, close=lambda: None)


def request_group_stop(proc: Any) -> str:
    """SIGTERM the process group. Returns the label recorded in
    ``ProcessResult.signalled``."""
    _signal_group(proc, signal.SIGTERM)
    return signal.SIGTERM.name


def force_kill_tree(proc: Any) -> str:
    """SIGKILL the process group. Returns the label recorded in
    ``ProcessResult.signalled``."""
    _signal_group(proc, signal.SIGKILL)
    return signal.SIGKILL.name


def _signal_group(proc: Any, sig: signal.Signals) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), sig)
    except (ProcessLookupError, PermissionError, OSError):
        # Already reaped, or the fake process in tests has no real pgid.
        with contextlib.suppress(Exception):
            proc.kill()


def stop_pid_group(pid: int) -> bool:
    """SIGTERM a process group discovered only as a bare pid (e.g. read back
    from a pid file across a restart, with no live Process object)."""
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def kill_pid_tree(pid: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(os.getpgid(pid), signal.SIGKILL)


# ---------------------------------------------------------------------------
# Shell selection -- checks.py's CommandCheck and computer.run()
# ---------------------------------------------------------------------------


def posix_shell() -> Path | None:
    return Path("/bin/sh") if Path("/bin/sh").exists() else None


def shell_argv(command: str) -> list[str]:
    return ["/bin/sh", "-c", command]


def shell_kind() -> str:
    return "posix"


# ---------------------------------------------------------------------------
# Executables
# ---------------------------------------------------------------------------


def resolve_executable(name: str) -> str:
    """POSIX ``PATH`` lookup already works for bare names passed to
    ``exec*`` family calls; resolving is a courtesy, not a requirement."""
    return shutil.which(name) or name


# ---------------------------------------------------------------------------
# Filesystem
# ---------------------------------------------------------------------------


def is_reparse_point(path: Path) -> bool:
    return path.is_symlink()


def replace_atomic(src: Path, dst: Path) -> None:
    os.replace(src, dst)


# ---------------------------------------------------------------------------
# Console raw mode and key reading
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def raw_console() -> Iterator[bool]:
    stream = sys.stdin
    if not stream.isatty():
        yield False
        return
    saved = termios.tcgetattr(stream)
    try:
        tty.setcbreak(stream.fileno())
        yield True
    finally:
        termios.tcsetattr(stream, termios.TCSADRAIN, saved)


#: The arrow keys' CSI final byte -> the same named-token vocabulary
#: platform/_windows.py's key_reader emits for its own extended keys, so
#: console.apply_key has exactly one dialect to understand regardless of
#: platform. Before this, an arrow key's escape sequence was fed to
#: apply_key one character at a time, and -- since "[" and "A" are both
#: `str.isprintable()` -- pressing Up inserted the literal text "[A" into
#: the prompt. Only the common case (the whole 3-byte sequence arriving in
#: one read) is decoded; a sequence split across two reads falls back to the
#: old raw-character behaviour, which is a rare cosmetic miss, not a
#: regression.
_CSI_ARROWS: dict[str, str] = {"A": "<up>", "B": "<down>", "C": "<right>", "D": "<left>"}


@contextlib.contextmanager
def key_reader(loop: Any, put: Callable[[str], None]) -> Iterator[None]:
    """Feed raw stdin bytes to ``put`` as they arrive.

    Lifted from ``console.py``'s former ``_on_readable``/``add_reader`` pair,
    with one addition: arrow-key escape sequences are folded into one token
    rather than delivered as three separate characters.
    """

    def _on_readable() -> None:
        data = os.read(sys.stdin.fileno(), 1024).decode("utf-8", "ignore")
        index, length = 0, len(data)
        while index < length:
            if (
                data[index] == "\x1b"
                and index + 2 < length
                and data[index + 1] == "["
                and data[index + 2] in _CSI_ARROWS
            ):
                put(_CSI_ARROWS[data[index + 2]])
                index += 3
                continue
            put(data[index])
            index += 1

    loop.add_reader(sys.stdin.fileno(), _on_readable)
    try:
        yield
    finally:
        loop.remove_reader(sys.stdin.fileno())


__all__ = [
    "CHILD_SPAWN_KWARGS",
    "colour_is_supported",
    "create_guarded_launch",
    "enable_ansi",
    "force_kill_tree",
    "is_reparse_point",
    "key_reader",
    "kill_pid_tree",
    "pid_is_alive",
    "posix_shell",
    "prepare_stdio_encoding",
    "raw_console",
    "replace_atomic",
    "request_group_stop",
    "resolve_executable",
    "shell_argv",
    "shell_kind",
    "stop_pid_group",
    "try_lock_exclusive",
    "unlock",
]
