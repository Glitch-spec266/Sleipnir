"""Quartz backend: synthetic input through ``CGEventPost``.

macOS has no ``/dev/uinput`` and no ``SendInput``. The equivalent is Quartz:
build a ``CGEvent`` and post it to the HID event tap, which puts it into the
same stream a real keyboard feeds. Reached through ``ctypes`` rather than
PyObjC for the same reason ``_windows.py`` uses ``ctypes`` for ``user32`` --
the frameworks are already on every Mac and a binding is not worth a
dependency the rest of Sleipnir would then carry.

**Consent, not sandboxing, is what gates this.** The App Sandbox does block
``CGEventPost``, but it applies to Mac App Store apps and to nothing else; a
``pip``-installed CLI is not sandboxed. What actually stands in the way is
TCC: without the **Accessibility** grant every posted event is silently
dropped -- no error, no exception, the keystroke simply never lands. Silent
failure is the one outcome this package exists to prevent, so
``ensure_daemon`` refuses to proceed without the grant instead of letting a
caller believe it typed something.

Two consequences of TCC worth knowing before debugging a "permission is
granted but nothing happens":

* **The grant attaches to the responsible process, not to this script.**
  Run under Terminal.app and it is *Terminal* that must be ticked in System
  Settings -> Privacy & Security -> Accessibility. Arcaflame will never
  appear in that list by itself, which is exactly the sort of thing people
  spend an hour hunting for.
* **Secure input blocks keystrokes outright.** While a password field has
  secure event input active, synthetic keys are refused whatever TCC says --
  the local equivalent of the UAC secure desktop on Windows.

Frameworks are loaded lazily rather than at import, so this module imports
on Linux and Windows too. That is what lets the key-vocabulary parity test
run everywhere instead of only on a Mac.
"""

from __future__ import annotations

import ctypes
import shutil
import subprocess
import time
from ctypes import c_bool, c_double, c_int32, c_uint16, c_uint32, c_uint64, c_void_p
from pathlib import Path

from sleipnir.capabilities.computer._backend import CapabilityError, Probe

_CG_PATH = "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
_AS_PATH = "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"

# CGEventType
_MOUSE_MOVED = 5
_LEFT_DOWN, _LEFT_UP = 1, 2
_RIGHT_DOWN, _RIGHT_UP = 3, 4
_OTHER_DOWN, _OTHER_UP = 25, 26

# CGMouseButton
_BUTTON_LEFT, _BUTTON_RIGHT, _BUTTON_CENTER = 0, 1, 2

_HID_EVENT_TAP = 0        # kCGHIDEventTap — the earliest point in the stream
_SCROLL_UNIT_LINE = 1     # kCGScrollEventUnitLine

# CGEventFlags, for chords
_FLAG_SHIFT = 0x00020000
_FLAG_CONTROL = 0x00040000
_FLAG_OPTION = 0x00080000
_FLAG_COMMAND = 0x00100000


class _CGPoint(ctypes.Structure):
    _fields_ = [("x", c_double), ("y", c_double)]


#: Virtual key codes (``kVK_*``). The *names* are the cross-platform
#: contract and must match ``_linux.KEYCODES`` exactly; the numbers are
#: Quartz's and are not comparable with evdev or with Windows VKs.
#:
#: ``delete`` is forward-delete (117) rather than 51, which is backspace --
#: the same split the other two backends make, so a plan written on Linux
#: means the same key here.
KEYCODES: dict[str, int] = {
    "esc": 53, "1": 18, "2": 19, "3": 20, "4": 21, "5": 23, "6": 22, "7": 26,
    "8": 28, "9": 25, "0": 29, "minus": 27, "equal": 24, "backspace": 51,
    "tab": 48, "q": 12, "w": 13, "e": 14, "r": 15, "t": 17, "y": 16, "u": 32,
    "i": 34, "o": 31, "p": 35, "enter": 36, "ctrl": 59, "a": 0, "s": 1,
    "d": 2, "f": 3, "g": 5, "h": 4, "j": 38, "k": 40, "l": 37,
    "semicolon": 41, "shift": 56, "backslash": 42, "z": 6, "x": 7, "c": 8,
    "v": 9, "b": 11, "n": 45, "m": 46, "comma": 43, "dot": 47, "slash": 44,
    "alt": 58, "space": 49, "f1": 122, "f2": 120, "f3": 99, "f4": 118,
    "f5": 96, "f6": 97, "f7": 98, "f8": 100, "f9": 101, "f10": 109,
    "f11": 103, "f12": 111, "home": 115, "up": 126, "pageup": 116,
    "left": 123, "right": 124, "end": 119, "down": 125, "pagedown": 121,
    "insert": 114, "delete": 117, "super": 55, "meta": 55,
}

