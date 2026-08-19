"""ProcessRunner: streaming, timeout, tree kill, cancellation."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import subprocess
import sys
import time
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


def test_real_spawn_is_wrapped_with_linux_parent_death_guard(
    tmp_path: Path, monkeypatch
):
    calls: list = []
    monkeypatch.setattr("sleipnir.process._default_spawn", fake_spawner(calls=calls))
    runner = ProcessRunner()
    run(
        runner.run(
            ["provider-cli", "--flag"],
            stdout_path=tmp_path / "out.log",
            stderr_path=tmp_path / "err.log",
        )
    )
    if sys.platform.startswith("linux"):
        assert calls[0]["argv"] == [
            sys.executable,
            str(Path(__file__).parents[1] / "src" / "sleipnir" / "process_guard.py"),
            "--",
            "provider-cli",
            "--flag",
        ]
    else:
        assert calls[0]["argv"] == ["provider-cli", "--flag"]


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux prctl contract")
def test_parent_death_guard_terminates_child_after_hard_parent_kill():
    guard = Path(__file__).parents[1] / "src" / "sleipnir" / "process_guard.py"
    supervisor_code = f"""
import subprocess, sys, time
child = subprocess.Popen([
    sys.executable, {str(guard)!r}, '--',
    sys.executable, '-c',
    'import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)'
])
print(child.pid, flush=True)
time.sleep(30)
"""
    supervisor = subprocess.Popen(
        [sys.executable, "-c", supervisor_code],
        stdout=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    assert supervisor.stdout is not None
    child_pid = int(supervisor.stdout.readline().strip())
    provider_pid: int | None = None

    def stopped(pid: int) -> bool:
        try:
            return Path(f"/proc/{pid}/stat").read_text().split()[2] == "Z"
        except (FileNotFoundError, ProcessLookupError):
            return True

    try:
        children = Path(f"/proc/{child_pid}/task/{child_pid}/children")
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            values = children.read_text().split() if children.exists() else []
            if values:
                provider_pid = int(values[0])
                break
            time.sleep(0.02)
        assert provider_pid is not None
        os.kill(supervisor.pid, signal.SIGKILL)
        supervisor.wait(timeout=2)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            processes = [child_pid, provider_pid]
            if all(stopped(pid) for pid in processes):
                break
            time.sleep(0.02)
        else:
            states = {
                pid: ("stopped" if stopped(pid) else "running")
                for pid in processes
            }
            pytest.fail(f"guarded child survived its parent's SIGKILL: {states}")
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.kill(child_pid, signal.SIGKILL)
        if provider_pid is not None:
            with contextlib.suppress(ProcessLookupError):
                os.kill(provider_pid, signal.SIGKILL)
