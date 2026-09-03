"""Async subprocess execution with timeout, streaming capture, and tree kill.

Every adapter that shells out goes through :class:`ProcessRunner`. The spawn
call itself is the injection seam (``spawn=``), so tests exercise the *real*
streaming, timeout and kill logic against a fake process rather than replacing
the runner wholesale — mocking one layer up would leave exactly the code most
likely to deadlock untested.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from sleipnir import platform

#: Bytes of stderr retained in memory for the result record. The full stream
#: always goes to disk; this is the part that reaches a human without opening
#: a file.
STDERR_TAIL_BYTES = 8_192

_READ_CHUNK = 65_536


class SpawnedProcess(Protocol):
    """The subset of ``asyncio.subprocess.Process`` this module relies on."""

    stdin: Any
    stdout: Any
    stderr: Any
    pid: int
    returncode: int | None

    async def wait(self) -> int: ...


Spawner = Callable[..., Awaitable[SpawnedProcess]]


@dataclass(slots=True)
class ProcessResult:
    exit_code: int | None
    timed_out: bool = False
    cancelled: bool = False
    duration_s: float = 0.0
    stdout_bytes: int = 0
    stderr_bytes: int = 0
    stderr_tail: str = ""
    signalled: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out and not self.cancelled


async def _default_spawn(*argv: str, **kwargs: Any) -> SpawnedProcess:
    return await asyncio.create_subprocess_exec(*argv, **kwargs)  # type: ignore[return-value]


async def _pump(reader: Any, path: Path, *, tail_bytes: int = 0) -> tuple[int, bytes]:
    """Stream ``reader`` to ``path``, keeping the last ``tail_bytes`` in memory.

    Pumps run concurrently with the process wait. Draining only after exit
    would deadlock the moment a subagent writes more than one pipe buffer of
    output, which for a coding agent is immediately.
    """
    total = 0
    tail = bytearray()
    with path.open("wb") as handle:
        while True:
            chunk = await reader.read(_READ_CHUNK)
            if not chunk:
                break
            handle.write(chunk)
            total += len(chunk)
            if tail_bytes:
                tail.extend(chunk)
                if len(tail) > tail_bytes:
                    del tail[: len(tail) - tail_bytes]
    return total, bytes(tail)


class ProcessRunner:
    """Runs one child process to completion, a timeout, or a cancellation."""

    def __init__(self, spawn: Spawner | None = None) -> None:
        self._spawn: Spawner = spawn or _default_spawn
        # Test/injected spawners receive the adapter argv. Real children get a
        # kernel parent-death guard before the provider CLI execs.
        self._guard_parent_death = spawn is None

    async def run(
        self,
        argv: Sequence[str],
        *,
        stdout_path: Path,
        stderr_path: Path,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        stdin_data: str | None = None,
        timeout_s: float = 900.0,
        grace_s: float = 5.0,
    ) -> ProcessResult:
        started = time.monotonic()
        stdout_path.parent.mkdir(parents=True, exist_ok=True)

        # Test/injected spawners get the adapter argv unwrapped and no tree-
        # kill guarantee beyond the group kwargs below; real children get
        # whatever this platform can offer against "Sleipnir itself is
        # hard-killed" (PR_SET_PDEATHSIG on Linux, a job object on Windows;
        # see platform.create_guarded_launch and process_guard.py).
        if self._guard_parent_death and platform.WRAPS_CHILDREN:
            guard = platform.create_guarded_launch(list(argv))
        else:
            guard = platform.GuardedLaunch(list(argv), close=lambda: None)

        try:
            proc = await self._spawn(
                *guard.argv,
                cwd=str(cwd) if cwd else None,
                env=dict(env) if env is not None else None,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                # Own process group, so a timeout kills the CLI's children
                # too. Provider CLIs spawn node/python subprocesses that
                # outlive a bare stop-the-parent and go on burning tokens.
                **platform.CHILD_SPAWN_KWARGS,
            )

            result = ProcessResult(exit_code=None)
            pumps = [
                asyncio.create_task(_pump(proc.stdout, stdout_path)),
                asyncio.create_task(
                    _pump(proc.stderr, stderr_path, tail_bytes=STDERR_TAIL_BYTES)
                ),
            ]

            try:
                await self._feed_stdin(proc, stdin_data)
                try:
                    async with asyncio.timeout(timeout_s):
                        result.exit_code = await proc.wait()
                        await asyncio.gather(*pumps)
                except TimeoutError:
                    result.timed_out = True
                    await self._terminate(proc, grace_s, result)
                    await self._drain(pumps)
            except asyncio.CancelledError:
                result.cancelled = True
                await self._terminate(proc, grace_s, result)
                await self._drain(pumps)
                self._finalize(result, pumps, started)
                raise
            finally:
                for pump in pumps:
                    pump.cancel()

            self._finalize(result, pumps, started)
            return result
        finally:
            guard.close()

    @staticmethod
    async def _feed_stdin(proc: SpawnedProcess, data: str | None) -> None:
        if proc.stdin is None:
            return
        try:
            if data:
                proc.stdin.write(data.encode())
                await proc.stdin.drain()
            proc.stdin.close()
        except (BrokenPipeError, ConnectionResetError):
            # The child exited before reading its prompt. Its exit code and
            # stderr explain why; masking that with a pipe error would not.
            pass

    async def _terminate(
        self, proc: SpawnedProcess, grace_s: float, result: ProcessResult
    ) -> None:
        """Ask the group to stop, allow a grace period, then force it.

        Shielded because this runs inside cancellation handling, where an
        unshielded await re-raises immediately and would leave the child alive.
        """
        if proc.returncode is not None:
            return
        result.signalled.append(platform.request_group_stop(proc))
        with contextlib.suppress(TimeoutError, asyncio.CancelledError, ProcessLookupError):
            await asyncio.shield(asyncio.wait_for(proc.wait(), grace_s))
            return
        result.signalled.append(platform.force_kill_tree(proc))

    @staticmethod
    async def _drain(pumps: list[asyncio.Task[Any]]) -> None:
        """Give the pumps a moment to flush what the child already wrote."""
        with contextlib.suppress(TimeoutError, asyncio.CancelledError):
            await asyncio.shield(asyncio.wait_for(asyncio.gather(*pumps, return_exceptions=True), 2.0))

    @staticmethod
    def _finalize(
        result: ProcessResult, pumps: list[asyncio.Task[Any]], started: float
    ) -> None:
        result.duration_s = time.monotonic() - started
        for index, pump in enumerate(pumps):
            if not pump.done() or pump.cancelled():
                continue
            if pump.exception() is not None:
                continue
            total, tail = pump.result()
            if index == 0:
                result.stdout_bytes = total
            else:
                result.stderr_bytes = total
                result.stderr_tail = tail.decode("utf-8", errors="replace")


__all__ = [
    "STDERR_TAIL_BYTES",
    "ProcessResult",
    "ProcessRunner",
    "SpawnedProcess",
    "Spawner",
]
