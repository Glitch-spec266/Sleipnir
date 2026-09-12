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
import errno
import hashlib
import msvcrt
import os
import re
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
    # stderr is an output screen buffer too. The old fallback selected stdin
    # for every non-stdout stream and then tried to enable an *output* mode on
    # the input buffer, so colour capability checks on stderr always failed.
    which = _win32.STD_ERROR_HANDLE if stream is sys.stderr else _win32.STD_OUTPUT_HANDLE
    handle = _std_handle(which)
    if not handle or handle == _win32.INVALID_HANDLE_VALUE:
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
        raise OSError(ctypes.get_last_error(), "could not create provider job object")

    info = _win32.JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = _win32.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    configured = _win32.kernel32.SetInformationJobObject(
        handle,
        _win32.JobObjectExtendedLimitInformation,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )
    if not configured:
        error = ctypes.get_last_error()
        _win32.kernel32.CloseHandle(handle)
        raise OSError(error, "could not configure provider job object")

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


def _is_same_file(opened: os.stat_result, on_disk: os.stat_result) -> bool:
    """Whether a descriptor and a path name the same underlying file.

    Windows fills ``st_ino`` with the NTFS file index and ``st_dev`` with the
    volume serial, so the pair identifies a file the way the POSIX pair does.
    A zero index means the filesystem did not supply one, which is treated as
    "cannot prove they match" rather than as a match.
    """
    if opened.st_ino == 0 or on_disk.st_ino == 0:
        return False
    return (opened.st_dev, opened.st_ino) == (on_disk.st_dev, on_disk.st_ino)


def open_no_follow(path: Path, flags: int, mode: int = 0o600) -> int:
    """``open_no_follow`` for a platform whose Python has no ``O_NOFOLLOW``.

    Windows cannot ask the kernel to refuse a reparse point through
    ``os.open``, so the guarantee is rebuilt in two halves: refuse a path that
    is already a reparse point, then prove after opening that the descriptor
    and the path still name the same file.  A junction swapped in during the
    open changes the identity, and the mismatch is what catches it -- the
    check alone would be a plain time-of-check/time-of-use hole.

    ``O_BINARY`` is forced so callers get the byte stream POSIX gives them and
    newline translation stays with the text wrapper above, not the descriptor.
    """
    path = Path(path)
    if is_reparse_point(path):
        raise OSError(errno.ELOOP, "refusing to follow a reparse point", str(path))
    descriptor = os.open(path, flags | os.O_BINARY, mode)
    try:
        opened = os.fstat(descriptor)
        on_disk = os.lstat(path)
    except OSError:
        os.close(descriptor)
        raise
    if is_reparse_point(path) or not _is_same_file(opened, on_disk):
        os.close(descriptor)
        raise OSError(errno.ELOOP, "path was redirected during open", str(path))
    return descriptor


def open_in_directory(directory: Path, filename: str, flags: int, mode: int = 0o600) -> int:
    """``open_in_directory`` without ``dir_fd``, which Windows does not support.

    ``os.supports_dir_fd`` is empty here, so the parent is validated by path
    instead of held open as a descriptor.  The final component still gets the
    full ``open_no_follow`` treatment, which is the component an agent writing
    inside its own workspace can actually control.
    """
    directory = Path(directory)
    if is_reparse_point(directory) or not directory.is_dir():
        raise OSError(errno.ENOTDIR, "unsafe directory", str(directory))
    return open_no_follow(directory / filename, flags, mode)


# ---------------------------------------------------------------------------
# Local IPC -- capabilities/agent.py's credential cache
# ---------------------------------------------------------------------------
#
# The POSIX agent leans on two properties of a Unix socket in a 0700
# directory: only this account can open it, and the server learns the peer's
# pid from the kernel rather than from the client. CPython exposes no AF_UNIX
# here (Windows has supported it since 10/1803, the interpreter has not), so a
# named pipe supplies both instead: a DACL naming exactly this user's SID, and
# ``GetNamedPipeClientProcessId``. ``PIPE_REJECT_REMOTE_CLIENTS`` keeps the
# pipe off the network, which a Unix socket never was in the first place.
#
# The endpoint is still addressed by the ``Path`` the agent passes around,
# hashed into a pipe name, so nothing above this seam needs to know whether it
# is speaking to a socket or to a pipe.


def _pipe_name(path: Path) -> str:
    digest = hashlib.sha256(str(path).casefold().encode("utf-8")).hexdigest()
    return r"\\.\pipe\sleipnir-agent-" + digest[:32]


