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

from sleipnir import platform
from sleipnir.process import STDERR_TAIL_BYTES, ProcessRunner

#: What request_group_stop() labels its first, graceful attempt as, on this
#: platform -- used so the timeout test asserts a real, platform-correct
#: value instead of hardcoding the POSIX one.
_GRACEFUL_STOP_LABEL = "CTRL_BREAK_EVENT" if platform.IS_WINDOWS else "SIGTERM"


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
    assert _GRACEFUL_STOP_LABEL in result.signalled


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


def test_spawn_requests_its_own_group(tmp_path: Path):
    """The group-forming spawn kwargs are what let a tree-kill reach the
    CLI's children -- start_new_session on POSIX, CREATE_NEW_PROCESS_GROUP
    on Windows. This is unconditional: it applies even with a fake spawner,
    since forming the group is orthogonal to whether the parent-death guard
    (process_guard.py) is also wrapping argv."""
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
    for key, value in platform.CHILD_SPAWN_KWARGS.items():
        assert calls[0]["kwargs"][key] == value


def test_real_spawn_is_wrapped_with_a_parent_death_guard(tmp_path: Path, monkeypatch):
    """Only a *real* spawner (spawn=None, the ProcessRunner() default) gets
    wrapped -- test/injected spawners receive the adapter argv untouched, per
    test_spawn_requests_its_own_group above."""
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
    guard = str(Path(__file__).parents[1] / "src" / "sleipnir" / "process_guard.py")
    argv = calls[0]["argv"]
    if platform.IS_WINDOWS:
        # ['python', guard.py, '--job', <uuid-based name>, '--', 'provider-cli', '--flag']
        assert argv[0] == sys.executable
        assert argv[1] == guard
        assert argv[2] == "--job"
        assert argv[3].startswith("sleipnir-")
        assert argv[4:] == ["--", "provider-cli", "--flag"]
    elif sys.platform.startswith("linux"):
        assert argv == [sys.executable, guard, "--", "provider-cli", "--flag"]
    else:
        # No guard implementation on this POSIX platform (e.g. macOS):
        # platform.WRAPS_CHILDREN is False there, so argv passes through.
        assert argv == ["provider-cli", "--flag"]


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux prctl contract")
def test_parent_death_guard_terminates_child_after_hard_parent_kill():
    guard = Path(__file__).parents[1] / "src" / "sleipnir" / "process_guard.py"
    supervisor_code = f"""
import subprocess, sys, time
child = subprocess.Popen([
    sys.executable, {str(guard)!r}, '--',
    sys.executable, '-c', 'import time; time.sleep(30)'
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


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux prctl contract")
def test_parent_death_guard_escalates_to_sigkill_for_a_provider_that_ignores_sigterm(
    tmp_path: Path,
):
    """A provider that traps SIGTERM must still stop spending.

    On the ordinary cancellation path ``ProcessRunner`` escalates the group to
    SIGKILL after a grace period. After a hard parent SIGKILL no runner is left
    alive to do that, so the guard itself is the only thing standing between an
    ignored SIGTERM and a provider CLI that keeps burning quota unattended.
    """
    guard = Path(__file__).parents[1] / "src" / "sleipnir" / "process_guard.py"
    ready = tmp_path / "trapped"
    stubborn = (
        "import signal, pathlib, time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        f"pathlib.Path({str(ready)!r}).write_text('x'); "
        "time.sleep(30)"
    )
    supervisor_code = f"""
import subprocess, sys, time
child = subprocess.Popen([
    sys.executable, {str(guard)!r}, '--', sys.executable, '-c', {stubborn!r}
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
        except (FileNotFoundError, ProcessLookupError, IndexError):
            return True

    try:
        children = Path(f"/proc/{child_pid}/task/{child_pid}/children")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            values = children.read_text().split() if children.exists() else []
            # Only meaningful once the provider has actually trapped SIGTERM;
            # killing it before that measures interpreter startup, not the guard.
            if values and ready.exists():
                provider_pid = int(values[0])
                break
            time.sleep(0.02)
        assert provider_pid is not None
        os.kill(supervisor.pid, signal.SIGKILL)
        supervisor.wait(timeout=2)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if stopped(provider_pid):
                break
            time.sleep(0.05)
        else:
            pytest.fail(
                "a provider ignoring SIGTERM outlived its orphaned guard "
                f"(pid {provider_pid} still running)"
            )
    finally:
        for pid in (child_pid, provider_pid):
            if pid is not None:
                with contextlib.suppress(ProcessLookupError):
                    os.kill(pid, signal.SIGKILL)


@pytest.mark.skipif(not platform.IS_WINDOWS, reason="Windows job-object contract")
def test_windows_job_guard_terminates_after_hard_parent_kill(tmp_path: Path):
    """The Windows analogue of the two Linux tests above: a
    process_guard.py invocation must not survive a hard kill (TerminateProcess,
    not a cooperative close) of its launcher. create_guarded_launch's job
    object -- KILL_ON_JOB_CLOSE plus the guard's own parent-watch thread --
    is what stands in for PR_SET_PDEATHSIG on this platform; this is the
    live drill that PR_SET_PDEATHSIG's own tests run for Linux.
    """
    src_dir = Path(__file__).parents[1] / "src"
    supervisor_code = f"""
import sys, subprocess, time
sys.path.insert(0, {str(src_dir)!r})
from sleipnir import platform
gl = platform.create_guarded_launch([sys.executable, "-c", "import time; time.sleep(30)"])
proc = subprocess.Popen(gl.argv)
print(proc.pid, flush=True)
time.sleep(30)
"""
    supervisor = subprocess.Popen(
        [sys.executable, "-c", supervisor_code],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert supervisor.stdout is not None
    guard_pid = int(supervisor.stdout.readline().strip())
    assert platform.pid_is_alive(guard_pid)

    try:
        # A hard kill, not a cooperative one: this must not depend on the
        # supervisor running any of its own cleanup code.
        subprocess.run(
            ["taskkill", "/F", "/PID", str(supervisor.pid)], capture_output=True, check=False
        )
        supervisor.wait(timeout=5)

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and platform.pid_is_alive(guard_pid):
            time.sleep(0.05)
        assert not platform.pid_is_alive(guard_pid), "guard survived its parent's hard kill"
    finally:
        subprocess.run(
            ["taskkill", "/F", "/PID", str(guard_pid)], capture_output=True, check=False
        )
