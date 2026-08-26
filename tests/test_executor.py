"""Executor: dependency order, concurrency cap, dry run, recovery, cancellation."""

from __future__ import annotations

import asyncio
import fcntl
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_schema import finished, make_task

from sleipnir.adapters.base import (
    BaseAdapter,
    DispatchOutcome,
    DispatchPreview,
    DispatchRequest,
)
from sleipnir.checks import UnsupportedCheckError
from sleipnir.executor import ConcurrentExecutionError, Executor, ExecutorConfig, StaticRouter
from sleipnir.runlog import ResultLog
from sleipnir.schema import (
    Adapter,
    AttemptFinished,
    AttemptStarted,
    AttemptStatus,
    BillingMode,
    CommandCheck,
    ExpectedOutput,
    FailureKind,
    LlmJudgeCheck,
    OutputContract,
    OutputKind,
    Plan,
    TaskStatus,
    Tier,
    TokenUsage,
)

T0 = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
ROUTER = StaticRouter({tier: (Adapter.OPENROUTER, f"test/{tier.value}") for tier in Tier})


def run(coro):
    return asyncio.run(coro)


def plan_of(*tasks) -> Plan:
    return Plan(plan_id="p", goal="Ship the thing.", created_at=T0, tasks=list(tasks))


class ScriptedAdapter(BaseAdapter):
    """Records dispatches, tracks peak concurrency, writes declared outputs."""

    name = Adapter.OPENROUTER

    def __init__(
        self,
        *,
        write_outputs: bool = True,
        status: AttemptStatus = AttemptStatus.SUCCEEDED,
        failure_kind: FailureKind | None = None,
        delay: float = 0.0,
        summary: str = "did the thing",
        billing_mode: BillingMode = BillingMode.METERED,
        cost: float | None = 0.01,
        server_tool_use: dict[str, int] | None = None,
        raises: Exception | None = None,
        fail_first: int = 0,
        write_only: set[str] | None = None,
    ) -> None:
        self.write_only = write_only
        self.write_outputs = write_outputs
        self.status = status
        self.failure_kind = failure_kind
        self.delay = delay
        self.summary = summary
        self.billing_mode = billing_mode
        self.cost = cost
        self.server_tool_use = server_tool_use or {}
        self.raises = raises
        self.fail_first = fail_first
        self.dispatched: list[tuple[str, int]] = []
        self.in_flight = 0
        self.peak = 0

    async def dispatch(self, request: DispatchRequest) -> DispatchOutcome:
        self.dispatched.append((request.task.id, request.attempt))
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.raises is not None:
                raise self.raises

            workspace = request.workspace
            workspace.prepare()
            workspace.write_text("summary.md", self.summary)

            failing = len(self.dispatched) <= self.fail_first
            if self.write_outputs and not failing:
                for expected in request.task.outputs.outputs:
                    if self.write_only is not None and expected.name not in self.write_only:
                        continue
                    workspace.write_text(expected.path, f"content of {expected.name}\n")

            if failing:
                return DispatchOutcome(
                    status=AttemptStatus.FAILED,
                    failure_kind=FailureKind.PROVIDER_ERROR,
                    billing_mode=self.billing_mode,
                    reported_cost_usd=self.cost,
                )
            return DispatchOutcome(
                status=self.status,
                failure_kind=self.failure_kind,
                billing_mode=self.billing_mode,
                usage=TokenUsage(
                    input_tokens=100,
                    output_tokens=50,
                    server_tool_use=self.server_tool_use,
                ),
                reported_cost_usd=self.cost,
                exit_code=0,
            )
        finally:
            self.in_flight -= 1

    def preview(self, request: DispatchRequest) -> DispatchPreview:
        return DispatchPreview(
            task_id=request.task.id,
            attempt=request.attempt,
            adapter=self.name,
            tier_final=request.tier_final,
            model=request.model,
            target="scripted",
            prompt_bytes=len(request.prompt.encode()),
            estimated_input_tokens=10,
            timeout_s=request.timeout_s,
            workspace=request.workspace.rel_dir,
        )


