"""Run a provider CLI with a parent-death guard installed.

An executor can be killed with SIGKILL (or ``TerminateProcess`` on Windows),
so its asyncio cancellation handler is not guaranteed to run. This wrapper
gives Sleipnir a way to say "when I die, so do you" that survives that.

The two platforms rebuild the guarantee from different primitives, because
neither POSIX signals nor Windows job objects exist on the other side:

* **Linux** — ``PR_SET_PDEATHSIG`` asks the kernel to send SIGTERM to this
  process when its parent dies, and this process forwards that to its own
  process group (the provider CLI and anything it spawned).
* **Windows** — this process joins a job object the launcher created *before*
  spawning anything (see ``platform.create_guarded_launch``), so every
  descendant inherits membership automatically. A background thread waits on
  a handle to the launcher's pid; when that wait returns, the job is
  terminated directly, killing the whole tree unconditionally — no signal to
  trap, no grace period to outlast.

Neither platform's Sleipnir process is guaranteed to survive to run a
``finally``, so both guards act independently of it: :mod:`sleipnir.process`
remains the stronger cleanup path for ordinary cancellation and timeouts.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess  # nosec B404 - exact argv execution is this module's sole purpose
import sys
import threading
import time

if sys.platform == "win32":
    import ctypes
    import ctypes.wintypes as _wintypes

_GRACE_S = 5.0


# ---------------------------------------------------------------------------
# Linux
# ---------------------------------------------------------------------------

_PR_SET_PDEATHSIG = 1


def _install_parent_death_signal_linux() -> None:
    """Install SIGTERM-on-parent-death, closing the setup race explicitly."""
    import ctypes

    original_parent = os.getppid()
    libc = ctypes.CDLL(None, use_errno=True)
    prctl = libc.prctl
    prctl.argtypes = [
        ctypes.c_int,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
    ]
    prctl.restype = ctypes.c_int
    if prctl(_PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    # The parent could die between getppid() and prctl(). In that case the
    # kernel had no relationship change left to notify us about.
    if os.getppid() != original_parent:
        os.kill(os.getpid(), signal.SIGTERM)


def _run_linux(args: list[str]) -> int:
    _install_parent_death_signal_linux()
    child: subprocess.Popen[bytes] | None = None

    def terminate_group(signum: int, _frame: object) -> None:
        """Forward parent death/cancellation to every provider descendant."""
        # Ignore our own group broadcast while provider descendants receive it.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        try:
            # Broadcast even with no child recorded yet: Popen may already have
            # forked into this group between spawn and the assignment below.
            os.killpg(os.getpgrp(), signal.SIGTERM)
        except ProcessLookupError:
            pass
        if child is None:
            os._exit(128 + signum)
        # Popen.wait may hold an internal lock when the signal arrives, so no
        # Popen method is signal-safe here; waitpid is.
        pid = child.pid
        deadline = time.monotonic() + _GRACE_S
        while time.monotonic() < deadline:
            try:
                if os.waitpid(pid, os.WNOHANG)[0] == pid:
                    os._exit(128 + signum)
            except (ChildProcessError, OSError):
                os._exit(128 + signum)
            time.sleep(0.05)
        # A provider that ignored SIGTERM is still holding quota open, and
        # nothing upstream is left alive to escalate for us.
        try:
            os.killpg(os.getpgrp(), signal.SIGKILL)
        except ProcessLookupError:
            pass
        os._exit(128 + signum)

    signal.signal(signal.SIGTERM, terminate_group)
    # The validated adapter invocation is passed as an argv vector; no shell,
    # interpolation, or command-string parsing occurs here.
    child = subprocess.Popen(args, shell=False)  # nosec B603
    return_code = child.wait()
    return return_code if return_code >= 0 else 128 - return_code


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------
#
# Deliberately self-contained, exactly like the Linux path above: this file
# runs as a standalone script (`python process_guard.py ...`), not as part
# of an installed `sleipnir` package, so it cannot import from
# `sleipnir.platform` -- reproduced live as `ModuleNotFoundError: No module
# named 'sleipnir'` from the spawned guard before this was inlined. Every
# Win32 binding it needs is declared right here instead.

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True) if sys.platform == "win32" else None

_JOB_OBJECT_ALL_ACCESS = 0x1F001F
_SYNCHRONIZE = 0x00100000
_INFINITE = 0xFFFFFFFF
_CTRL_BREAK_EVENT = 1

if _kernel32 is not None:
    _kernel32.OpenJobObjectW.argtypes = [_wintypes.DWORD, _wintypes.BOOL, _wintypes.LPCWSTR]
    _kernel32.OpenJobObjectW.restype = _wintypes.HANDLE
    _kernel32.AssignProcessToJobObject.argtypes = [_wintypes.HANDLE, _wintypes.HANDLE]
    _kernel32.AssignProcessToJobObject.restype = _wintypes.BOOL
    _kernel32.TerminateJobObject.argtypes = [_wintypes.HANDLE, _wintypes.UINT]
    _kernel32.TerminateJobObject.restype = _wintypes.BOOL
    _kernel32.GetCurrentProcess.restype = _wintypes.HANDLE
    _kernel32.OpenProcess.argtypes = [_wintypes.DWORD, _wintypes.BOOL, _wintypes.DWORD]
    _kernel32.OpenProcess.restype = _wintypes.HANDLE
    _kernel32.WaitForSingleObject.argtypes = [_wintypes.HANDLE, _wintypes.DWORD]
    _kernel32.WaitForSingleObject.restype = _wintypes.DWORD
    _kernel32.CloseHandle.argtypes = [_wintypes.HANDLE]
    _kernel32.CloseHandle.restype = _wintypes.BOOL
    _HANDLER_ROUTINE = ctypes.WINFUNCTYPE(_wintypes.BOOL, _wintypes.DWORD)
    _kernel32.SetConsoleCtrlHandler.argtypes = [_HANDLER_ROUTINE, _wintypes.BOOL]
    _kernel32.SetConsoleCtrlHandler.restype = _wintypes.BOOL


def _run_windows(args: list[str], job_name: str | None) -> int:
    job_handle = None
    if job_name:
        job_handle = _kernel32.OpenJobObjectW(_JOB_OBJECT_ALL_ACCESS, False, job_name)
        if job_handle:
            _kernel32.AssignProcessToJobObject(job_handle, _kernel32.GetCurrentProcess())
        # A failed open/assign means no isolation guarantee for this dispatch
        # rather than a refusal to run it -- the same posture the Linux path
        # takes when prctl fails for a reason other than the race it checks.

    handler_ref = None  # keeps the ctypes trampoline alive; see below
    if job_handle:
        ppid = os.getppid()

        def _watch_parent() -> None:
            handle = _kernel32.OpenProcess(_SYNCHRONIZE, False, ppid)
            if not handle:
                return  # parent already gone
            _kernel32.WaitForSingleObject(handle, _INFINITE)
            _kernel32.CloseHandle(handle)
            # No grace period, unlike the Linux path's SIGTERM-then-SIGKILL:
            # there is no Windows signal a provider CLI could trap here to
            # earn one, and a job kill reaches the whole tree unconditionally
            # regardless of what any member does.
            _kernel32.TerminateJobObject(job_handle, 1)

        threading.Thread(target=_watch_parent, name="sleipnir-guard-watch", daemon=True).start()

        @_HANDLER_ROUTINE
        def _on_ctrl(event: int) -> bool:
            if event != _CTRL_BREAK_EVENT:
                return False
            _kernel32.TerminateJobObject(job_handle, 1)
            return True

        # ctypes does not keep a reference to a callback once it is passed
        # to a C function; without this the handler could be garbage
        # collected while SetConsoleCtrlHandler's table still points at it.
        handler_ref = _on_ctrl
        _kernel32.SetConsoleCtrlHandler(handler_ref, True)

    # The validated adapter invocation is passed as an argv vector; no shell,
    # interpolation, or command-string parsing occurs here.
    child = subprocess.Popen(args, shell=False)  # nosec B603
    return child.wait()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    job_name: str | None = None
    if args[:1] == ["--job"]:
        if len(args) < 2:
            print("process guard: --job requires a value", file=sys.stderr)
            return 2
        job_name = args[1]
        args = args[2:]
    if args[:1] == ["--"]:
        args = args[1:]
    if not args:
        print("process guard requires a command", file=sys.stderr)
        return 2

    if sys.platform.startswith("linux"):
        try:
            return _run_linux(args)
        except OSError as exc:
            print(f"process guard could not install parent-death signal: {exc}", file=sys.stderr)
            return 126
    if sys.platform == "win32":
        return _run_windows(args, job_name)

    # No guard available on this platform (e.g. macOS): run the command
    # plainly. WRAPS_CHILDREN in platform/__init__.py keeps this branch
    # unreachable from process.py, but the guard remains directly runnable.
    with contextlib.suppress(Exception):
        return subprocess.run(args, shell=False).returncode  # nosec B603
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