#: Modifier keycodes carry a flag mask as well as a key event. Posting the
#: key alone is enough for some applications and silently ignored by others;
#: setting the mask on the events inside the chord is what makes Cmd-T open
#: a tab rather than type a "t".
MODIFIER_FLAGS: dict[int, int] = {
    56: _FLAG_SHIFT,
    59: _FLAG_CONTROL,
    58: _FLAG_OPTION,
    55: _FLAG_COMMAND,
}

BUTTON_CODES: dict[str, tuple[int, int, int]] = {
    "left": (_LEFT_DOWN, _LEFT_UP, _BUTTON_LEFT),
    "right": (_RIGHT_DOWN, _RIGHT_UP, _BUTTON_RIGHT),
    "middle": (_OTHER_DOWN, _OTHER_UP, _BUTTON_CENTER),
}

#: Characters that are a key press rather than text. Same table shape as the
#: Windows backend: everything else goes through the Unicode path, so there
#: is no shift handling and no keyboard-layout assumption anywhere here.
_TYPED_AS_KEY: dict[str, int] = {"\n": 36, "\r": 36, "\t": 48}

_frameworks: tuple[ctypes.CDLL, ctypes.CDLL] | None = None


def _load() -> tuple[ctypes.CDLL, ctypes.CDLL]:
    """Load CoreGraphics and ApplicationServices, once, on first use.

    Lazy on purpose: at import time this module must not require a Mac, or
    the shared key vocabulary could only be tested on one platform.
    """
    global _frameworks
    if _frameworks is not None:
        return _frameworks
    try:
        cg = ctypes.CDLL(_CG_PATH)
        appservices = ctypes.CDLL(_AS_PATH)
    except OSError as exc:  # pragma: no cover - only reachable off macOS
        raise CapabilityError(f"Quartz is not available on this host: {exc}") from exc

    cg.CGEventCreateKeyboardEvent.argtypes = [c_void_p, c_uint16, c_bool]
    cg.CGEventCreateKeyboardEvent.restype = c_void_p
    cg.CGEventCreateMouseEvent.argtypes = [c_void_p, c_uint32, _CGPoint, c_uint32]
    cg.CGEventCreateMouseEvent.restype = c_void_p
    cg.CGEventCreateScrollWheelEvent.argtypes = [c_void_p, c_uint32, c_uint32, c_int32]
    cg.CGEventCreateScrollWheelEvent.restype = c_void_p
    cg.CGEventCreate.argtypes = [c_void_p]
    cg.CGEventCreate.restype = c_void_p
    cg.CGEventGetLocation.argtypes = [c_void_p]
    cg.CGEventGetLocation.restype = _CGPoint
    cg.CGEventSetFlags.argtypes = [c_void_p, c_uint64]
    cg.CGEventSetFlags.restype = None
    cg.CGEventKeyboardSetUnicodeString.argtypes = [c_void_p, c_uint32, ctypes.POINTER(c_uint16)]
    cg.CGEventKeyboardSetUnicodeString.restype = None
    cg.CGEventPost.argtypes = [c_uint32, c_void_p]
    cg.CGEventPost.restype = None
    cg.CFRelease.argtypes = [c_void_p]
    cg.CFRelease.restype = None
    cg.CGMainDisplayID.argtypes = []
    cg.CGMainDisplayID.restype = c_uint32
    cg.CGDisplayPixelsWide.argtypes = [c_uint32]
    cg.CGDisplayPixelsWide.restype = ctypes.c_size_t
    cg.CGDisplayPixelsHigh.argtypes = [c_uint32]
    cg.CGDisplayPixelsHigh.restype = ctypes.c_size_t

    appservices.AXIsProcessTrusted.argtypes = []
    appservices.AXIsProcessTrusted.restype = c_bool

    _frameworks = (cg, appservices)
    return _frameworks


def _post(event: c_void_p | int | None, flags: int = 0) -> None:
    """Post one event and release it.

    Every ``CGEventCreate*`` returns a retained object. Posting does not
    consume it, so skipping ``CFRelease`` leaks one event per keystroke --
    invisible at a handful and very visible over a long run.
    """
    cg, _ = _load()
    if not event:
        raise CapabilityError("Quartz refused to create an event")
    if flags:
        cg.CGEventSetFlags(event, flags)
    cg.CGEventPost(_HID_EVENT_TAP, event)
    cg.CFRelease(event)