def build(
    tmp_path: Path,
    plan: Plan,
    adapter: ScriptedAdapter,
    *,
    staled_at: dict[str, int] | None = None,
    **config_kwargs,
):
    log = ResultLog(tmp_path / "results.jsonl")
    executor = Executor(
        plan,
        adapters={Adapter.OPENROUTER: adapter},
        router=ROUTER,
        log=log,
        config=ExecutorConfig(run_root=tmp_path, env={}, **config_kwargs),
        staled_at=staled_at,
    )
    return executor, log


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------


def test_dependencies_are_respected(tmp_path: Path):
    plan = plan_of(
        make_task("a"),
        make_task("b", deps=["a"]),
        make_task("c", deps=["b"]),
    )
    adapter = ScriptedAdapter()
    executor, _ = build(tmp_path, plan, adapter)
    run(executor.run())
    assert [tid for tid, _ in adapter.dispatched] == ["a", "b", "c"]


def test_concurrency_cap_is_enforced(tmp_path: Path):
    plan = plan_of(*[make_task(f"t{i}") for i in range(8)])
    adapter = ScriptedAdapter(delay=0.02)
    executor, _ = build(tmp_path, plan, adapter, concurrency=3)
    report = run(executor.run())
    assert adapter.peak == 3, f"peak concurrency was {adapter.peak}, cap was 3"
    assert report.succeeded == 8


def test_concurrency_of_one_serializes(tmp_path: Path):
    plan = plan_of(*[make_task(f"t{i}") for i in range(4)])
    adapter = ScriptedAdapter(delay=0.01)
    executor, _ = build(tmp_path, plan, adapter, concurrency=1)
    run(executor.run())
    assert adapter.peak == 1


def test_independent_tasks_actually_run_in_parallel(tmp_path: Path):
    plan = plan_of(*[make_task(f"t{i}") for i in range(3)])
    adapter = ScriptedAdapter(delay=0.05)
    executor, _ = build(tmp_path, plan, adapter, concurrency=3)
    run(executor.run())
    assert adapter.peak == 3


def test_higher_priority_dispatches_first(tmp_path: Path):
    plan = plan_of(
        make_task("low", priority=0),
        make_task("high", priority=10),
    )
    adapter = ScriptedAdapter()
    executor, _ = build(tmp_path, plan, adapter, concurrency=1)
    run(executor.run())
    assert adapter.dispatched[0][0] == "high"


def test_semantic_revision_reruns_superseded_then_stale_descendants(tmp_path: Path):
    original = plan_of(
        make_task("a"),
        make_task("b", deps=["a"]),
        make_task("c", deps=["b"]),
    )
    changed_a = original.by_id["a"].model_copy(
        update={"description": "A materially revised upstream contract."}
    )
    revised = original.model_copy(
        update={
            "revision": 1,
            "tasks": [changed_a, original.by_id["b"], original.by_id["c"]],
        }
    )
    adapter = ScriptedAdapter()
    executor, log = build(
        tmp_path,
        revised,
        adapter,
        concurrency=3,
        staled_at={"b": 1, "c": 1},
    )
    for task_id in ("a", "b", "c"):
        record = finished(task_id, attempt=1, spec_hash=original.by_id[task_id].spec_hash())
        record.plan_revision = 0
        log.append(record)

    report = run(executor.run())

    assert adapter.dispatched == [("a", 2), ("b", 2), ("c", 2)]
    assert all(state.status is TaskStatus.DONE for state in report.final_states.values())


# ---------------------------------------------------------------------------
# Record composition
# ---------------------------------------------------------------------------


def test_start_record_precedes_the_finish_record(tmp_path: Path):
    """A crash between the two must leave evidence that money was committed."""
    plan = plan_of(make_task("a"))
    executor, log = build(tmp_path, plan, ScriptedAdapter())
    run(executor.run())
    records = log.read()
    assert isinstance(records[0], AttemptStarted)
    assert isinstance(records[1], AttemptFinished)
    assert records[0].attempt == records[1].attempt == 1