def _token_user_sid(token: ctypes.wintypes.HANDLE) -> str:
    size = ctypes.wintypes.DWORD(0)
    _win32.advapi32.GetTokenInformation(token, _win32.TokenUser, None, 0, ctypes.byref(size))
    buffer = ctypes.create_string_buffer(size.value)
    if not _win32.advapi32.GetTokenInformation(
        token, _win32.TokenUser, buffer, size, ctypes.byref(size)
    ):
        raise OSError(ctypes.get_last_error(), "could not read the token user")
    user = ctypes.cast(buffer, ctypes.POINTER(_win32.TOKEN_USER)).contents
    text = ctypes.wintypes.LPWSTR()
    if not _win32.advapi32.ConvertSidToStringSidW(user.User.Sid, ctypes.byref(text)):
        raise OSError(ctypes.get_last_error(), "could not format the token SID")
    try:
        return str(text.value)
    finally:
        _win32.kernel32.LocalFree(text)


def current_user_id() -> str:
    """This process's token SID -- the Windows answer to ``os.getuid()``."""
    token = ctypes.wintypes.HANDLE()
    if not _win32.advapi32.OpenProcessToken(
        _win32.kernel32.GetCurrentProcess(), _win32.TOKEN_QUERY, ctypes.byref(token)
    ):
        raise OSError(ctypes.get_last_error(), "could not open this process's token")
    try:
        return _token_user_sid(token)
    finally:
        _win32.kernel32.CloseHandle(token)


def _process_user_sid(pid: int) -> str:
    handle = _win32.kernel32.OpenProcess(
        _win32.PROCESS_QUERY_LIMITED_INFORMATION, False, pid
    )
    if not handle:
        raise OSError(ctypes.get_last_error(), f"could not open peer process {pid}")
    try:
        token = ctypes.wintypes.HANDLE()
        if not _win32.advapi32.OpenProcessToken(handle, _win32.TOKEN_QUERY, ctypes.byref(token)):
            raise OSError(ctypes.get_last_error(), f"could not open peer token for {pid}")
        try:
            return _token_user_sid(token)
        finally:
            _win32.kernel32.CloseHandle(token)
    finally:
        _win32.kernel32.CloseHandle(handle)


def agent_endpoint_is_filesystem_path() -> bool:
    """A pipe has no directory and no mode, so the path checks do not apply."""
    return False


class _PipeConnection:
    """The subset of a socket that ``capabilities/agent.py`` actually uses."""

    def __init__(self, handle: int, *, server: bool, timeout: float = 5.0) -> None:
        self._handle = handle
        self._server = server
        self._timeout = timeout

    def settimeout(self, timeout: float | None) -> None:
        self._timeout = 3600.0 if timeout is None else timeout

    def _finish(self, overlapped: Any, event: Any) -> int:
        """Wait out one overlapped transfer, then give up rather than hang."""
        millis = int(max(self._timeout, 0.0) * 1000) or 1
        if _win32.kernel32.WaitForSingleObject(event, millis) != _win32.WAIT_OBJECT_0:
            _win32.kernel32.CancelIo(self._handle)
            raise TimeoutError("named pipe operation timed out")
        moved = ctypes.wintypes.DWORD(0)
        if not _win32.kernel32.GetOverlappedResult(
            self._handle, ctypes.byref(overlapped), ctypes.byref(moved), False
        ):
            error = ctypes.get_last_error()
            if error == _win32.ERROR_BROKEN_PIPE:
                return 0
            raise OSError(error, "named pipe transfer failed")
        return moved.value

    def recv(self, size: int) -> bytes:
        buffer = ctypes.create_string_buffer(size)
        overlapped = _win32.OVERLAPPED()
        event = _win32.kernel32.CreateEventW(None, True, False, None)
        overlapped.hEvent = event
        try:
            moved = ctypes.wintypes.DWORD(0)
            ok = _win32.kernel32.ReadFile(
                self._handle, buffer, size, ctypes.byref(moved), ctypes.byref(overlapped)
            )
            if ok:
                count = moved.value
            else:
                error = ctypes.get_last_error()
                if error == _win32.ERROR_BROKEN_PIPE:
                    return b""
                if error != _win32.ERROR_IO_PENDING:
                    raise OSError(error, "named pipe read failed")
                count = self._finish(overlapped, event)
            return buffer.raw[:count]
        finally:
            _win32.kernel32.CloseHandle(event)

    def sendall(self, payload: bytes) -> None:
        overlapped = _win32.OVERLAPPED()
        event = _win32.kernel32.CreateEventW(None, True, False, None)
        overlapped.hEvent = event
        try:
            moved = ctypes.wintypes.DWORD(0)
            ok = _win32.kernel32.WriteFile(
                self._handle, payload, len(payload), ctypes.byref(moved), ctypes.byref(overlapped)
            )
            if not ok:
                error = ctypes.get_last_error()
                if error != _win32.ERROR_IO_PENDING:
                    raise OSError(error, "named pipe write failed")
                self._finish(overlapped, event)
        finally:
            _win32.kernel32.CloseHandle(event)

    def peer_pid(self) -> int:
        pid = ctypes.wintypes.ULONG(0)
        if not _win32.kernel32.GetNamedPipeClientProcessId(self._handle, ctypes.byref(pid)):
            raise OSError(ctypes.get_last_error(), "could not read the pipe client pid")
        return int(pid.value)

    def close(self) -> None:
        if self._handle:
            if self._server:
                # A socket's unread data survives close; a pipe's does not.
                # Disconnecting before the client has drained the reply throws
                # the reply away, which surfaced as "the agent closed the
                # connection" on the larger responses (a full LIST) only.
                _win32.kernel32.FlushFileBuffers(self._handle)
                _win32.kernel32.DisconnectNamedPipe(self._handle)
            _win32.kernel32.CloseHandle(self._handle)
            self._handle = 0

    def __enter__(self) -> _PipeConnection:
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()


