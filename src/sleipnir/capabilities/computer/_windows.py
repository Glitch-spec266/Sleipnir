"""SendInput / GDI backend: desktop control on Windows.

Where the Linux backend shells out to ``ydotool``, this calls the Win32 API
directly through ``ctypes``. There is no daemon, no device node, no udev
rule and nothing to install -- ``user32.SendInput`` and the GDI capture path
are present on every Windows install and need no elevation for the ordinary
case.

Three things here are not obvious and are load-bearing:

**DPI awareness must be set before the first capture.** Windows lies to a
DPI-unaware process about screen geometry: measured on the port's target
machine, the virtual screen reports 1536x960 instead of its real 1920x1200
under 125% scaling. Every coordinate an agent derives from such a screenshot
is then 1.25x off, and the failure mode is "the agent clicks slightly wrong"
-- far worse to debug than an outright error. ``SetProcessDpiAwarenessContext``
runs once at import, before anything can capture.

**Injection is weaker than ``/dev/uinput``.** ydotool injects below the input
stack, so its events are indistinguishable from a physical keyboard.
``SendInput`` is user-mode: UIPI blocks it from reaching windows of a more
privileged process, the UAC secure desktop is unreachable by design, and
software that checks ``LLMHF_INJECTED`` (anti-cheat, DRM, some banking apps)
can tell. ``probe()`` reports elevation for exactly this reason. Closing the
gap needs a signed kernel driver, which is out of scope.

**Auditing happens one layer up**, in ``computer/__init__.py``. This module
only performs raw injection and never records that it did.
"""

from __future__ import annotations

import ctypes
import os
import time
from pathlib import Path

from sleipnir.capabilities.computer import _png
from sleipnir.capabilities.computer._backend import CapabilityError, Probe
from sleipnir.platform import _win32

user32 = _win32.user32
gdi32 = _win32.gdi32
kernel32 = _win32.kernel32


def _set_dpi_awareness() -> bool:
    """Opt this process out of DPI virtualisation. Once, at import.

    Returns whether the call succeeded. Failure is not fatal and not
    necessarily a problem: the API refuses if awareness was already set --
    by an application manifest, by an embedding host, or by a second import
    of this module -- and in that case the process is already aware.
    """
    try:
        return bool(
            user32.SetProcessDpiAwarenessContext(
                _win32.DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
            )
        )
    except (AttributeError, OSError):  # pragma: no cover - pre-1703 Windows
        return False


DPI_AWARENESS_SET = _set_dpi_awareness()

#: Virtual-key codes for the same friendly names the Linux backend's evdev
#: table uses, so ``sleipnir computer key ctrl shift t`` means the same thing
#: on both platforms. The names are the contract; the numbers behind them are
#: not, and deliberately differ.
KEYCODES: dict[str, int] = {
    "esc": 0x1B, "1": 0x31, "2": 0x32, "3": 0x33, "4": 0x34, "5": 0x35,
    "6": 0x36, "7": 0x37, "8": 0x38, "9": 0x39, "0": 0x30, "minus": 0xBD,
    "equal": 0xBB, "backspace": 0x08, "tab": 0x09, "q": 0x51, "w": 0x57,
    "e": 0x45, "r": 0x52, "t": 0x54, "y": 0x59, "u": 0x55, "i": 0x49,
    "o": 0x4F, "p": 0x50, "enter": 0x0D, "ctrl": 0x11, "a": 0x41, "s": 0x53,
    "d": 0x44, "f": 0x46, "g": 0x47, "h": 0x48, "j": 0x4A, "k": 0x4B,
    "l": 0x4C, "semicolon": 0xBA, "shift": 0x10, "backslash": 0xDC,
    "z": 0x5A, "x": 0x58, "c": 0x43, "v": 0x56, "b": 0x42, "n": 0x4E,
    "m": 0x4D, "comma": 0xBC, "dot": 0xBE, "slash": 0xBF, "alt": 0x12,
    "space": 0x20, "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73,
    "f5": 0x74, "f6": 0x75, "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79,
    "f11": 0x7A, "f12": 0x7B, "home": 0x24, "up": 0x26, "pageup": 0x21,
    "left": 0x25, "right": 0x27, "end": 0x23, "down": 0x28, "pagedown": 0x22,
    "insert": 0x2D, "delete": 0x2E, "super": 0x5B, "meta": 0x5B,
}

