"""Windows backend for the platform seam.

Every function here answers to the same contract ``_posix.py`` established;
see that module's and ``platform/__init__.py``'s docstrings for what each name
promises. Where the underlying mechanism differs in a way worth knowing, it is
explained inline rather than left to be discovered from a bug report.
"""

from __future__ import annotations

import contextlib
import ctypes
import ctypes.wintypes
import msvcrt
import os
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import IO, Any

from sleipnir.platform import LockUnavailable, _win32

# ---------------------------------------------------------------------------
# File locking -- runlog.py's RunLock and run_is_active()
# ---------------------------------------------------------------------------
#
# msvcrt.locking() locks (or unlocks) a byte range on the file *descriptor*
# starting at the file's current position, for a byte count -- unlike
# fcntl.flock, which always locks the whole file regardless of position, and
# is advisory: cooperating processes that check are kept out, but a plain
# read from a handle that never locked still succeeds. Windows range locks
# are *mandatory* system-wide: any read or write that overlaps a locked byte
# range fails with PermissionError, from any handle, even a read-only one
# opened by an unrelated process. RunLock also writes human-readable
# diagnostic content ("pid=...") starting at byte 0 of the same file, and
# run_is_active() reads that content back -- locking byte 0 would make that
# read fail with the lock still held (reproduced: a losing run_is_active()
# call raised PermissionError trying to read the winner's pid line). Locking
# a fixed byte far past any realistic content instead keeps the two uses --
# "is this file locked" and "what does this file say" -- from colliding.
# Locking past EOF is explicitly allowed on Windows (unlike flock on Linux),
# which is what makes this trick available at all.
_LOCK_OFFSET = 1 << 20
_LOCK_BYTES = 1


def try_lock_exclusive(handle: IO[Any]) -> None:
    handle.seek(_LOCK_OFFSET)
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, _LOCK_BYTES)
    except OSError as exc:
        raise LockUnavailable(str(exc)) from exc
    finally:
        handle.seek(0)


def unlock(handle: IO[Any]) -> None:
    handle.seek(_LOCK_OFFSET)
    with contextlib.suppress(OSError):
        # Already unlocked (e.g. a second unlock after a failed re-lock
        # attempt in run_is_active) raises; that is not an error to us.
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, _LOCK_BYTES)
    handle.seek(0)


# ---------------------------------------------------------------------------
# Process liveness -- executor.py's crash-recovery probe
# ---------------------------------------------------------------------------
#
# os.kill(pid, 0) -- the POSIX "does this pid exist" idiom -- is not
# meaningful on Windows: CPython's os.kill() there only special-cases
# CTRL_C_EVENT/CTRL_BREAK_EVENT and SIGTERM (as TerminateProcess); signal 0
# falls through to a raw call that fails with WinError 87 ("the parameter is
# incorrect") regardless of whether the pid is alive -- reproduced live, not
# theorised. The actual Windows probe is opening a handle and asking it
# whether it has finished.


def pid_is_alive(pid: int) -> bool:
    handle = _win32.kernel32.OpenProcess(_win32.SYNCHRONIZE, False, pid)
    if not handle:
        # ERROR_ACCESS_DENIED means a real, running process this account
        # cannot query -- treat as alive, mirroring the POSIX PermissionError
        # branch. Anything else (ERROR_INVALID_PARAMETER, most commonly)
        # means the pid does not currently name a process.
        return ctypes.get_last_error() == 5  # ERROR_ACCESS_DENIED
    try:
        # WAIT_TIMEOUT (still running) vs WAIT_OBJECT_0 (already exited and
        # signalled) -- a zero timeout makes this a poll, never a wait.
        return _win32.kernel32.WaitForSingleObject(handle, 0) == _win32.WAIT_TIMEOUT
    finally:
        _win32.kernel32.CloseHandle(handle)


# ---------------------------------------------------------------------------
# Console encoding and colour
# ---------------------------------------------------------------------------