class _PipeListener:
    """``accept()`` with a timeout, so the agent still runs its expiry sweep."""

    def __init__(self, path: Path, timeout: float | None) -> None:
        self.name = _pipe_name(path)
        self._timeout = timeout
        self._attributes = self._security_attributes()
        self._claim = None

    def _security_attributes(self) -> Any:
        # "D:P(A;;GA;;;<sid>)" -- a protected DACL with exactly one entry:
        # full control for this account, inheritance blocked so nothing
        # widens it later. This is the ACL equivalent of the 0700 directory
        # the POSIX socket sits in.
        sddl = f"D:P(A;;GA;;;{current_user_id()})"
        descriptor = ctypes.c_void_p()
        if not _win32.advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, _win32.SDDL_REVISION_1, ctypes.byref(descriptor), None
        ):
            raise OSError(ctypes.get_last_error(), "could not build the pipe ACL")
        attributes = _win32.SECURITY_ATTRIBUTES()
        attributes.nLength = ctypes.sizeof(_win32.SECURITY_ATTRIBUTES)
        attributes.lpSecurityDescriptor = descriptor
        attributes.bInheritHandle = False
        return attributes

    def _instance(self, *, first: bool) -> int:
        flags = _win32.PIPE_ACCESS_DUPLEX | _win32.FILE_FLAG_OVERLAPPED
        if first:
            flags |= _win32.FILE_FLAG_FIRST_PIPE_INSTANCE
        handle = _win32.kernel32.CreateNamedPipeW(
            self.name,
            flags,
            _win32.PIPE_TYPE_BYTE
            | _win32.PIPE_READMODE_BYTE
            | _win32.PIPE_WAIT
            | _win32.PIPE_REJECT_REMOTE_CLIENTS,
            _win32.PIPE_UNLIMITED_INSTANCES,
            65536,
            65536,
            0,
            ctypes.byref(self._attributes),
        )
        if handle == _win32.INVALID_HANDLE_VALUE:
            raise OSError(ctypes.get_last_error(), f"could not create pipe {self.name}")
        return handle

    def accept(self) -> tuple[_PipeConnection, None]:
        # The instance created to claim the name is a real, connectable
        # instance. Leaving it idle lets the first client attach to a box
        # nobody ever reads from and time out -- which looked exactly like a
        # dead agent. Serve on it first, then make fresh instances.
        if self._claim is not None:
            handle, self._claim = self._claim, None
        else:
            handle = self._instance(first=False)
        overlapped = _win32.OVERLAPPED()
        event = _win32.kernel32.CreateEventW(None, True, False, None)
        overlapped.hEvent = event
        try:
            if not _win32.kernel32.ConnectNamedPipe(handle, ctypes.byref(overlapped)):
                error = ctypes.get_last_error()
                if error == _win32.ERROR_IO_PENDING:
                    millis = int((self._timeout if self._timeout else 3600.0) * 1000)
                    if _win32.kernel32.WaitForSingleObject(event, millis) != _win32.WAIT_OBJECT_0:
                        _win32.kernel32.CancelIo(handle)
                        _win32.kernel32.CloseHandle(handle)
                        raise TimeoutError("no client connected")
                elif error != _win32.ERROR_PIPE_CONNECTED:
                    _win32.kernel32.CloseHandle(handle)
                    raise OSError(error, "could not wait for a pipe client")
            return _PipeConnection(handle, server=True), None
        finally:
            _win32.kernel32.CloseHandle(event)

    def settimeout(self, timeout: float | None) -> None:
        self._timeout = timeout

    def close(self) -> None:
        if self._claim:
            _win32.kernel32.CloseHandle(self._claim)
            self._claim = None
        if self._attributes.lpSecurityDescriptor:
            _win32.kernel32.LocalFree(self._attributes.lpSecurityDescriptor)
            self._attributes.lpSecurityDescriptor = None