#: Keys that live on the extended half of the old PC keyboard. Without
#: ``KEYEVENTF_EXTENDEDKEY`` these deliver as their numpad twins, so
#: ``key("ctrl", "home")`` would jump the caret by a page instead of to the
#: top of the document in applications that read the flag.
_EXTENDED = frozenset(
    {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B, 0x5C}
)

BUTTON_CODES: dict[str, tuple[int, int]] = {
    "left": (_win32.MOUSEEVENTF_LEFTDOWN, _win32.MOUSEEVENTF_LEFTUP),
    "right": (_win32.MOUSEEVENTF_RIGHTDOWN, _win32.MOUSEEVENTF_RIGHTUP),
    "middle": (_win32.MOUSEEVENTF_MIDDLEDOWN, _win32.MOUSEEVENTF_MIDDLEUP),
}

#: ``type_text`` sends most characters as raw Unicode, but a newline typed
#: that way is a literal U+000A that most GUI controls ignore. Both newline
#: forms become a real Return press instead, which is what ydotool's ``type``
#: does and what any caller typing a multi-line form expects.
_TYPED_AS_KEY = {"\n": 0x0D, "\r": 0x0D, "\t": 0x09}


# ---------------------------------------------------------------------------
# The one call into the OS
# ---------------------------------------------------------------------------


def _send(inputs: list[_win32.INPUT]) -> None:
    """Deliver a batch of events, or raise.

    Every injection in this module funnels through here so there is exactly
    one place that checks the return value and one seam for tests to
    intercept. ``SendInput`` reports how many events it accepted rather than
    raising, and a partial accept means the rest were dropped -- silently,
    which is the failure this project refuses to have.
    """
    if not inputs:
        return
    array = (_win32.INPUT * len(inputs))(*inputs)
    sent = user32.SendInput(len(array), array, ctypes.sizeof(_win32.INPUT))
    if sent != len(array):
        detail = ctypes.WinError(ctypes.get_last_error()).strerror or "unknown error"
        raise CapabilityError(
            f"SendInput delivered {sent} of {len(array)} events: {detail}. "
            "A window belonging to a more privileged process blocks input "
            "from an unelevated Sleipnir (UIPI); run `sleipnir doctor`."
        )


def _key_event(vk: int, *, up: bool) -> _win32.INPUT:
    flags = _win32.KEYEVENTF_KEYUP if up else 0
    if vk in _EXTENDED:
        flags |= _win32.KEYEVENTF_EXTENDEDKEY
    event = _win32.INPUT(type=_win32.INPUT_KEYBOARD)
    event.ki = _win32.KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=0)
    return event


def _unicode_event(code_unit: int, *, up: bool) -> _win32.INPUT:
    flags = _win32.KEYEVENTF_UNICODE | (_win32.KEYEVENTF_KEYUP if up else 0)
    event = _win32.INPUT(type=_win32.INPUT_KEYBOARD)
    event.ki = _win32.KEYBDINPUT(
        wVk=0, wScan=code_unit, dwFlags=flags, time=0, dwExtraInfo=0
    )
    return event


def _mouse_event(flags: int, *, dx: int = 0, dy: int = 0, data: int = 0) -> _win32.INPUT:
    event = _win32.INPUT(type=_win32.INPUT_MOUSE)
    event.mi = _win32.MOUSEINPUT(
        dx=dx, dy=dy, mouseData=data, dwFlags=flags, time=0, dwExtraInfo=0
    )
    return event


# ---------------------------------------------------------------------------
# Backend interface
# ---------------------------------------------------------------------------


def ensure_daemon(timeout_s: float = 5.0) -> None:
    """No-op: Windows has no input daemon to start.

    Kept so the public API in ``computer/__init__.py`` has one unconditional
    call site rather than a platform branch around it.
    """
    return None


