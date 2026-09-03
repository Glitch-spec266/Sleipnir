"""Keyboard, mouse, screen and shell control of the host machine.

The public surface. Everything here is platform-neutral: it validates what a
caller asked for, records it, and hands the raw action to whichever backend
this machine has -- ``_linux`` (ydotool, injecting through ``/dev/uinput``)
or ``_windows`` (``SendInput`` and GDI). The two mechanisms differ in what
they can reach; the vocabulary a caller speaks does not.

**Auditing lives here and nowhere else.** Every function in the original
single-file module audited itself, and splitting it into backends is exactly
how one of them would eventually forget to. Backends perform raw injection
and never write to the log, so an unaudited host action cannot be reached
through this package's public API. The same argument applies to validation:
an unknown key name or mouse button is refused here, once, rather than
becoming two subtly different error messages.

The `text` key is on ``audit``'s forbidden list, so typed keystrokes are
recorded by length and never by content -- which is what makes it safe for
``secrets.type_into_focused_window`` to route through this module at all.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from sleipnir import platform
from sleipnir.capabilities import audit
from sleipnir.capabilities.computer._backend import CapabilityError, Probe

if platform.IS_WINDOWS:  # pragma: win32 cover
    from sleipnir.capabilities.computer import _windows as _impl
else:  # pragma: posix cover
    from sleipnir.capabilities.computer import _linux as _impl

#: The friendly key names this host understands, mapped to whatever the
#: active backend's injector speaks -- evdev keycodes on Linux, virtual-key
#: codes on Windows. The *names* are the cross-platform contract; the numbers
#: are an implementation detail of one backend and are not comparable across
#: the two. ``computer._linux.KEYCODES`` still holds the evdev table on any
#: platform for anything that genuinely needs it.
KEYCODES: dict[str, int] = _impl.KEYCODES

#: Accepted ``click()`` button names. The value shape differs per backend
#: (a ydotool code string, a pair of SendInput flags); only the keys are
#: public.
BUTTON_CODES = _impl.BUTTON_CODES

#: Start the input daemon if this platform has one. A no-op on Windows.
#: Called by name from each public function below rather than through
#: ``_impl`` so there is exactly one interceptable seam.
ensure_daemon = _impl.ensure_daemon


def probe() -> Probe:
    """What this machine can actually do, for ``sleipnir doctor``."""
    return _impl.probe()


def type_text(text: str, *, key_delay_ms: int = 12) -> None:
    """Type into whatever window currently has focus.

    ``key_delay_ms`` is not cosmetic: web sign-in forms commonly debounce or
    validate per keystroke, and a zero-delay burst gets dropped or mangled by
    them.  Twelve milliseconds is roughly a fast human.
    """
    ensure_daemon()
    _impl.type_text(text, key_delay_ms=key_delay_ms)
    audit.record("desktop.type", {"text": text, "chars": len(text)})


def key(*combo: str) -> None:
    """Press a chord, e.g. ``key("ctrl", "shift", "t")``.

    Modifiers are held for the whole chord and released in reverse order, which
    is what applications expect; releasing in press order leaves a modifier
    stuck down often enough to be a real bug.
    """
    codes = []
    for name in combo:
        code = KEYCODES.get(name.lower())
        if code is None:
            raise CapabilityError(f"unknown key name: {name!r}")
        codes.append(code)
    ensure_daemon()
    _impl.key_chord(codes)
    audit.record("desktop.key", {"combo": list(combo)})


def move_mouse(x: int, y: int) -> None:
    ensure_daemon()
    _impl.move_mouse(x, y)
    audit.record("desktop.move_mouse", {"x": x, "y": y})


def click(button: str = "left") -> None:
    if button not in BUTTON_CODES:
        raise CapabilityError(f"unknown mouse button: {button!r}")
    ensure_daemon()
    _impl.click(button)
    audit.record("desktop.click", {"button": button})


def scroll(amount: int) -> None:
    """Positive scrolls up, negative down."""
    ensure_daemon()
    _impl.scroll(amount)
    audit.record("desktop.scroll", {"amount": amount})


def screenshot(path: str | Path = "screen.png") -> Path:
    """Capture the full screen to ``path``.

    The agent reads the resulting image itself; this function never returns
    pixel data, so a screenshot cannot accidentally become prompt text.
    """
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    tool = _impl.screenshot(destination)
    audit.record("desktop.screenshot", {"path": str(destination), "tool": tool})
    return destination


def run(
    command: str, *, cwd: str | Path | None = None, timeout_s: float = 300.0
) -> subprocess.CompletedProcess[str]:
    """Run a shell command as the operator, with the operator's environment.

    This is the deliberate opposite of the executor's credential-stripped
    worker spawn.  It exists so the console can install packages, provision
    hosting and drive CLIs the way a person at this keyboard would — and it is
    audited for exactly that reason.

    The command goes to ``platform.shell_argv``, the same resolver
    ``checks.py`` uses for a plan's ``CommandCheck`` — one dialect for both,
    so an operator who verifies a command by hand here gets the same shell a
    plan gets. On Windows that is a POSIX ``sh`` when one is installed and
    ``cmd.exe`` otherwise; ``sleipnir doctor`` says which.

    **This function is not a trust boundary, and narrowing it would not create
    one.**  Static analysis flags handing a whole command line to a shell; the
    flag is correct about the pattern and wrong about the consequence.  The
    only caller is a session that already holds full host control and its own
    shell, so anything that could be "smuggled" through this argument can
    simply be executed one line earlier.  Refusing to invoke a shell would
    delete pipes, redirection and globbing — the reason an operator shell
    exists — while removing no capability from an attacker who is, by
    construction, already inside.

    The boundary that does exist is the worker lane: dispatched tasks keep the
    stripped environment and the confined workspace, and never reach this
    module at all.  If you are tempted to harden this function, check that
    separation instead; it is the one that carries weight.
    """
    audit.record("shell.run", {"command": command, "cwd": str(cwd or Path.cwd())})
    return subprocess.run(  # noqa: S603 - operator-authorised shell, by design
        platform.shell_argv(command),
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )


__all__ = [
    "BUTTON_CODES",
    "CapabilityError",
    "KEYCODES",
    "Probe",
    "click",
    "ensure_daemon",
    "key",
    "move_mouse",
    "probe",
    "run",
    "screenshot",
    "scroll",
    "type_text",
]
