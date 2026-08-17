"""Test doubles.

The fake lives at the *spawn* boundary rather than replacing ProcessRunner, so
tests exercise the real streaming, timeout, signalling and drain logic. That
code is the most likely to deadlock and the least likely to be noticed if it
does, which makes it exactly the code a wholesale mock must not skip.
"""

from __future__ import annotations

import asyncio
from typing import Any

#: Fake pids must never name a live process: the runner escalates to
#: os.killpg(os.getpgid(pid)), and pid 0 would signal our own process group.
#: -1 raises inside getpgid, which is the intended fallback path.
FAKE_PID = -1


class FakeStdin:
    def __init__(self) -> None:
        self.buffer = bytearray()
        self.closed = False

    def write(self, data: bytes) -> None:
        self.buffer.extend(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    @property
    def text(self) -> str:
        return self.buffer.decode()


class FakeProcess:
    """Implements the SpawnedProcess protocol."""

    def __init__(
        self,
        *,
        stdout: bytes = b"",
        stderr: bytes = b"",
        exit_code: int = 0,
        runtime: float = 0.0,
        never_exits: bool = False,
    ) -> None:
        self.stdout = _reader(stdout)
        self.stderr = _reader(stderr)
        self.stdin = FakeStdin()
        self.pid = FAKE_PID
        self.returncode: int | None = None
        self.killed = False
        self._exit_code = exit_code
        self._runtime = runtime
        self._never_exits = never_exits
        self._done = asyncio.Event()

    async def wait(self) -> int:
        if self.returncode is not None:
            return self.returncode
        if self._never_exits:
            await self._done.wait()
            return self.returncode if self.returncode is not None else -9
        if self._runtime:
            await asyncio.sleep(self._runtime)
        self.returncode = self._exit_code
        self._done.set()
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        if self.returncode is None:
            self.returncode = -9
        self._done.set()

    def send_signal(self, sig: int) -> None:
        self.kill()

    def terminate(self) -> None:
        self.kill()


def _reader(data: bytes) -> asyncio.StreamReader:
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    reader.feed_eof()
    return reader


def fake_spawner(
    *,
    stdout: bytes = b"",
    stderr: bytes = b"",
    exit_code: int = 0,
    runtime: float = 0.0,
    never_exits: bool = False,
    calls: list[dict[str, Any]] | None = None,
    processes: list[FakeProcess] | None = None,
):
    """Build a Spawner that yields FakeProcess objects.

    ``calls`` captures argv and kwargs so tests can assert on the command line
    an adapter actually built — which is the only way to catch a wrong flag
    without a live CLI.
    """

    async def spawn(*argv: str, **kwargs: Any) -> FakeProcess:
        proc = FakeProcess(
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            runtime=runtime,
            never_exits=never_exits,
        )
        if calls is not None:
            calls.append({"argv": list(argv), "kwargs": kwargs})
        if processes is not None:
            processes.append(proc)
        return proc

    return spawn


__all__ = ["FAKE_PID", "FakeProcess", "FakeStdin", "fake_spawner"]