def accessibility_granted() -> bool:
    """Whether this process may post events into other applications.

    ``AXIsProcessTrusted`` asks without prompting. The prompting variant is
    deliberately not used: a probe that throws a system dialog at someone
    running ``doctor`` is a surprise, and the grant needs a restart of the
    responsible process to take effect anyway.
    """
    try:
        _, appservices = _load()
    except CapabilityError:  # pragma: no cover - only reachable off macOS
        return False
    return bool(appservices.AXIsProcessTrusted())


def _has_display() -> bool:
    """Whether there is a window server to inject into at all.

    False over plain SSH into a headless Mac, which is the macOS equivalent
    of the Session-0 case the Windows backend checks for.
    """
    try:
        cg, _ = _load()
    except CapabilityError:  # pragma: no cover - only reachable off macOS
        return False
    return bool(cg.CGMainDisplayID())


def ensure_daemon(timeout_s: float = 5.0) -> None:
    """No daemon on macOS -- but this is where the consent gate belongs.

    Without the Accessibility grant ``CGEventPost`` fails *silently*: the
    call succeeds, the event goes nowhere, and a caller told "click at
    400,300" would carry on believing it had. Refusing here is the whole
    reason this function is not simply a no-op like the Windows one.
    """
    if not _has_display():
        raise CapabilityError(
            "no window server on this host — synthetic input needs a logged-in "
            "desktop session, not an SSH connection to a headless Mac"
        )
    if not accessibility_granted():
        raise CapabilityError(
            "Accessibility permission has not been granted, so posted input "
            "would be silently discarded. Grant it in System Settings → "
            "Privacy & Security → Accessibility, then restart this process. "
            "Note the grant attaches to the app running Sleipnir — usually "
            "Terminal or iTerm — not to Sleipnir itself."
        )


def type_text(text: str, *, key_delay_ms: int) -> None:
    """Type into whatever window currently has focus.

    Characters are delivered with ``CGEventKeyboardSetUnicodeString`` on an
    otherwise empty key event, which types any character whatever the active
    layout is — the same reasoning as the Windows Unicode path, and the
    reason there is no shift handling here. Astral characters are passed as
    their two UTF-16 surrogates in a single call, which is what Quartz
    expects.
    """
    cg, _ = _load()
    delay = key_delay_ms / 1000.0
    for index, char in enumerate(text):
        if index and delay:
            time.sleep(delay)
        keycode = _TYPED_AS_KEY.get(char)
        if keycode is not None:
            _post(cg.CGEventCreateKeyboardEvent(None, keycode, True))
            _post(cg.CGEventCreateKeyboardEvent(None, keycode, False))
            continue
        units = _utf16_units(char)
        buffer = (c_uint16 * len(units))(*units)
        for down in (True, False):
            event = cg.CGEventCreateKeyboardEvent(None, 0, down)
            if not event:
                raise CapabilityError("Quartz refused to create a key event")
            cg.CGEventKeyboardSetUnicodeString(event, len(units), buffer)
            cg.CGEventPost(_HID_EVENT_TAP, event)
            cg.CFRelease(event)


def _utf16_units(char: str) -> list[int]:
    encoded = char.encode("utf-16-le")
    return [encoded[i] | (encoded[i + 1] << 8) for i in range(0, len(encoded), 2)]


def key_chord(codes: list[int]) -> None:
    """Press resolved key codes in order, release in reverse.

    Ordering is the caller's contract (``computer/__init__.py``), not this
    backend's. What is this backend's problem is the flag mask: a modifier
    posted only as a key event is honoured by some applications and ignored
    by others, so the accumulated mask is set on every event in the chord as
    well. Both mechanisms, because either alone has real gaps.
    """
    cg, _ = _load()
    flags = 0
    for code in codes:
        flags |= MODIFIER_FLAGS.get(code, 0)
        _post(cg.CGEventCreateKeyboardEvent(None, code, True), flags)
    for code in reversed(codes):
        _post(cg.CGEventCreateKeyboardEvent(None, code, False), flags)
        flags &= ~MODIFIER_FLAGS.get(code, 0)


def screen_size() -> tuple[int, int]:
    """``(width, height)`` of the main display, in points."""
    cg, _ = _load()
    display = cg.CGMainDisplayID()
    return int(cg.CGDisplayPixelsWide(display)), int(cg.CGDisplayPixelsHigh(display))