def agent_listen(path: Path, *, backlog: int = 16, timeout: float | None = None) -> _PipeListener:
    """Claim the pipe name, refusing to start beside a live agent.

    ``FILE_FLAG_FIRST_PIPE_INSTANCE`` fails when another process already owns
    the name, which is this platform's version of the POSIX "a Sleipnir agent
    is already listening" check -- and unlike a stale socket file, a pipe name
    disappears with the process that held it, so there is nothing to unlink.
    """
    listener = _PipeListener(path, timeout)
    try:
        listener._claim = listener._instance(first=True)
    except OSError:
        listener.close()
        raise
    return listener


def agent_connect(path: Path, timeout: float) -> _PipeConnection:
    name = _pipe_name(path)
    deadline = time.monotonic() + timeout
    while True:
        handle = _win32.kernel32.CreateFileW(
            name,
            _win32.GENERIC_READ | _win32.GENERIC_WRITE,
            0,
            None,
            _win32.OPEN_EXISTING,
            _win32.FILE_FLAG_OVERLAPPED,
            None,
        )
        if handle != _win32.INVALID_HANDLE_VALUE:
            return _PipeConnection(handle, server=False, timeout=timeout)
        error = ctypes.get_last_error()
        if error not in (_win32.ERROR_PIPE_BUSY, _win32.ERROR_FILE_NOT_FOUND):
            raise OSError(error, f"no Sleipnir agent at {name}")
        if time.monotonic() >= deadline:
            raise OSError(error, f"no Sleipnir agent at {name}")
        if error == _win32.ERROR_PIPE_BUSY:
            # Every instance is serving someone else; wait for one to free up.
            _win32.kernel32.WaitNamedPipeW(name, 100)
        else:
            # A live agent creates its next instance between connections, so
            # "not found" is normally that gap rather than a missing agent.
            # A genuinely absent agent still fails, just at the deadline.
            time.sleep(0.02)


def agent_peer_credentials(conn: _PipeConnection) -> tuple[int | None, str]:
    """Peer pid from the kernel, then that process's token SID."""
    pid = conn.peer_pid()
    return pid, _process_user_sid(pid)


def lock_memory(address: int, length: int) -> None:
    """``VirtualLock`` is the Windows ``mlock``: keeps the pages resident.

    ``ctypes.CDLL(None)`` -- the POSIX way to reach libc -- raises TypeError
    here, which is what made the credential agent fail with a bare
    ``TypeError`` rather than anything that named the real problem.
    """
    if _win32.kernel32.VirtualLock(ctypes.c_void_p(address), ctypes.c_size_t(length)):
        return
    error = ctypes.get_last_error()
    if error != _win32.ERROR_WORKING_SET_QUOTA:
        raise OSError(error, "could not lock credential memory")
    # Windows caps locked memory at the process's *minimum working set*, which
    # defaults to a couple of hundred KiB -- enough for the first few secrets
    # and not for a full cache. POSIX has no equivalent ceiling, so the cap is
    # raised here rather than letting the agent refuse its 60th entry.
    minimum, maximum = ctypes.c_size_t(0), ctypes.c_size_t(0)
    process = _win32.kernel32.GetCurrentProcess()
    if not _win32.kernel32.GetProcessWorkingSetSize(
        process, ctypes.byref(minimum), ctypes.byref(maximum)
    ):
        raise OSError(ctypes.get_last_error(), "could not read the working-set limit")
    headroom = max(length * 4, 1 << 20)
    if not _win32.kernel32.SetProcessWorkingSetSize(
        process, minimum.value + headroom, max(maximum.value, minimum.value + headroom * 2)
    ):
        raise OSError(ctypes.get_last_error(), "could not raise the working-set limit")
    if not _win32.kernel32.VirtualLock(ctypes.c_void_p(address), ctypes.c_size_t(length)):
        raise OSError(ctypes.get_last_error(), "could not lock credential memory")


def unlock_memory(address: int, length: int) -> None:
    _win32.kernel32.VirtualUnlock(ctypes.c_void_p(address), ctypes.c_size_t(length))


