"""ProcessRunner: streaming, timeout, tree kill, cancellation."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fakes import fake_spawner

from sleipnir.process import STDERR_TAIL_BYTES, ProcessRunner


def run(coro):
    return asyncio.run(coro)


def test_streams_stdout_and_stderr_to_disk(tmp_path: Path):
    runner = ProcessRunner(spawn=fake_spawner(stdout=b"hello", stderr=b"oops", exit_code=0))
    result = run(
        runner.run(
            ["fake"], stdout_path=tmp_path / "out.log", stderr_path=tmp_path / "err.log"
        )
    )
    assert result.ok
    assert (tmp_path / "out.log").read_bytes() == b"hello"
    assert (tmp_path / "err.log").read_bytes() == b"oops"
    assert result.stderr_tail == "oops"


def test_large_output_does_not_deadlock(tmp_path: Path):
    """Pumps must run concurrently with wait(); draining after exit would hang
    the moment output exceeds one pipe buffer."""
    payload = b"x" * (4 * 1024 * 1024)
    runner = ProcessRunner(spawn=fake_spawner(stdout=payload))
    result = run(
        runner.run(
            ["fake"],
            stdout_path=tmp_path / "out.log",
            stderr_path=tmp_path / "err.log",
            timeout_s=10,
        )
    )
    assert result.stdout_bytes == len(payload)


def test_stderr_tail_is_bounded(tmp_path: Path):
    noisy = b"E" * (STDERR_TAIL_BYTES * 3)
    runner = ProcessRunner(spawn=fake_spawner(stderr=noisy))
    result = run(
        runner.run(
            ["fake"], stdout_path=tmp_path / "out.log", stderr_path=tmp_path / "err.log"
        )
    )
    assert len(result.stderr_tail) == STDERR_TAIL_BYTES
    assert (tmp_path / "err.log").stat().st_size == len(noisy)


def test_stdin_is_delivered(tmp_path: Path):
    processes: list = []
    runner = ProcessRunner(spawn=fake_spawner(processes=processes))
    run(
        runner.run(
            ["fake"],
            stdout_path=tmp_path / "out.log",
            stderr_path=tmp_path / "err.log",
            stdin_data="the prompt",
        )
    )
    assert processes[0].stdin.text == "the prompt"
    assert processes[0].stdin.closed


def test_timeout_kills_the_process(tmp_path: Path):
    processes: list = []
    runner = ProcessRunner(spawn=fake_spawner(never_exits=True, processes=processes))
    result = run(
        runner.run(
            ["fake"],
            stdout_path=tmp_path / "out.log",
            stderr_path=tmp_path / "err.log",
            timeout_s=0.05,
            grace_s=0.05,
        )
    )
    assert result.timed_out
    assert not result.ok
    assert processes[0].killed, "a timed-out process must not be left running"
    assert "SIGTERM" in result.signalled


def test_cancellation_kills_the_process_and_propagates(tmp_path: Path):
    processes: list = []
    runner = ProcessRunner(spawn=fake_spawner(never_exits=True, processes=processes))

    async def scenario():
        task = asyncio.create_task(
            runner.run(
                ["fake"],
                stdout_path=tmp_path / "out.log",
                stderr_path=tmp_path / "err.log",
                timeout_s=30,
                grace_s=0.05,
            )
        )
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    run(scenario())
    assert processes[0].killed, "cancellation must not orphan a running subagent"


def test_nonzero_exit_is_not_ok(tmp_path: Path):
    runner = ProcessRunner(spawn=fake_spawner(exit_code=3))
    result = run(
        runner.run(
            ["fake"], stdout_path=tmp_path / "out.log", stderr_path=tmp_path / "err.log"
        )
    )
    assert result.exit_code == 3
    assert not result.ok


def test_spawn_requests_its_own_session(tmp_path: Path):
    """start_new_session is what makes killpg reach the CLI's children."""
    calls: list = []
    runner = ProcessRunner(spawn=fake_spawner(calls=calls))
    run(
        runner.run(
            ["fake", "--flag"],
            stdout_path=tmp_path / "out.log",
            stderr_path=tmp_path / "err.log",
        )
    )
    assert calls[0]["argv"] == ["fake", "--flag"]
    assert calls[0]["kwargs"]["start_new_session"] is True