def _cursor_location() -> _CGPoint:
    """Where the pointer is now.

    Needed because a Quartz click carries its own coordinates rather than
    happening wherever the cursor happens to be — clicking without this
    would teleport the pointer to (0, 0).
    """
    cg, _ = _load()
    probe_event = cg.CGEventCreate(None)
    if not probe_event:
        raise CapabilityError("Quartz refused to report the cursor location")
    point = cg.CGEventGetLocation(probe_event)
    cg.CFRelease(probe_event)
    return point


def move_mouse(x: int, y: int) -> None:
    cg, _ = _load()
    _post(cg.CGEventCreateMouseEvent(None, _MOUSE_MOVED, _CGPoint(float(x), float(y)), 0))


def click(button: str) -> None:
    cg, _ = _load()
    down, up, index = BUTTON_CODES[button]
    at = _cursor_location()
    _post(cg.CGEventCreateMouseEvent(None, down, at, index))
    _post(cg.CGEventCreateMouseEvent(None, up, at, index))


def scroll(amount: int) -> None:
    """Positive scrolls up, negative down.

    Quartz already uses positive-is-up for line units, so the sign passes
    through unchanged — the contract and the platform happen to agree here.
    """
    cg, _ = _load()
    _post(cg.CGEventCreateScrollWheelEvent(None, _SCROLL_UNIT_LINE, 1, int(amount)))


def screenshot(destination: Path) -> str:
    """Capture the screen with ``screencapture``.

    Shipped with macOS, so unlike the Linux backend there is nothing to
    choose between and nothing to install. ``-x`` suppresses the shutter
    sound; a capture that announces itself is startling when an agent takes
    one every few seconds.
    """
    tool = _screenshot_tool()
    if tool is None:  # pragma: no cover - screencapture is part of the OS
        raise CapabilityError("screencapture is missing from this macOS install")
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [tool, "-x", "-t", "png", str(destination)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0 or not destination.exists():
        raise CapabilityError(f"screencapture failed: {result.stderr.strip()[:200]}")
    return "screencapture"


def record_screen(destination: Path, *, duration_s: float) -> str:
    tool = _screenshot_tool()
    if tool is None:  # pragma: no cover - part of macOS
        raise CapabilityError("screencapture is missing from this macOS install")
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [tool, "-v", "-V", str(duration_s), str(destination)],
        capture_output=True,
        text=True,
        timeout=duration_s + 30,
        check=False,
    )
    if result.returncode != 0 or not destination.is_file():
        raise CapabilityError(f"screencapture video failed: {result.stderr.strip()[:200]}")
    return "screencapture"


def _screenshot_tool() -> str | None:
    return shutil.which("screencapture")


def probe() -> Probe:
    """What this Mac can actually do, for ``sleipnir doctor``.

    The ``Probe`` field names are Linux-shaped; this fills the same five
    with their macOS equivalents rather than growing a parallel shape:

    * ``input_injection`` — Accessibility is granted, so posted events land
    * ``daemon_running`` — always True; there is no daemon to start
    * ``uinput_writable`` — a window server exists to inject into
    * ``session_type`` — ``"aqua"``, macOS's own name for a GUI session

    Screen Recording cannot be honestly probed without taking a capture and
    inspecting it, so it is reported as a note rather than as a field. It is
    the one that fails *quietly*: without it a capture still succeeds and
    still writes a PNG, but other applications' windows are missing from it.
    """
    notes: list[str] = []
    has_display = _has_display()
    granted = accessibility_granted()
    tool = _screenshot_tool()

    if not has_display:
        notes.append(
            "no window server — input and capture need a logged-in desktop session"
        )
    if not granted:
        notes.append(
            "Accessibility not granted — posted input would be silently dropped. "
            "System Settings → Privacy & Security → Accessibility, then restart "
            "the terminal app (the grant attaches to it, not to Sleipnir)"
        )
    if tool is None:  # pragma: no cover - part of the OS
        notes.append("screencapture is missing from this macOS install")
    else:
        notes.append(
            "screen capture also needs Screen Recording; without it a capture "
            "still succeeds but other apps' windows are blank in it"
        )
    notes.append(
        "keystrokes are refused while a password field holds secure input — "
        "the local equivalent of the UAC secure desktop"
    )

    return Probe(
        input_injection=granted,
        daemon_running=True,
        screenshot_tool="screencapture" if tool else None,
        uinput_writable=has_display,
        session_type="aqua",
        notes=tuple(notes),
    )


__all__ = [
    "BUTTON_CODES",
    "KEYCODES",
    "MODIFIER_FLAGS",
    "accessibility_granted",
    "click",
    "ensure_daemon",
    "key_chord",
    "move_mouse",
    "probe",
    "screen_size",
    "screenshot",
    "record_screen",
    "scroll",
    "type_text",
]