def test_producing_nothing_is_failed_not_partial(tmp_path: Path):
    """Partial means *some* of the work exists. Nothing is a failure."""
    plan = plan_of(make_task("a"))
    adapter = ScriptedAdapter(write_outputs=False)
    executor, log = build(tmp_path, plan, adapter)
    run(executor.run())
    record = [r for r in log.read() if isinstance(r, AttemptFinished)][-1]
    assert record.status is AttemptStatus.FAILED
    assert record.missing_outputs == ["result"]
    assert record.failure_kind is FailureKind.ACCEPTANCE_FAILED


def test_some_outputs_present_and_some_missing_is_partial(tmp_path: Path):
    """The half-worked case from DESIGN.md Q2, end to end."""
    plan = plan_of(
        make_task(
            "a",
            outputs=OutputContract(
                outputs=[
                    ExpectedOutput(
                        name="code", kind=OutputKind.FILE, path="out.py",
                        description="The implementation.",
                    ),
                    ExpectedOutput(
                        name="tests", kind=OutputKind.FILE, path="test_out.py",
                        description="The tests.",
                    ),
                ]
            ),
        )
    )
    adapter = ScriptedAdapter(write_only={"code"})
    executor, log = build(tmp_path, plan, adapter)
    run(executor.run())
    record = [r for r in log.read() if isinstance(r, AttemptFinished)][-1]
    assert record.status is AttemptStatus.PARTIAL
    assert record.missing_outputs == ["tests"]
    assert [a.name for a in record.artifacts if a.name] == ["code"]


def test_failed_acceptance_check_fails_a_complete_attempt(tmp_path: Path):
    plan = plan_of(make_task("a", acceptance=[CommandCheck(command="exit 7")]))
    executor, log = build(tmp_path, plan, ScriptedAdapter())
    run(executor.run())
    record = [r for r in log.read() if isinstance(r, AttemptFinished)][-1]
    assert record.status is AttemptStatus.FAILED
    assert record.failure_kind is FailureKind.ACCEPTANCE_FAILED
    assert record.missing_outputs == []
    assert any(not check.passed for check in record.checks)


def test_passing_acceptance_check_succeeds(tmp_path: Path):
    plan = plan_of(make_task("a", acceptance=[CommandCheck(command="test -s out.py")]))
    executor, log = build(tmp_path, plan, ScriptedAdapter())
    run(executor.run())
    record = [r for r in log.read() if isinstance(r, AttemptFinished)][-1]
    assert record.status is AttemptStatus.SUCCEEDED
    assert all(check.passed for check in record.checks)


def test_adapter_exception_becomes_an_adapter_error_record(tmp_path: Path):
    plan = plan_of(make_task("a"))
    adapter = ScriptedAdapter(raises=RuntimeError("boom"))
    executor, log = build(tmp_path, plan, adapter)
    run(executor.run())
    record = [r for r in log.read() if isinstance(r, AttemptFinished)][-1]
    assert record.failure_kind is FailureKind.ADAPTER_ERROR
    # The only diagnostic that exists must survive into the record.
    assert "boom" in record.summary


def test_summary_comes_from_the_subagents_file_and_is_clipped(tmp_path: Path):
    plan = plan_of(make_task("a"))
    adapter = ScriptedAdapter(summary="S" * 5_000)
    executor, log = build(tmp_path, plan, adapter)
    run(executor.run())
    record = [r for r in log.read() if isinstance(r, AttemptFinished)][-1]
    assert record.summary_truncated
    assert len(record.summary) <= AttemptFinished.SUMMARY_MAX_CHARS


def test_summary_symlink_cannot_read_a_host_file(tmp_path: Path):
    secret = tmp_path / "host-secret.txt"
    secret.write_text("DO-NOT-EXFILTRATE")
    plan = plan_of(make_task("a"))

    class SymlinkingAdapter(ScriptedAdapter):
        async def dispatch(self, request):
            outcome = await super().dispatch(request)
            request.workspace.summary_path.unlink()
            request.workspace.summary_path.symlink_to(secret)
            outcome.summary_text = "safe provider summary"
            return outcome

    executor, log = build(tmp_path / "run", plan, SymlinkingAdapter())
    run(executor.run())
    record = [r for r in log.read() if isinstance(r, AttemptFinished)][-1]
    assert record.summary == "safe provider summary"
    assert "DO-NOT-EXFILTRATE" not in record.model_dump_json()


