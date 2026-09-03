"""The one seam between Sleipnir and the operating system it runs on.

Every POSIX-only syscall and every Windows-only API call in the codebase goes
through a name exported here. No other module is allowed a bare
``sys.platform`` branch around process control, file locking, console raw
mode, or shell selection — if a new one is needed, it is added to this
package, not sprinkled at the call site. That is what keeps ``_posix.py`` a
provable no-op refactor of what the Linux path already did, and keeps the
Windows implementation reviewable as one thing instead of six partial ones.

The two backends do not always mean the same mechanism behind the same name.
``force_kill_tree`` is ``killpg(SIGKILL)`` on POSIX and ``taskkill /F /T`` on
Windows — different kernels, same observable contract: the whole descendant
tree is gone when the call returns. Callers depend on the contract, never the
mechanism.
"""

from __future__ import annotations

import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")

#: Platforms where the parent-death guard (``process_guard.py``) has a real
#: implementation. Other POSIX systems (macOS, *BSD) fall through to no
#: guard at all -- exactly the behaviour this port found already in place for
#: non-Linux POSIX, and deliberately left unchanged.
WRAPS_CHILDREN = IS_LINUX or IS_WINDOWS


class LockUnavailable(OSError):
    """Another process already holds this lock.

    One exception for both backends: ``fcntl.flock`` raises
    ``BlockingIOError`` on contention, ``msvcrt.locking`` raises
    ``PermissionError``. Callers (``runlog.py``) should never see the
    difference.
    """


class GuardedLaunch:
    """A child's argv, wrapped with whatever tree-kill guarantee this
    platform can offer, plus whatever OS handle that guarantee needs held
    open for the life of the child.

    ``argv`` is what actually gets spawned. ``close()`` must be called once
    the child has been reaped either way -- on POSIX it is a no-op; on
    Windows it releases the job object, and *that* release is itself part of
    the guarantee (see ``platform/_windows.py``), not just cleanup.
    """

    __slots__ = ("argv", "_close")

    def __init__(self, argv: list[str], close) -> None:
        self.argv = argv
        self._close = close

    def close(self) -> None:
        self._close()


def guard_script_path() -> Path:
    """Where ``process_guard.py`` lives, for both backends to wrap argv with."""
    return Path(__file__).resolve().parent.parent / "process_guard.py"


if IS_WINDOWS:  # pragma: win32 cover
    from sleipnir.platform import _windows as _impl
else:  # pragma: posix cover
    from sleipnir.platform import _posix as _impl

pid_is_alive = _impl.pid_is_alive
try_lock_exclusive = _impl.try_lock_exclusive
unlock = _impl.unlock
prepare_stdio_encoding = _impl.prepare_stdio_encoding
enable_ansi = _impl.enable_ansi
colour_is_supported = _impl.colour_is_supported
CHILD_SPAWN_KWARGS = _impl.CHILD_SPAWN_KWARGS
create_guarded_launch = _impl.create_guarded_launch
request_group_stop = _impl.request_group_stop
force_kill_tree = _impl.force_kill_tree
kill_pid_tree = _impl.kill_pid_tree
stop_pid_group = _impl.stop_pid_group
posix_shell = _impl.posix_shell
shell_argv = _impl.shell_argv
shell_kind = _impl.shell_kind
resolve_executable = _impl.resolve_executable
is_reparse_point = _impl.is_reparse_point
raw_console = _impl.raw_console
key_reader = _impl.key_reader
replace_atomic = _impl.replace_atomic

__all__ = [
    "CHILD_SPAWN_KWARGS",
    "IS_LINUX",
    "IS_WINDOWS",
    "WRAPS_CHILDREN",
    "GuardedLaunch",
    "LockUnavailable",
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