def prepare_stdio_encoding() -> None:
    """Fix a real crash, not a cosmetic one.

    ``sys.stdout.encoding`` on a stock Windows CPython install is the
    console's legacy code page (cp1252, verified on this port's target
    machine) -- and both ``theme.py``'s box-drawing glyphs and
    ``console.py``'s lock icon are outside it. Left alone, the first
    ``sleipnir tui`` frame raises ``UnicodeEncodeError`` before anything
    useful is on screen. Switching the console's output code page to UTF-8
    *and* reconfiguring the Python-level stream both matter: the first makes
    conhost render what arrives correctly, the second stops Python rejecting
    the bytes before they are sent.
    """
    with contextlib.suppress(OSError):
        _win32.kernel32.SetConsoleOutputCP(_win32.CP_UTF8)
        _win32.kernel32.SetConsoleCP(_win32.CP_UTF8)
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(ValueError):
                reconfigure(encoding="utf-8", errors="replace")


def _std_handle(which: int) -> int:
    return _win32.kernel32.GetStdHandle(which)


def enable_ansi(stream: Any) -> bool:
    """Turn on VT escape processing for one std stream's console handle.

    Returns whether it actually took: redirected-to-a-file streams have no
    console handle, and ``SetConsoleMode`` fails cleanly for those, which is
    exactly the "no colour to a pipe" behaviour ``theme.py`` wants.
    """
    isatty = getattr(stream, "isatty", None)
    if not (isatty and isatty()):
        return False
    which = _win32.STD_OUTPUT_HANDLE if stream is sys.stdout else _win32.STD_INPUT_HANDLE
    handle = _std_handle(which)
    if not handle or handle == -1:
        return False
    mode = ctypes.wintypes.DWORD()
    if not _win32.kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
        return False
    new_mode = mode.value | _win32.ENABLE_VIRTUAL_TERMINAL_PROCESSING
    return bool(_win32.kernel32.SetConsoleMode(handle, new_mode))


def colour_is_supported(stream: Any) -> bool:
    """Windows consoles never set ``TERM``, so the POSIX rule
    (``TERM in (None, "", "dumb")`` -> no colour) would disable colour
    unconditionally here. The real signal is whether VT processing could be
    turned on at all.
    """
    if os.environ.get("NO_COLOR"):
        return False
    return enable_ansi(stream)


# ---------------------------------------------------------------------------
# Child process spawn and tree kill
# ---------------------------------------------------------------------------
#
# Windows has no process-group signal delivery the way POSIX does, so the
# guarantee is rebuilt from two different primitives rather than one:
#
#   * graceful stop  -> CTRL_BREAK_EVENT, which only reaches processes that
#     share a *console process group* -- the reason every spawn passes
#     CREATE_NEW_PROCESS_GROUP below, forming a fresh group whose leader is
#     the spawned process and which every descendant inherits automatically.
#   * forced tree kill -> ``taskkill /F /T``, which walks the live
#     parent-child PID graph at kill time. Unlike a job object assigned
#     after the fact, this has no race: it does not matter what the tree
#     looked like when it was created, only what it looks like now.
#
# The one guarantee POSIX's PR_SET_PDEATHSIG gave that neither of the above
# covers -- "if Sleipnir itself is hard-killed, the provider CLI dies with
# it, unconditionally" -- is what create_guarded_launch()/process_guard.py
# rebuild with a Windows job object instead. See that function's docstring.

CHILD_SPAWN_KWARGS: dict[str, Any] = {"creationflags": _win32.CREATE_NEW_PROCESS_GROUP}