def type_text(text: str, *, key_delay_ms: int) -> None:
    """Type into whatever window currently has focus.

    Characters go out as ``KEYEVENTF_UNICODE`` scan codes with no virtual-key
    at all, which types any character regardless of the active keyboard
    layout -- strictly better than a keycode table, and the reason there is
    no shift-handling here. Text is encoded UTF-16-LE and sent one code unit
    at a time, so an astral character (an emoji) is delivered as its two
    surrogates, which is exactly what Windows wants.

    ``key_delay_ms`` is not cosmetic: web sign-in forms commonly debounce or
    validate per keystroke, and a zero-delay burst gets dropped or mangled by
    them.
    """
    delay = key_delay_ms / 1000.0
    for index, char in enumerate(text):
        if index and delay:
            time.sleep(delay)
        vk = _TYPED_AS_KEY.get(char)
        if vk is not None:
            _send([_key_event(vk, up=False), _key_event(vk, up=True)])
            continue
        for unit in _utf16_units(char):
            _send([_unicode_event(unit, up=False), _unicode_event(unit, up=True)])


def _utf16_units(char: str) -> list[int]:
    encoded = char.encode("utf-16-le")
    return [
        encoded[i] | (encoded[i + 1] << 8) for i in range(0, len(encoded), 2)
    ]


def key_chord(codes: list[int]) -> None:
    """Press already-resolved virtual-key codes in order, release in reverse.

    Ordering is the caller's contract (``computer/__init__.py``), not this
    backend's. The whole chord is one ``SendInput`` batch so the OS cannot
    interleave another process's input in the middle of it and leave a
    modifier stuck down.
    """
    events = [_key_event(code, up=False) for code in codes]
    events += [_key_event(code, up=True) for code in reversed(codes)]
    _send(events)


def virtual_screen() -> tuple[int, int, int, int]:
    """``(left, top, width, height)`` of the whole virtual desktop.

    Not the primary monitor: coordinates are normalised against this, so a
    second monitor placed left of or above the primary one has negative
    origin coordinates and clicks there land correctly.
    """
    metrics = user32.GetSystemMetrics
    return (
        metrics(_win32.SM_XVIRTUALSCREEN),
        metrics(_win32.SM_YVIRTUALSCREEN),
        metrics(_win32.SM_CXVIRTUALSCREEN),
        metrics(_win32.SM_CYVIRTUALSCREEN),
    )


def move_mouse(x: int, y: int) -> None:
    left, top, width, height = virtual_screen()
    if width <= 1 or height <= 1:  # pragma: no cover - no display attached
        raise CapabilityError("no usable virtual screen; is this a headless session?")
    # ABSOLUTE coordinates are a 0..65535 fraction of the virtual desktop,
    # not pixels. The -1 matters: without it the rightmost pixel column is
    # unreachable, which is where scrollbars and close buttons live.
    normalised_x = round((x - left) * 65535 / (width - 1))
    normalised_y = round((y - top) * 65535 / (height - 1))
    _send(
        [
            _mouse_event(
                _win32.MOUSEEVENTF_MOVE
                | _win32.MOUSEEVENTF_ABSOLUTE
                | _win32.MOUSEEVENTF_VIRTUALDESK,
                dx=normalised_x,
                dy=normalised_y,
            )
        ]
    )


def click(button: str) -> None:
    down, up = BUTTON_CODES[button]
    _send([_mouse_event(down), _mouse_event(up)])


def scroll(amount: int) -> None:
    """Positive scrolls up, negative down -- one notch per unit."""
    _send([_mouse_event(_win32.MOUSEEVENTF_WHEEL, data=amount * _win32.WHEEL_DELTA)])


# ---------------------------------------------------------------------------
# Screen capture
# ---------------------------------------------------------------------------


class _BITMAPINFO(ctypes.Structure):
    """``BITMAPINFOHEADER`` plus room for the colour table.

    ``BI_RGB`` at 32bpp uses no palette, but ``GetDIBits`` is documented to
    take a ``BITMAPINFO``, so the trailing space is reserved rather than
    handing the API a struct shorter than its declared type.
    """

    _fields_ = [
        ("header", _win32.BITMAPINFOHEADER),
        ("colours", ctypes.c_uint32 * 3),
    ]