def test_declared_output_symlink_cannot_read_a_host_file(tmp_path: Path):
    secret = tmp_path / "host-secret.txt"
    secret.write_text("DO-NOT-EXFILTRATE")
    plan = plan_of(make_task("a"))

    class SymlinkingAdapter(ScriptedAdapter):
        async def dispatch(self, request):
            outcome = await super().dispatch(request)
            output = request.workspace.dir / "out.py"
            output.unlink()
            output.symlink_to(secret)
            return outcome

    executor, log = build(tmp_path / "run", plan, SymlinkingAdapter())
    run(executor.run())
    record = [r for r in log.read() if isinstance(r, AttemptFinished)][-1]
    assert record.status is AttemptStatus.FAILED
    assert record.missing_outputs == ["result"]
    assert all(artifact.path != str(secret) for artifact in record.artifacts)


def test_metered_and_subscription_costs_are_tallied_separately(tmp_path: Path):
    plan = plan_of(make_task("a"))
    metered = ScriptedAdapter(billing_mode=BillingMode.METERED, cost=0.25)
    executor, _ = build(tmp_path, plan, metered)
    report = run(executor.run())
    assert report.cost_usd == pytest.approx(0.25)
    assert report.notional_usd == 0.0
    assert report.window_tokens == 0

    plan2 = plan_of(make_task("b"))
    subscription = ScriptedAdapter(billing_mode=BillingMode.SUBSCRIPTION, cost=0.25)
    executor2, _ = build(tmp_path / "run2", plan2, subscription)
    report2 = run(executor2.run())
    # Subscription spend does not count against the dollar budget, but it does
    # consume the window — and its notional value stays visible, so a report
    # never reads "$0.0000" after doing real work.
    assert report2.cost_usd == 0.0
    assert report2.notional_usd == pytest.approx(0.25)
    assert report2.window_tokens == 150
    assert "notional=$0.2500" in report2.render()


def test_codex_subscription_usage_does_not_consume_the_claude_window(tmp_path: Path):
    plan = plan_of(make_task("a"))
    adapter = ScriptedAdapter(billing_mode=BillingMode.SUBSCRIPTION, cost=0.25)
    executor = Executor(
        plan,
        adapters={Adapter.CODEX: adapter},
        router=StaticRouter({tier: (Adapter.CODEX, "codex-worker") for tier in Tier}),
        log=ResultLog(tmp_path / "results.jsonl"),
        config=ExecutorConfig(run_root=tmp_path, env={}),
    )
    report = run(executor.run())
    assert report.window_tokens == 0
    assert report.codex_tokens == 150
    assert "codex_tokens=150" in report.render()


def test_reported_cost_marks_the_estimate_as_authoritative(tmp_path: Path):
    plan = plan_of(make_task("a"))
    executor, log = build(tmp_path, plan, ScriptedAdapter(cost=0.5))
    run(executor.run())
    record = [r for r in log.read() if isinstance(r, AttemptFinished)][-1]
    assert record.cost.is_estimate is False

    plan2 = plan_of(make_task("b"))
    executor2, log2 = build(tmp_path / "r2", plan2, ScriptedAdapter(cost=None))
    run(executor2.run())
    record2 = [r for r in log2.read() if isinstance(r, AttemptFinished)][-1]
    assert record2.cost.is_estimate is True


def test_report_preserves_server_tool_counts_with_the_authoritative_total(tmp_path: Path):
    plan = plan_of(make_task("a"))
    executor, log = build(
        tmp_path,
        plan,
        ScriptedAdapter(cost=0.017, server_tool_use={"web_search_requests": 2}),
    )
    report = run(executor.run())
    record = [item for item in log.read() if isinstance(item, AttemptFinished)][-1]

    assert record.cost.amount_usd == pytest.approx(0.017)
    assert record.usage.server_tool_use == {"web_search_requests": 2}
    assert report.server_tool_use == {"web_search_requests": 2}
    assert "server_tools=web_search_requests=2" in report.render()


# ---------------------------------------------------------------------------
# Retry and recovery
# ---------------------------------------------------------------------------