def create_guarded_launch(argv: list[str]):
    """Wrap ``argv`` so the whole tree it spawns dies if Sleipnir itself is
    hard-killed -- the Windows analogue of ``PR_SET_PDEATHSIG``.

    A job object is created *before* anything runs, named so the guard
    process (which does not yet exist) can find it by name rather than by an
    inherited handle -- ``asyncio.create_subprocess_exec`` never exposes a
    child's raw handle before it starts running, so "spawn, then assign to a
    job" always has a window where a fast-forking child already escaped.
    Naming the job and having the guard open it by name before *it* spawns
    the real provider closes that window completely: nothing the provider
    forks can pre-date its own process's job membership.

    ``KILL_ON_JOB_CLOSE`` (set on the job here) makes the guarantee
    unconditional in a way ``PR_SET_PDEATHSIG`` was not: SIGTERM can be
    trapped and ignored by a stubborn provider; a job whose last handle
    closes terminates every member regardless of what any of them do.
    """
    job_name = f"sleipnir-{uuid.uuid4().hex}"
    handle = _win32.kernel32.CreateJobObjectW(None, job_name)
    if not handle:
        # No isolation available; still run the child rather than refuse.
        from sleipnir.platform import GuardedLaunch

        wrapped = [sys.executable, str(_guard_path()), "--", *argv]
        return GuardedLaunch(wrapped, close=lambda: None)

    info = _win32.JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = _win32.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    _win32.kernel32.SetInformationJobObject(
        handle,
        _win32.JobObjectExtendedLimitInformation,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )

    wrapped = [sys.executable, str(_guard_path()), "--job", job_name, "--", *argv]

    def _close() -> None:
        _win32.kernel32.CloseHandle(handle)

    from sleipnir.platform import GuardedLaunch

    return GuardedLaunch(wrapped, close=_close)


def _guard_path() -> Path:
    from sleipnir.platform import guard_script_path

    return guard_script_path()


def request_group_stop(proc: Any) -> str:
    """``CTRL_BREAK_EVENT`` to the child's console process group.

    Reaches the whole group precisely because every spawn already carries
    ``CREATE_NEW_PROCESS_GROUP`` -- that flag is what makes the *spawned*
    process, not Sleipnir itself, the group's leader and target. A process
    with no console control handler installed exits on ``CTRL_BREAK`` by
    default (verified: a plain Python child exits with
    ``STATUS_CONTROL_C_EXIT``), which is the same "does nothing special,
    just dies" behaviour an unhandled SIGTERM gives on POSIX.
    """
    with contextlib.suppress(Exception):
        proc.send_signal(signal.CTRL_BREAK_EVENT)
        return "CTRL_BREAK_EVENT"
    with contextlib.suppress(Exception):
        proc.terminate()
    return "TerminateProcess"


def force_kill_tree(proc: Any) -> str:
    """``taskkill /F /T`` -- forceful, whole-tree, race-free.

    Ships with every Windows install, so this needs no new dependency and no
    job object of its own; it is the right default for ``chat.py`` and
    ``capabilities/browser.py``, which (like their Linux counterparts) spawn
    their child directly rather than through the ``process_guard.py``
    wrapper ``process.py`` uses. It walks the *live* PID parent-child graph
    at the moment it runs rather than a job assigned at spawn time, so
    unlike a job object it carries no assignment race to reason about.
    """
    pid = getattr(proc, "pid", None)
    if pid is not None:
        result = subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            return "taskkill"
    with contextlib.suppress(Exception):
        proc.kill()
    return "TerminateProcess"


def stop_pid_group(pid: int) -> bool:
    """``CTRL_BREAK_EVENT`` to a process group discovered only as a bare pid
    (e.g. read back from a pid file across a restart -- ``browser.py``'s
    detached-Chromium case, which has no live Process object to call
    ``send_signal`` on). Requires the target to have been spawned with
    ``CREATE_NEW_PROCESS_GROUP`` in the first place, which every spawn in
    this codebase is (``CHILD_SPAWN_KWARGS``).
    """
    return bool(_win32.kernel32.GenerateConsoleCtrlEvent(_win32.CTRL_BREAK_EVENT, pid))


