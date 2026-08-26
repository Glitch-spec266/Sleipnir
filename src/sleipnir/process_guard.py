"""Run a provider CLI with a Linux parent-death signal installed.

An executor can be killed with SIGKILL, so its asyncio cancellation handler is
not guaranteed to run. On Linux, ``PR_SET_PDEATHSIG`` asks the kernel to send
SIGTERM to the provider CLI leader when Sleipnir dies. The process-group kill
in :mod:`sleipnir.process` remains the stronger cleanup path for ordinary
cancellation and timeouts.
"""

from __future__ import annotations

import ctypes
import os
import signal
import time
# Exact argv execution is this module's sole purpose.
import subprocess  # nosec B404
import sys

_PR_SET_PDEATHSIG = 1

#: How long a provider gets to exit on SIGTERM before the group is SIGKILLed.
#: After a hard parent kill no ``ProcessRunner`` survives to escalate, so this
#: is the only remaining backstop against a CLI that traps SIGTERM and keeps
#: spending.
_GRACE_S = 5.0


def _install_parent_death_signal() -> None:
    """Install SIGTERM-on-parent-death, closing the setup race explicitly."""
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


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["--"]:
        args = args[1:]
    if not args:
        print("process guard requires a command", file=sys.stderr)
        return 2
    if sys.platform.startswith("linux"):
        try:
            _install_parent_death_signal()
        except OSError as exc:
            print(f"process guard could not install parent-death signal: {exc}", file=sys.stderr)
            return 126
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


if __name__ == "__main__":
    raise SystemExit(main())
