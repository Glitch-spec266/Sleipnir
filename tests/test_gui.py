"""Desktop dashboard projection stays derived, bounded, and content-safe."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sleipnir.gui import build_dashboard_snapshot, load_dashboard
from sleipnir.runlog import ResultLog
from sleipnir.schema import (
    Adapter,
    AttemptFinished,
    AttemptStarted,
    AttemptStatus,
    BillingMode,
    CostEstimate,
    ExpectedOutput,
    InputContract,
    OutputContract,
    OutputKind,
    Plan,
    RoutingDecision,
    Task,
    Tier,
    TokenUsage,
)

NOW = datetime(2026, 9, 9, 20, 0, tzinfo=UTC)


def task(task_id: str, *, dependencies: list[str] | None = None) -> Task:
    dependencies = dependencies or []
    return Task(
        id=task_id,
        group="desktop",
        description=f"Implement the {task_id} desktop integration.",
        tier=Tier.CODE,
        depends_on=dependencies,
        inputs=InputContract(summaries=dependencies),
        outputs=OutputContract(
            outputs=[
                ExpectedOutput(
                    name="result",
                    kind=OutputKind.FILE,
                    path="result.txt",
                    description="Verified integration output.",
                )
            ]
        ),
    )


def route() -> RoutingDecision:
    return RoutingDecision(
        tier_requested=Tier.CODE,
        tier_final=Tier.CODE,
        model="cli-default",
        adapter=Adapter.CODEX,
        rationale="Use the already-authenticated coding subscription.",
    )


def test_snapshot_folds_task_state_and_never_reads_artifact_content(tmp_path):
    first = task("core")
    plan = Plan(
        plan_id="desktop-run",
        goal="Connect the native desktop to the existing Sleipnir core.",
        created_at=NOW,
        tasks=[first, task("shell", dependencies=["core"])],
    )
    secret = tmp_path / "artifacts" / "task-core" / "attempt-01" / "result.txt"
    secret.parent.mkdir(parents=True)
    secret.write_text("PRIVATE ARTIFACT BODY")
    record = AttemptFinished(
        run_id="run-1",
        task_id="core",
        attempt=1,
        spec_hash=first.spec_hash(),
        plan_revision=0,
        routing=route(),
        status=AttemptStatus.SUCCEEDED,
        started_at=NOW,
        ended_at=NOW,
        wall_time_s=0,
        usage=TokenUsage(input_tokens=120, output_tokens=30),
        cost=CostEstimate(
            billing_mode=BillingMode.SUBSCRIPTION,
            amount_usd=0.04,
            quota_pool="codex",
        ),
        summary="Core bridge is ready.",
    )

    snapshot = build_dashboard_snapshot(plan, [record], run_root=tmp_path, now=NOW)

    assert [item["state"] for item in snapshot["tasks"]] == ["done", "ready"]
    assert snapshot["tasks"][0]["model"] == "codex/cli-default"
    assert snapshot["run"]["progress"] == 50
    assert snapshot["source"] == "core"
    assert "PRIVATE ARTIFACT BODY" not in json.dumps(snapshot)


def test_load_dashboard_reads_plan_and_append_only_log(tmp_path):
    first = task("core")
    plan = Plan(plan_id="desktop-run", goal="Ship the desktop.", created_at=NOW, tasks=[first])
    (tmp_path / "plan.json").write_text(plan.model_dump_json(indent=2))
    started = AttemptStarted(
        run_id="run-1",
        task_id="core",
        attempt=1,
        spec_hash=first.spec_hash(),
        plan_revision=0,
        routing=route(),
        started_at=NOW,
    )
    ResultLog(tmp_path / "results.jsonl").append(started)

    snapshot = load_dashboard(tmp_path, now=NOW)

    assert snapshot["run"]["state"] == "running"
    assert snapshot["tasks"][0]["state"] == "running"
    assert snapshot["routes"][0]["status"] == "selected"
    assert snapshot["timeline"][0]["kind"] == "dispatch_started"


def test_load_dashboard_supports_a_workspace_before_its_first_plan(tmp_path):
    snapshot = load_dashboard(tmp_path, now=NOW)

    assert snapshot["source"] == "core"
    assert snapshot["run"] is None
    assert snapshot["tasks"] == []
    assert snapshot["runtime"]["connected"] is True
