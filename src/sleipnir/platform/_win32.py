"""Raw ctypes bindings against ``kernel32``/``user32``/``gdi32``.

Structural only: structs, function prototypes, and the numeric constants that
name them. No policy and no docstrings-that-explain-why live here -- those
belong in ``platform/_windows.py`` (process/console/lock policy) and
``capabilities/computer/_windows.py`` (desktop-control policy), so that
either of those can be reviewed against MSDN's own naming without wading
through prose, and so a struct is declared exactly once regardless of how
many policy modules need it.

Imported only on ``sys.platform == "win32"``; every name here is undefined
elsewhere, which is exactly the point of the seam in ``platform/__init__.py``.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as w

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

ULONG_PTR = ctypes.c_size_t

# ---------------------------------------------------------------------------
# File locking (LockFileEx / UnlockFileEx -- msvcrt.locking is used instead
# in _windows.py for the run-lock, but these are kept for completeness of the
# binding set and for anything that later needs a byte-range rather than a
# whole-file lock).
# ---------------------------------------------------------------------------

LOCKFILE_EXCLUSIVE_LOCK = 0x00000002
LOCKFILE_FAIL_IMMEDIATELY = 0x00000001

# ---------------------------------------------------------------------------
# Console
# ---------------------------------------------------------------------------

STD_INPUT_HANDLE = -10
STD_OUTPUT_HANDLE = -11

ENABLE_ECHO_INPUT = 0x0004
ENABLE_LINE_INPUT = 0x0002
ENABLE_PROCESSED_INPUT = 0x0001
ENABLE_VIRTUAL_TERMINAL_INPUT = 0x0200
ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
ENABLE_PROCESSED_OUTPUT = 0x0001

CP_UTF8 = 65001

kernel32.GetStdHandle.argtypes = [w.DWORD]
kernel32.GetStdHandle.restype = w.HANDLE
kernel32.GetConsoleMode.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
kernel32.GetConsoleMode.restype = w.BOOL
kernel32.SetConsoleMode.argtypes = [w.HANDLE, w.DWORD]
kernel32.SetConsoleMode.restype = w.BOOL
kernel32.SetConsoleOutputCP.argtypes = [w.UINT]
kernel32.SetConsoleOutputCP.restype = w.BOOL
kernel32.SetConsoleCP.argtypes = [w.UINT]
kernel32.SetConsoleCP.restype = w.BOOL

# ---------------------------------------------------------------------------
# Process / job objects
# ---------------------------------------------------------------------------

CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000

JobObjectExtendedLimitInformation = 9
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_ALL_ACCESS = 0x1F001F
PROCESS_SET_QUOTA = 0x0100
PROCESS_TERMINATE = 0x0001
SYNCHRONIZE = 0x00100000


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", w.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", w.DWORD),
        ("Affinity", ctypes.POINTER(ctypes.c_ulong)),
        ("PriorityClass", w.DWORD),
        ("SchedulingClass", w.DWORD),
    ]


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_uint64)
        for name in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
kernel32.CreateJobObjectW.restype = w.HANDLE
kernel32.OpenJobObjectW.argtypes = [w.DWORD, w.BOOL, w.LPCWSTR]
kernel32.OpenJobObjectW.restype = w.HANDLE
kernel32.SetInformationJobObject.argtypes = [
    w.HANDLE,
    ctypes.c_int,
    ctypes.c_void_p,
    w.DWORD,
]
kernel32.SetInformationJobObject.restype = w.BOOL
kernel32.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
kernel32.AssignProcessToJobObject.restype = w.BOOL
kernel32.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
kernel32.TerminateJobObject.restype = w.BOOL
kernel32.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
kernel32.OpenProcess.restype = w.HANDLE
kernel32.GetCurrentProcess.restype = w.HANDLE
kernel32.CloseHandle.argtypes = [w.HANDLE]
kernel32.CloseHandle.restype = w.BOOL
kernel32.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
kernel32.WaitForSingleObject.restype = w.DWORD
kernel32.GenerateConsoleCtrlEvent.argtypes = [w.DWORD, w.DWORD]
kernel32.GenerateConsoleCtrlEvent.restype = w.BOOL

WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102
INFINITE = 0xFFFFFFFF

CTRL_BREAK_EVENT = 1

HANDLER_ROUTINE = ctypes.WINFUNCTYPE(w.BOOL, w.DWORD)
kernel32.SetConsoleCtrlHandler.argtypes = [HANDLER_ROUTINE, w.BOOL]
kernel32.SetConsoleCtrlHandler.restype = w.BOOL

shell32.IsUserAnAdmin.restype = w.BOOL

kernel32.GetCurrentProcessId.argtypes = []
kernel32.GetCurrentProcessId.restype = w.DWORD
kernel32.ProcessIdToSessionId.argtypes = [w.DWORD, ctypes.POINTER(w.DWORD)]
kernel32.ProcessIdToSessionId.restype = w.BOOL

# ---------------------------------------------------------------------------
# DPI awareness
# ---------------------------------------------------------------------------

#: ``DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2``. A sentinel handle value,
#: not a real pointer -- this is how the Win32 headers define it.
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)

user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
user32.SetProcessDpiAwarenessContext.restype = w.BOOL

# ---------------------------------------------------------------------------
# Input injection (SendInput)
# ---------------------------------------------------------------------------

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000

WHEEL_DELTA = 120

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", w.WORD),
        ("wScan", w.WORD),
        ("dwFlags", w.DWORD),
        ("time", w.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", w.LONG),
        ("dy", w.LONG),
        ("mouseData", w.DWORD),
        ("dwFlags", w.DWORD),
        ("time", w.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _InputUnion(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", w.DWORD), ("u", _InputUnion)]


user32.SendInput.argtypes = [w.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = w.UINT
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.SetCursorPos.restype = w.BOOL

# ---------------------------------------------------------------------------
# Screen capture (GDI)
# ---------------------------------------------------------------------------

SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0
BI_RGB = 0


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", w.DWORD),
        ("biWidth", w.LONG),
        ("biHeight", w.LONG),
        ("biPlanes", w.WORD),
        ("biBitCount", w.WORD),
        ("biCompression", w.DWORD),
        ("biSizeImage", w.DWORD),
        ("biXPelsPerMeter", w.LONG),
        ("biYPelsPerMeter", w.LONG),
        ("biClrUsed", w.DWORD),
        ("biClrImportant", w.DWORD),
    ]


user32.GetDC.argtypes = [w.HWND]
user32.GetDC.restype = w.HDC
user32.ReleaseDC.argtypes = [w.HWND, w.HDC]
user32.ReleaseDC.restype = ctypes.c_int
gdi32.CreateCompatibleDC.argtypes = [w.HDC]
gdi32.CreateCompatibleDC.restype = w.HDC
gdi32.CreateCompatibleBitmap.argtypes = [w.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = w.HBITMAP
gdi32.SelectObject.argtypes = [w.HDC, w.HGDIOBJ]
gdi32.SelectObject.restype = w.HGDIOBJ
gdi32.BitBlt.argtypes = [
    w.HDC,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    w.HDC,
    ctypes.c_int,
    ctypes.c_int,
    w.DWORD,
]
gdi32.BitBlt.restype = w.BOOL
gdi32.GetDIBits.argtypes = [
    w.HDC,
    w.HBITMAP,
    w.UINT,
    w.UINT,
    ctypes.c_void_p,
    ctypes.c_void_p,
    w.UINT,
]
gdi32.GetDIBits.restype = ctypes.c_int
gdi32.DeleteObject.argtypes = [w.HGDIOBJ]
gdi32.DeleteObject.restype = w.BOOL
gdi32.DeleteDC.argtypes = [w.HDC]
gdi32.DeleteDC.restype = w.BOOL


__all__ = [name for name in dir() if not name.startswith("_")]