def kill_pid_tree(pid: int) -> None:
    subprocess.run(
        ["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, check=False
    )


# ---------------------------------------------------------------------------
# Shell selection -- checks.py's CommandCheck and computer.run()
# ---------------------------------------------------------------------------

#: Common Git for Windows install locations, checked when ``sh`` is not on
#: PATH -- the installer does not always add its ``usr\bin`` to PATH, only
#: ``cmd``, so a which()-only lookup misses a real, common install.
_GIT_SH_CANDIDATES = (
    r"C:\Program Files\Git\usr\bin\sh.exe",
    r"C:\Program Files\Git\bin\sh.exe",
    r"C:\Program Files (x86)\Git\usr\bin\sh.exe",
)


def posix_shell() -> Path | None:
    override = os.environ.get("SLEIPNIR_SHELL")
    if override:
        return Path(override)
    found = shutil.which("sh")
    if found:
        return Path(found)
    for candidate in _GIT_SH_CANDIDATES:
        path = Path(candidate)
        if path.exists():
            return path
    return None


def shell_argv(command: str) -> list[str]:
    """Prefer a POSIX shell (Git for Windows, MSYS2, ...) so
    ``plan.json``-authored ``CommandCheck`` commands stay portable across
    platforms unchanged; fall back to ``cmd.exe`` -- loudly, via
    ``shell_kind()`` -- only when none is found.
    """
    sh = posix_shell()
    if sh is not None:
        return [str(sh), "-c", command]
    comspec = os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe")
    return [comspec, "/c", command]


def shell_kind() -> str:
    return "posix" if posix_shell() is not None else "cmd"


# ---------------------------------------------------------------------------
# Executables
# ---------------------------------------------------------------------------


def resolve_executable(name: str) -> str:
    """Resolve through ``PATH`` explicitly.

    ``CreateProcess`` (what ``asyncio.create_subprocess_exec`` calls)
    appends ``.exe`` for a bare name, but does **not** resolve ``.cmd``/
    ``.bat`` shims -- which is exactly what npm-installed CLIs like
    ``codex`` are. Verified on this port's target machine: a bare ``npm``
    argv raises ``FileNotFoundError``; ``shutil.which("npm")`` resolves the
    ``.CMD`` path, and spawning that succeeds.
    """
    return shutil.which(name) or name


# ---------------------------------------------------------------------------
# Filesystem
# ---------------------------------------------------------------------------


def is_reparse_point(path: Path) -> bool:
    """True for a symlink *or* an NTFS junction.

    ``Path.is_symlink()`` alone misses junctions
    (``IO_REPARSE_TAG_MOUNT_POINT``) -- and unlike a symlink, creating a
    junction needs no privilege and no Developer Mode, so it is the more
    likely attack shape on a stock Windows install. Both set
    ``FILE_ATTRIBUTE_REPARSE_POINT``, which this checks directly rather than
    relying on a tag-specific stdlib helper.
    """
    try:
        attrs = os.lstat(path).st_file_attributes  # type: ignore[attr-defined]
    except (OSError, AttributeError):
        return path.is_symlink()
    return bool(attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def replace_atomic(src: Path, dst: Path) -> None:
    """``os.replace`` with a short bounded retry.

    Windows has no unlink-on-open: replacing a file another process has
    open (``sleipnir tui --watch`` holding ``plan.json``, say) raises
    ``PermissionError`` instead of the silent success POSIX gives. The
    retry covers the common case -- a reader between its own open and close
    -- without hiding a genuinely stuck lock; ``PermissionError`` still
    surfaces if every attempt fails.
    """
    last: OSError | None = None
    for attempt in range(10):
        try:
            os.replace(src, dst)
            return
        except PermissionError as exc:
            last = exc
            time.sleep(0.05 * (attempt + 1))
    assert last is not None
    raise last


# ---------------------------------------------------------------------------
# Console raw mode and key reading
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def raw_console() -> Iterator[bool]:
    """The cbreak equivalent: no line buffering, no echo, and Ctrl-C arrives
    as a byte (``\\x03``) rather than a ``KeyboardInterrupt``.

    Clearing ``ENABLE_PROCESSED_INPUT`` is what makes Ctrl-C a byte instead
    of an interrupt -- without it Windows raises ``KeyboardInterrupt`` in the
    main thread the moment it is pressed, but ``console.py``'s loop expects
    to *receive* ``"\\x03"`` as ordinary input and return cleanly. Restoring
    both handles' modes in ``finally`` matters exactly as much as it does on
    POSIX: a crash that skips it leaves the operator's next shell prompt
    silently un-echoing input, which reads as a hung terminal.
    """
    if not sys.stdin.isatty():
        yield False
        return
    hin = _std_handle(_win32.STD_INPUT_HANDLE)
    hout = _std_handle(_win32.STD_OUTPUT_HANDLE)
    saved_in = ctypes.wintypes.DWORD()
    saved_out = ctypes.wintypes.DWORD()
    _win32.kernel32.GetConsoleMode(hin, ctypes.byref(saved_in))
    _win32.kernel32.GetConsoleMode(hout, ctypes.byref(saved_out))
    raw_mode = saved_in.value & ~(
        _win32.ENABLE_ECHO_INPUT | _win32.ENABLE_LINE_INPUT | _win32.ENABLE_PROCESSED_INPUT
    )
    try:
        _win32.kernel32.SetConsoleMode(hin, raw_mode | _win32.ENABLE_VIRTUAL_TERMINAL_INPUT)
        _win32.kernel32.SetConsoleMode(
            hout, saved_out.value | _win32.ENABLE_VIRTUAL_TERMINAL_PROCESSING
        )
        yield True
    finally:
        _win32.kernel32.SetConsoleMode(hin, saved_in.value)
        _win32.kernel32.SetConsoleMode(hout, saved_out.value)


#: msvcrt.getwch() lead bytes for an extended (arrow/function) key.
_EXTENDED_LEADS = ("\x00", "\xe0")

#: Second byte after an extended lead -> the named token console.py's
#: apply_key should treat as a single keypress, not literal characters.
#: (Named rather than re-encoded as an ANSI CSI sequence, because
#: console.py's own ANSI decoding for the POSIX arrow-key case is itself
#: dropped, not translated -- see console.py's apply_key docstring update.)
_EXTENDED_KEYS: dict[str, str] = {
    "H": "<up>",
    "P": "<down>",
    "K": "<left>",
    "M": "<right>",
    "G": "<home>",
    "O": "<end>",
    "S": "<delete>",
    "R": "<insert>",
}


@contextlib.contextmanager
def key_reader(loop: Any, put: Callable[[str], None]) -> Iterator[None]:
    """Feed console keypresses to ``put`` from a daemon polling thread.

    ``loop.add_reader`` -- the POSIX mechanism -- is unavailable here twice
    over: ``ProactorEventLoop`` (asyncio's Windows default, confirmed in use)
    raises ``NotImplementedError`` for it outright, and the alternative
    ``SelectorEventLoop`` only ever accepted *sockets*, never a console
    handle, on any platform. A blocking ``msvcrt.getwch()`` in a thread would
    solve the loop-integration problem but not shutdown: it cannot be
    interrupted, so ``raw_console``'s mode restoration would race a thread
    still parked inside a blocking read. Polling ``kbhit()`` on a short
    sleep is the one option that is both cancellable and loop-agnostic; 5ms
    is far under human perception and keeps CPU use negligible.
    """
    stop = threading.Event()

    def _poll() -> None:
        while not stop.is_set():
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in _EXTENDED_LEADS:
                    if stop.is_set():
                        break
                    nxt = msvcrt.getwch()
                    token = _EXTENDED_KEYS.get(nxt)
                    if token is not None:
                        loop.call_soon_threadsafe(put, token)
                    continue
                loop.call_soon_threadsafe(put, ch)
            else:
                time.sleep(0.005)

    thread = threading.Thread(target=_poll, name="sleipnir-key-reader", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        # Not joined: a thread parked in kbhit()'s underlying wait can take
        # up to the poll interval to notice `stop`, and this is a daemon
        # thread, so process exit reclaims it either way.


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