def test_a_failed_task_is_retried_then_succeeds(tmp_path: Path):
    plan = plan_of(make_task("a"))
    adapter = ScriptedAdapter(fail_first=1)
    executor, log = build(tmp_path, plan, adapter)
    report = run(executor.run())
    assert adapter.dispatched == [("a", 1), ("a", 2)]
    assert report.succeeded == 1 and report.failed == 1
    assert executor._states()["a"].status is TaskStatus.DONE


def test_attempts_do_not_share_a_directory(tmp_path: Path):
    plan = plan_of(make_task("a"))
    executor, _ = build(tmp_path, plan, ScriptedAdapter(fail_first=1))
    run(executor.run())
    attempts = sorted((tmp_path / "artifacts" / "task-a").iterdir())
    assert [p.name for p in attempts] == ["attempt-01", "attempt-02"]


def test_preexisting_attempt_workspace_is_never_reused_as_provider_output(tmp_path: Path):
    from sleipnir.artifacts import WorkspaceCollisionError

    poisoned = tmp_path / "artifacts" / "task-a" / "attempt-01"
    poisoned.mkdir(parents=True)
    (poisoned / "out.py").write_text("attacker-controlled")
    (poisoned / "summary.md").write_text("pretend this succeeded")
    adapter = ScriptedAdapter(write_outputs=False)
    executor, log = build(tmp_path, plan_of(make_task("a")), adapter)

    with pytest.raises(WorkspaceCollisionError, match="pre-existing"):
        run(executor.run())
    assert adapter.dispatched == []
    assert log.read() == []


def test_completed_work_is_not_redispatched_on_resume(tmp_path: Path):
    plan = plan_of(make_task("a"), make_task("b", deps=["a"]))
    first = ScriptedAdapter()
    executor, log = build(tmp_path, plan, first)
    run(executor.run())
    assert len(first.dispatched) == 2

    # Same run root, same log: a resume must find both tasks already done.
    second = ScriptedAdapter()
    resumed = Executor(
        plan,
        adapters={Adapter.OPENROUTER: second},
        router=ROUTER,
        log=ResultLog(tmp_path / "results.jsonl"),
        config=ExecutorConfig(run_root=tmp_path, env={}),
    )
    run(resumed.run())
    assert second.dispatched == [], "resume must not re-run completed tasks"


def test_resume_closes_an_open_attempt_and_retries_in_a_fresh_workspace(tmp_path: Path):
    """A hard-killed executor leaves only AttemptStarted; resume must not keep
    that task in RUNNING forever or overwrite its first workspace."""
    plan = plan_of(make_task("a"))
    log = ResultLog(tmp_path / "results.jsonl")
    routing = ROUTER.resolve(plan.tasks[0], attempt=1, tier=Tier.CODE)
    log.append(AttemptStarted(
        run_id="killed-run",
        task_id="a",
        attempt=1,
        spec_hash=plan.tasks[0].spec_hash(),
        plan_revision=plan.revision,
        routing=routing,
        pid=2_147_483_647,
        started_at=T0,
    ))

    adapter = ScriptedAdapter()
    resumed = Executor(
        plan,
        adapters={Adapter.OPENROUTER: adapter},
        router=ROUTER,
        log=log,
        config=ExecutorConfig(run_root=tmp_path, env={}),
    )
    report = run(resumed.run())

    assert adapter.dispatched == [("a", 2)]
    assert report.succeeded == 1 and report.failed == 0
    assert log.open_attempts() == {}
    interrupted = [
        record for record in log.read()
        if isinstance(record, AttemptFinished)
        and record.attempt == 1
    ]
    assert interrupted[0].failure_kind is FailureKind.INTERRUPTED
    assert (tmp_path / "artifacts" / "task-a" / "attempt-02").is_dir()


def test_resume_refuses_to_steal_an_attempt_from_a_live_executor(tmp_path: Path):
    plan = plan_of(make_task("a"))
    log = ResultLog(tmp_path / "results.jsonl")
    routing = ROUTER.resolve(plan.tasks[0], attempt=1, tier=Tier.CODE)
    log.append(AttemptStarted(
        run_id="live-run",
        task_id="a",
        attempt=1,
        spec_hash=plan.tasks[0].spec_hash(),
        plan_revision=plan.revision,
        routing=routing,
        pid=os.getpid(),
        started_at=T0,
    ))
    resumed = Executor(
        plan,
        adapters={Adapter.OPENROUTER: ScriptedAdapter()},
        router=ROUTER,
        log=log,
        config=ExecutorConfig(run_root=tmp_path, env={}),
    )
    with pytest.raises(ConcurrentExecutionError, match="live executor"):
        run(resumed.run())


