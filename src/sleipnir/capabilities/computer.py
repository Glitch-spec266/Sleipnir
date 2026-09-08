"""Keyboard, mouse, screen and shell control of the host machine.

Wayland is the constraint that shapes this module.  Under X11 a client could
synthesise input for any window; Wayland deliberately removed that, so the only
compositor-independent way to move the real pointer is to inject at the kernel
level through ``/dev/uinput``.  That is what ``ydotool`` does, and it is why
this needs a udev rule rather than a plain package install.

The consequence worth knowing: injected events are indistinguishable from a
physical keyboard, which is exactly the "robot at the desk" behaviour asked
for, and exactly why every call here is audited.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from sleipnir.capabilities import audit

YDOTOOL_SOCKET = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / ".ydotool_socket"

# evdev keycodes (linux/input-event-codes.h).  ydotool speaks numbers, not
# names, so the friendly layer lives here rather than in every caller.
KEYCODES: dict[str, int] = {
    "esc": 1, "1": 2, "2": 3, "3": 4, "4": 5, "5": 6, "6": 7, "7": 8, "8": 9,
    "9": 10, "0": 11, "minus": 12, "equal": 13, "backspace": 14, "tab": 15,
    "q": 16, "w": 17, "e": 18, "r": 19, "t": 20, "y": 21, "u": 22, "i": 23,
    "o": 24, "p": 25, "enter": 28, "ctrl": 29, "a": 30, "s": 31, "d": 32,
    "f": 33, "g": 34, "h": 35, "j": 36, "k": 37, "l": 38, "semicolon": 39,
    "shift": 42, "backslash": 43, "z": 44, "x": 45, "c": 46, "v": 47, "b": 48,
    "n": 49, "m": 50, "comma": 51, "dot": 52, "slash": 53, "alt": 56,
    "space": 57, "f1": 59, "f2": 60, "f3": 61, "f4": 62, "f5": 63, "f6": 64,
    "f7": 65, "f8": 66, "f9": 67, "f10": 68, "f11": 87, "f12": 88,
    "home": 102, "up": 103, "pageup": 104, "left": 105, "right": 106,
    "end": 107, "down": 108, "pagedown": 109, "insert": 110, "delete": 111,
    "super": 125, "meta": 125,
}

LEFT_CLICK = "0xC0"
RIGHT_CLICK = "0xC1"
MIDDLE_CLICK = "0xC2"


class CapabilityError(RuntimeError):
    """A host capability was asked for and is genuinely unavailable.

    Raised rather than silently degraded: an agent told "click at 400,300" that
    quietly does nothing is worse than one that stops and says the pointer is
    not wired up.
    """


@dataclass(frozen=True)
class Probe:
    """What this machine can actually do, for ``sleipnir doctor``."""

    input_injection: bool
    daemon_running: bool
    screenshot_tool: str | None
    uinput_writable: bool
    session_type: str
    notes: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return self.input_injection and self.uinput_writable and bool(self.screenshot_tool)


def _screenshot_tool() -> str | None:
    # Order matters: spectacle is KDE's own and is the only one that works on
    # KWin.  grim is wlroots-only and will fail on KDE despite being present.
    for candidate in ("spectacle", "grim", "gnome-screenshot", "import"):
        if shutil.which(candidate):
            if candidate == "grim" and "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", ""):
                continue
            return candidate
    return None


def probe() -> Probe:
    notes: list[str] = []
    uinput = Path("/dev/uinput")
    writable = os.access(uinput, os.W_OK)
    if uinput.exists() and not writable:
        notes.append("/dev/uinput exists but is not writable — run `sleipnir setup`")
    has_ydotool = shutil.which("ydotool") is not None
    if not has_ydotool:
        notes.append("ydotool is not installed — run `sleipnir setup`")
    running = YDOTOOL_SOCKET.exists()
    tool = _screenshot_tool()
    if tool is None:
        notes.append("no screenshot tool found (install spectacle)")
    return Probe(
        input_injection=has_ydotool,
        daemon_running=running,
        screenshot_tool=tool,
        uinput_writable=writable,
        session_type=os.environ.get("XDG_SESSION_TYPE", "unknown"),
        notes=tuple(notes),
    )


def ensure_daemon(timeout_s: float = 5.0) -> None:
    """Start ``ydotoold`` if it is not already listening.

    Started detached and left running: the socket is the handshake, so a
    restarted console reattaches to the existing daemon rather than spawning a
    second one that would fight it for ``/dev/uinput``.
    """
    if YDOTOOL_SOCKET.exists():
        return
    if shutil.which("ydotoold") is None:
        raise CapabilityError("ydotoold is not installed; run `sleipnir setup`")
    if not os.access("/dev/uinput", os.W_OK):
        raise CapabilityError(
            "/dev/uinput is not writable by this user; run `sleipnir setup` "
            "and start a new login session so the `input` group applies"
        )
    subprocess.Popen(  # noqa: S603 - fixed argv, no shell
        ["ydotoold", f"--socket-path={YDOTOOL_SOCKET}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if YDOTOOL_SOCKET.exists():
            audit.record("desktop.daemon_started", {"socket": str(YDOTOOL_SOCKET)})
            return
        time.sleep(0.1)
    raise CapabilityError(f"ydotoold did not create {YDOTOOL_SOCKET} within {timeout_s}s")


def _ydotool(*args: str, timeout_s: float = 15.0) -> None:
    ensure_daemon()
    env = dict(os.environ, YDOTOOL_SOCKET=str(YDOTOOL_SOCKET))
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["ydotool", *args],
        capture_output=True,
        text=True,
        timeout=timeout_s,
        env=env,
        check=False,
    )
    if result.returncode != 0:
        raise CapabilityError(f"ydotool {args[0]} failed: {result.stderr.strip()[:200]}")


def type_text(text: str, *, key_delay_ms: int = 12) -> None:
    """Type into whatever window currently has focus.

    ``key_delay_ms`` is not cosmetic: web sign-in forms commonly debounce or
    validate per keystroke, and a zero-delay burst gets dropped or mangled by
    them.  Twelve milliseconds is roughly a fast human.
    """
    _ydotool("type", "--key-delay", str(key_delay_ms), "--", text)
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
    sequence = [f"{code}:1" for code in codes] + [f"{code}:0" for code in reversed(codes)]
    _ydotool("key", *sequence)
    audit.record("desktop.key", {"combo": list(combo)})


def copy() -> None:
    """Send the standard Linux terminal copy chord to the focused application.

    The clipboard remains owned by the desktop/application, so its MIME payload
    is preserved: selected text stays text and a selected image stays an image.
    """
    key("ctrl", "shift", "c")
    audit.record("desktop.clipboard_copy", {"combo": "ctrl+shift+c"})


def paste() -> None:
    """Send the standard Linux terminal paste chord to the focused application."""
    key("ctrl", "shift", "v")
    audit.record("desktop.clipboard_paste", {"combo": "ctrl+shift+v"})


def move_mouse(x: int, y: int) -> None:
    _ydotool("mousemove", "--absolute", "-x", str(x), "-y", str(y))
    audit.record("desktop.move_mouse", {"x": x, "y": y})


def click(button: str = "left") -> None:
    code = {"left": LEFT_CLICK, "right": RIGHT_CLICK, "middle": MIDDLE_CLICK}.get(button)
    if code is None:
        raise CapabilityError(f"unknown mouse button: {button!r}")
    _ydotool("click", code)
    audit.record("desktop.click", {"button": button})


def scroll(amount: int) -> None:
    """Positive scrolls up, negative down."""
    _ydotool("mousemove", "--wheel", "-x", "0", "-y", str(amount))
    audit.record("desktop.scroll", {"amount": amount})


def screenshot(path: str | Path) -> Path:
    """Capture the full screen to ``path``.

    The agent reads the resulting image itself; this function never returns
    pixel data, so a screenshot cannot accidentally become prompt text.
    """
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    tool = _screenshot_tool()
    argv = {
        "spectacle": ["spectacle", "-b", "-n", "-f", "-o", str(destination)],
        "grim": ["grim", str(destination)],
        "gnome-screenshot": ["gnome-screenshot", "-f", str(destination)],
        "import": ["import", "-window", "root", str(destination)],
    }.get(tool or "")
    if argv is None:
        raise CapabilityError("no screenshot tool available; install spectacle")
    result = subprocess.run(argv, capture_output=True, text=True, timeout=30, check=False)  # noqa: S603
    if result.returncode != 0 or not destination.exists():
        raise CapabilityError(f"{tool} failed: {result.stderr.strip()[:200]}")
    audit.record("desktop.screenshot", {"path": str(destination), "tool": tool})
    return destination


def run(command: str, *, cwd: str | Path | None = None, timeout_s: float = 300.0) -> subprocess.CompletedProcess[str]:
    """Run a shell command as the operator, with the operator's environment.

    This is the deliberate opposite of the executor's credential-stripped
    worker spawn.  It exists so the console can install packages, provision
    hosting and drive CLIs the way a person at this keyboard would — and it is
    audited for exactly that reason.

    **This function is not a trust boundary, and narrowing it would not create
    one.**  Static analysis flags ``shell=True`` here; the flag is correct about
    the pattern and wrong about the consequence.  The only caller is a session
    that already holds full host control and its own shell, so anything that
    could be "smuggled" through this argument can simply be executed one line
    earlier.  Replacing this with an argv list would delete pipes, redirection
    and globbing — the reason an operator shell exists — while removing no
    capability from an attacker who is, by construction, already inside.

    The boundary that does exist is the worker lane: dispatched tasks keep the
    stripped environment and the confined workspace, and never reach this
    module at all.  If you are tempted to harden this function, check that
    separation instead; it is the one that carries weight.
    """
    audit.record("shell.run", {"command": command, "cwd": str(cwd or Path.cwd())})
    return subprocess.run(  # noqa: S602 - operator-authorised shell, by design
        command,
        shell=True,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )


__all__ = [
    "CapabilityError",
    "KEYCODES",
    "Probe",
    "click",
    "copy",
    "ensure_daemon",
    "key",
    "move_mouse",
    "paste",
    "probe",
    "run",
    "screenshot",
    "scroll",
    "type_text",
]