#: Accounts whose access to a private file is not a leak: the owner, plus the
#: two principals that can take ownership anyway. Excluding them would buy no
#: secrecy and would break backup and repair tooling.
_HARMLESS_TRUSTEES = frozenset({"SY", "BA", "S-1-5-18", "S-1-5-32-544"})


def make_path_private(path: Path) -> None:
    """Replace the file's DACL with a protected, owner-only one.

    ``os.chmod(path, 0o600)`` is not a permission change on Windows: CPython
    maps it onto the read-only attribute, and ``st_mode`` keeps reporting
    group/other bits that were never real. The access check that does exist
    here is the ACL, so that is what gets set.
    """
    sddl = f"D:P(A;;FA;;;{current_user_id()})"
    descriptor = ctypes.c_void_p()
    if not _win32.advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        sddl, _win32.SDDL_REVISION_1, ctypes.byref(descriptor), None
    ):
        raise OSError(ctypes.get_last_error(), "could not build the file ACL")
    try:
        if not _win32.advapi32.SetFileSecurityW(
            str(path), _win32.DACL_SECURITY_INFORMATION, descriptor
        ):
            raise OSError(ctypes.get_last_error(), f"could not set the ACL on {path}")
    finally:
        _win32.kernel32.LocalFree(descriptor)


def path_is_private(path: Path) -> bool:
    """Whether the DACL grants access to nobody but this account.

    Reads the descriptor back rather than trusting what was written: a file
    restored from a backup, or created before this code ran, can carry an
    inherited ACE that hands it to every local account.
    """
    size = ctypes.wintypes.DWORD(0)
    _win32.advapi32.GetFileSecurityW(
        str(path), _win32.DACL_SECURITY_INFORMATION, None, 0, ctypes.byref(size)
    )
    buffer = ctypes.create_string_buffer(size.value)
    if not _win32.advapi32.GetFileSecurityW(
        str(path), _win32.DACL_SECURITY_INFORMATION, buffer, size, ctypes.byref(size)
    ):
        raise OSError(ctypes.get_last_error(), f"could not read the ACL on {path}")
    text = ctypes.wintypes.LPWSTR()
    if not _win32.advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW(
        buffer, _win32.SDDL_REVISION_1, _win32.DACL_SECURITY_INFORMATION,
        ctypes.byref(text), None,
    ):
        raise OSError(ctypes.get_last_error(), f"could not read the ACL on {path}")
    try:
        sddl = str(text.value)
    finally:
        _win32.kernel32.LocalFree(text)

    me = current_user_id()
    for ace in re.findall(r"\(([^)]*)\)", sddl):
        parts = ace.split(";")
        if len(parts) < 6 or not parts[0].startswith("A"):
            continue  # a deny ACE only ever narrows access
        trustee = parts[5]
        if trustee != me and trustee not in _HARMLESS_TRUSTEES:
            return False
    return True


def process_belongs_to_current_user(pid: int) -> bool:
    """Whether ``pid`` is a live process owned by this account.

    The POSIX version reads ``/proc/<pid>``'s owner. There is no ``/proc``
    here, so the same question is asked of the process token -- and asking it
    matters: the Linux code silently answered "no" on Windows, which made the
    console treat every pending secret request as stale and delete it.
    """
    if not pid_is_alive(pid):
        return False
    try:
        return _process_user_sid(pid) == current_user_id()
    except OSError:
        # A process this account cannot open is not this account's process.
        return False


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
    if not _win32.kernel32.GetConsoleMode(hin, ctypes.byref(saved_in)):
        yield False
        return
    if not _win32.kernel32.GetConsoleMode(hout, ctypes.byref(saved_out)):
        yield False
        return
    raw_mode = saved_in.value & ~(
        _win32.ENABLE_ECHO_INPUT | _win32.ENABLE_LINE_INPUT | _win32.ENABLE_PROCESSED_INPUT
    )
    if not _win32.kernel32.SetConsoleMode(
        hin, raw_mode | _win32.ENABLE_VIRTUAL_TERMINAL_INPUT
    ):
        yield False
        return
    if not _win32.kernel32.SetConsoleMode(
        hout, saved_out.value | _win32.ENABLE_VIRTUAL_TERMINAL_PROCESSING
    ):
        _win32.kernel32.SetConsoleMode(hin, saved_in.value)
        yield False
        return
    try:
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
    "lock_memory",
    "make_path_private",
    "path_is_private",
    "process_belongs_to_current_user",
    "unlock_memory",
    "open_in_directory",
    "open_no_follow",
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