def test_run_refuses_when_another_executor_owns_the_run_directory(tmp_path: Path):
    """Two executors must not race between readiness and AttemptStarted."""
    plan = plan_of(make_task("a"))
    executor, _ = build(tmp_path, plan, ScriptedAdapter())
    lock_path = tmp_path / "run.lock"
    lock_path.touch()
    with lock_path.open("r+") as owner:
        owner.write("pid=4242\n")
        owner.flush()
        fcntl.flock(owner.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ConcurrentExecutionError, match=r"already active.*pid=4242"):
            run(executor.run())

    assert not (tmp_path / "results.jsonl").exists()


def test_run_lock_activity_probe_distinguishes_owned_from_stale_file(tmp_path: Path):
    from sleipnir.runlog import RunLock, run_is_active

    assert run_is_active(tmp_path) is False
    with RunLock(tmp_path):
        assert run_is_active(tmp_path) is True
    assert run_is_active(tmp_path) is False


def test_executor_refuses_a_plan_changed_before_lock_acquisition(tmp_path: Path):
    loaded = plan_of(make_task("a"))
    changed = plan_of(make_task("different"))
    (tmp_path / "plan.json").write_text(changed.model_dump_json())
    executor, _ = build(tmp_path, loaded, ScriptedAdapter())
    with pytest.raises(ConcurrentExecutionError, match="plan changed"):
        run(executor.run())


def test_result_log_refuses_a_precreated_symlink(tmp_path: Path):
    outside = tmp_path / "outside.txt"
    outside.write_text("must stay unchanged")
    run_root = tmp_path / "run"
    run_root.mkdir()
    (run_root / "results.jsonl").symlink_to(outside)
    executor, _ = build(run_root, plan_of(make_task("a")), ScriptedAdapter())
    from sleipnir.runlog import TornRecordError

    with pytest.raises(TornRecordError, match="symlinked result log"):
        run(executor.run())
    assert outside.read_text() == "must stay unchanged"


def test_downstream_receives_the_upstream_summary(tmp_path: Path):
    plan = plan_of(make_task("a"), make_task("b", deps=["a"]))
    captured: list[str] = []

    class Capturing(ScriptedAdapter):
        async def dispatch(self, request):
            captured.append(request.prompt)
            return await super().dispatch(request)

    executor, _ = build(tmp_path, plan, Capturing(summary="ALPHA-RESULT"))
    run(executor.run())
    assert "ALPHA-RESULT" in captured[1], "b must see a's summary"


def test_dependents_are_skipped_when_a_dependency_fails(tmp_path: Path):
    plan = plan_of(make_task("a"), make_task("b", deps=["a"]))
    adapter = ScriptedAdapter(fail_first=99)  # every attempt fails
    executor, _ = build(tmp_path, plan, adapter)
    run(executor.run())
    states = executor._states()
    assert states["a"].status is TaskStatus.FAILED
    assert states["b"].status is TaskStatus.SKIPPED
    assert all(tid == "a" for tid, _ in adapter.dispatched)


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


def test_cancellation_records_every_in_flight_attempt(tmp_path: Path):
    """No attempt may be left started-but-unfinished: that is what `resume`
    would otherwise misread as an orphan."""
    plan = plan_of(*[make_task(f"t{i}") for i in range(3)])
    adapter = ScriptedAdapter(delay=5.0)
    executor, log = build(tmp_path, plan, adapter, concurrency=3)

    async def scenario():
        task = asyncio.create_task(executor.run())
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    run(scenario())
    assert log.open_attempts() == {}
    cancelled = [
        r
        for r in log.read()
        if isinstance(r, AttemptFinished) and r.status is AttemptStatus.CANCELLED
    ]
    assert len(cancelled) == 3
    assert all(r.failure_kind is FailureKind.CANCELLED for r in cancelled)


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