def _capture_bgra() -> tuple[bytes, int, int]:
    """BitBlt the whole virtual desktop into a top-down 32bpp buffer."""
    left, top, width, height = virtual_screen()
    if width <= 0 or height <= 0:  # pragma: no cover - no display attached
        raise CapabilityError("no usable virtual screen; is this a headless session?")

    screen_dc = user32.GetDC(None)
    if not screen_dc:
        raise CapabilityError("GetDC(NULL) failed; no desktop is attached to this session")
    memory_dc = None
    bitmap = None
    try:
        memory_dc = gdi32.CreateCompatibleDC(screen_dc)
        bitmap = gdi32.CreateCompatibleBitmap(screen_dc, width, height)
        if not memory_dc or not bitmap:
            raise CapabilityError("could not allocate a GDI capture surface")
        gdi32.SelectObject(memory_dc, bitmap)
        if not gdi32.BitBlt(
            memory_dc, 0, 0, width, height, screen_dc, left, top, _win32.SRCCOPY
        ):
            raise CapabilityError("BitBlt failed to copy the screen")

        info = _BITMAPINFO()
        info.header.biSize = ctypes.sizeof(_win32.BITMAPINFOHEADER)
        info.header.biWidth = width
        # Negative height requests top-down rows. A DIB is bottom-up by
        # default, and flipping 1200 rows in Python afterwards is pure waste.
        info.header.biHeight = -height
        info.header.biPlanes = 1
        info.header.biBitCount = 32
        info.header.biCompression = _win32.BI_RGB

        buffer = ctypes.create_string_buffer(width * height * 4)
        copied = gdi32.GetDIBits(
            memory_dc,
            bitmap,
            0,
            height,
            buffer,
            ctypes.byref(info),
            _win32.DIB_RGB_COLORS,
        )
        if copied != height:
            raise CapabilityError(f"GetDIBits returned {copied} of {height} scanlines")
        return buffer.raw, width, height
    finally:
        if bitmap:
            gdi32.DeleteObject(bitmap)
        if memory_dc:
            gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(None, screen_dc)


def _bgra_to_rgb(raw: bytes) -> bytes:
    """Drop the alpha byte and swap the blue and red channels.

    Both steps are extended-slice operations on a ``bytearray`` so the loop
    runs in C. A screenshot is a couple of million pixels and a per-pixel
    Python loop here would cost seconds per capture -- on a call an agent
    makes repeatedly.
    """
    pixels = bytearray(raw)
    del pixels[3::4]
    pixels[0::3], pixels[2::3] = pixels[2::3], pixels[0::3]
    return bytes(pixels)


def screenshot(destination: Path) -> str:
    raw, width, height = _capture_bgra()
    destination.write_bytes(_png.encode_rgb(_bgra_to_rgb(raw), width, height))
    return "gdi"


# ---------------------------------------------------------------------------
# Probe
# ---------------------------------------------------------------------------


def _is_elevated() -> bool:
    try:
        return bool(_win32.shell32.IsUserAnAdmin())
    except OSError:  # pragma: no cover - defensive
        return False


def _in_interactive_session() -> bool:
    """Whether this process has a desktop to inject into.

    A service running in Session 0 has none: ``SendInput`` there returns
    success and does nothing at all, which is the silent no-op this project
    refuses to ship. Session 0 is services only on every supported Windows.
    """
    session = _win32.w.DWORD()
    pid = kernel32.GetCurrentProcessId()
    if not kernel32.ProcessIdToSessionId(pid, ctypes.byref(session)):
        return False  # pragma: no cover - defensive
    return session.value != 0


def probe() -> Probe:
    """Windows facts in the Linux-shaped ``Probe``. See ``_backend.Probe``."""
    notes: list[str] = []
    interactive = _in_interactive_session()
    if not interactive:
        notes.append(
            "this process has no interactive desktop session (Session 0); "
            "SendInput would silently do nothing"
        )
    if not DPI_AWARENESS_SET:
        notes.append(
            "per-monitor DPI awareness was not set by Sleipnir; if it was not "
            "already set by the host, screenshots and coordinates may be scaled"
        )
    if not _is_elevated():
        # Deliberately a note and not a `ready` failure: unelevated is the
        # ordinary, working state for nearly every window on the desktop.
        notes.append(
            "not elevated — input cannot reach windows of elevated processes "
            "(UIPI), and never reaches the UAC secure desktop"
        )
    return Probe(
        input_injection=True,
        daemon_running=True,  # nothing to start
        screenshot_tool="gdi (BitBlt)",
        uinput_writable=interactive,
        session_type="windows",
        notes=tuple(notes),
    )


__all__ = [
    "BUTTON_CODES",
    "DPI_AWARENESS_SET",
    "KEYCODES",
    "click",
    "ensure_daemon",
    "key_chord",
    "move_mouse",
    "probe",
    "screenshot",
    "scroll",
    "type_text",
    "virtual_screen",
]
