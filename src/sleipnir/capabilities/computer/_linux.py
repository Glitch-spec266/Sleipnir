"""ydotool backend: kernel-level input injection via ``/dev/uinput``.

Wayland is the constraint that shapes this module. Under X11 a client could
synthesise input for any window; Wayland deliberately removed that, so the
only compositor-independent way to move the real pointer is to inject at the
kernel level through ``/dev/uinput``. That is what ``ydotool`` does, and it
is why ``sleipnir setup`` needs a udev rule rather than a plain package
install.

The consequence worth knowing: injected events are indistinguishable from a
physical keyboard, which is exactly the "robot at the desk" behaviour asked
for. Auditing happens one layer up, in ``computer/__init__.py`` -- this
module only performs the raw injection, never records that it did.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

from sleipnir.capabilities.computer._backend import CapabilityError, Probe

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

BUTTON_CODES = {"left": LEFT_CLICK, "right": RIGHT_CLICK, "middle": MIDDLE_CLICK}


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
            return
        time.sleep(0.1)
    raise CapabilityError(f"ydotoold did not create {YDOTOOL_SOCKET} within {timeout_s}s")


def _ydotool(*args: str, timeout_s: float = 15.0) -> None:
    """Run one ydotool invocation.

    Does not call ``ensure_daemon()`` itself: the public API in
    ``computer/__init__.py`` calls it exactly once per operation, ahead of
    dispatching here, so it stays the one seam a caller (or a test) can
    intercept.
    """
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


def type_text(text: str, *, key_delay_ms: int) -> None:
    """Type into whatever window currently has focus.

    ``key_delay_ms`` is not cosmetic: web sign-in forms commonly debounce or
    validate per keystroke, and a zero-delay burst gets dropped or mangled by
    them.
    """
    _ydotool("type", "--key-delay", str(key_delay_ms), "--", text)


def key_chord(codes: list[int]) -> None:
    """Press already-resolved key codes in order, release in reverse.

    Ordering is the caller's contract (``computer/__init__.py``), not this
    backend's: this function only knows how to speak it to ydotool.
    """
    sequence = [f"{code}:1" for code in codes] + [f"{code}:0" for code in reversed(codes)]
    _ydotool("key", *sequence)


def move_mouse(x: int, y: int) -> None:
    _ydotool("mousemove", "--absolute", "-x", str(x), "-y", str(y))


def click(button: str) -> None:
    _ydotool("click", BUTTON_CODES[button])


def scroll(amount: int) -> None:
    """Positive scrolls up, negative down."""
    _ydotool("mousemove", "--wheel", "-x", "0", "-y", str(amount))


def screenshot(destination: Path) -> str:
    """Capture to ``destination``, returning the tool that did it.

    The name is returned rather than re-derived by the caller because
    ``_screenshot_tool()`` walks ``PATH`` and the audit record has to name
    the tool that actually ran, not the one a second probe would pick.
    """
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
    return tool


__all__ = [
    "BUTTON_CODES",
    "KEYCODES",
    "LEFT_CLICK",
    "MIDDLE_CLICK",
    "RIGHT_CLICK",
    "YDOTOOL_SOCKET",
    "click",
    "ensure_daemon",
    "key_chord",
    "move_mouse",
    "probe",
    "screenshot",
    "scroll",
    "type_text",
]