def test_dry_run_spends_nothing_and_writes_nothing(tmp_path: Path):
    plan = plan_of(make_task("a"), make_task("b", deps=["a"]), make_task("c", deps=["b"]))
    adapter = ScriptedAdapter()
    executor, log = build(tmp_path, plan, adapter, dry_run=True)
    report = run(executor.run())

    assert adapter.dispatched == [], "a dry run must never dispatch"
    assert not (tmp_path / "results.jsonl").exists()
    assert not (tmp_path / "artifacts").exists()
    assert [p.task_id for p in report.previews] == ["a", "b", "c"]


def test_dry_run_previews_the_whole_dag_not_just_the_first_wave(tmp_path: Path):
    plan = plan_of(*[make_task(f"t{i}", deps=[f"t{i-1}"] if i else []) for i in range(6)])
    executor, _ = build(tmp_path, plan, ScriptedAdapter(), dry_run=True)
    previews = executor.dry_run()
    assert len(previews) == 6
    assert all(p.estimated_input_tokens > 0 for p in previews)


def test_dry_run_skips_already_completed_tasks(tmp_path: Path):
    plan = plan_of(make_task("a"), make_task("b", deps=["a"]))
    executor, log = build(tmp_path, plan, ScriptedAdapter())
    run(executor.run())

    dry = Executor(
        plan,
        adapters={Adapter.OPENROUTER: ScriptedAdapter()},
        router=ROUTER,
        log=ResultLog(tmp_path / "results.jsonl"),
        config=ExecutorConfig(run_root=tmp_path, env={}, dry_run=True),
    )
    assert dry.dry_run() == []


def test_preview_renders_without_crashing(tmp_path: Path):
    plan = plan_of(make_task("a"))
    executor, _ = build(tmp_path, plan, ScriptedAdapter(), dry_run=True)
    assert "a" in executor.dry_run()[0].render()


# ---------------------------------------------------------------------------
# Guardrails
# ---------------------------------------------------------------------------


def test_plan_with_unimplemented_check_is_rejected_before_dispatch(tmp_path: Path):
    """Fail loudly at construction, not silently at task 40."""
    plan = plan_of(make_task("a", acceptance=[LlmJudgeCheck(rubric="is it good enough?")]))
    with pytest.raises(UnsupportedCheckError, match="llm_judge"):
        build(tmp_path, plan, ScriptedAdapter())


def test_plan_whose_command_check_names_a_missing_program_is_rejected(tmp_path: Path):
    """A check that cannot run must refuse the plan, not fail every attempt.

    Found live on 2026-08-26: a generated plan asked for
    `pytest -q tests/test_roman_numerals.py` on a machine with no `pytest` on
    PATH. Nothing could ever satisfy it, so the task burned three full Codex
    dispatches and took its whole downstream subtree down with it.
    """
    plan = plan_of(
        make_task(
            "a",
            acceptance=[CommandCheck(command="definitely-not-a-real-program --version")],
        )
    )
    with pytest.raises(UnsupportedCheckError, match="definitely-not-a-real-program"):
        build(tmp_path, plan, ScriptedAdapter())


def test_a_command_check_using_shell_syntax_is_not_second_guessed(tmp_path: Path):
    """Only the unambiguous case is refused.

    Once a command contains shell syntax its program cannot be resolved
    statically, and refusing on a guess would reject working plans.
    """
    plan = plan_of(
        make_task(
            "a",
            acceptance=[CommandCheck(command="definitely-not-real || true")],
        )
    )
    build(tmp_path, plan, ScriptedAdapter())


def test_shell_builtins_are_not_looked_up_on_path(tmp_path: Path):
    plan = plan_of(make_task("a", acceptance=[CommandCheck(command="cd tests")]))
    build(tmp_path, plan, ScriptedAdapter())


def test_unregistered_adapter_raises(tmp_path: Path):
    plan = plan_of(make_task("a"))
    log = ResultLog(tmp_path / "results.jsonl")
    executor = Executor(
        plan,
        adapters={},
        router=ROUTER,
        log=log,
        config=ExecutorConfig(run_root=tmp_path, env={}),
    )
    with pytest.raises(KeyError, match="no adapter registered"):
        run(executor.run())
