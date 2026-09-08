"""The control brain sees only the bounded manifest and returns typed actions."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

from test_executor import ScriptedAdapter, plan_of
from test_schema import make_task

import pytest

from sleipnir.adapters.base import DispatchOutcome
from sleipnir.orchestrator import (
    ControlAction,
    ControlError,
    build_control_task,
    control_instructions,
    run_control_cycle,
)
from sleipnir.projection import build_manifest
from sleipnir.schema import (
    Adapter, AttemptStatus, BillingMode, BudgetSnapshot,
    RoutingDecision, Tier,
)


def test_control_prompt_contains_bounded_manifest_but_no_artifact_content(tmp_path):
    now = datetime(2026, 8, 19, tzinfo=UTC)
    plan = plan_of(make_task("a"))
    budget = BudgetSnapshot(window_start=now, window_end=now + timedelta(hours=5), observed_at=now)
    manifest = build_manifest(plan, [], budget, generated_at=now)
    prompt = control_instructions(manifest, plan)
    assert manifest.model_dump_json() in prompt
    assert plan.by_id["a"].description in prompt
    assert "artifact content" not in manifest.model_dump_json().lower()


def test_the_control_task_carries_no_truncated_copy_of_its_own_prompt(tmp_path):
    """Clip the goal, never the prompt — and never keep a clipped duplicate.

    The prompt is built at dispatch. A second copy sliced to the schema's
    4,000-character instructions cap discards the whole bounded manifest and
    the frontier drill-down, keeping only the header and half a JSON schema.
    It was never read and never counted toward routing, so its only possible
    effect was to hand a manifest-less prompt to anyone who later routed
    control through the ordinary prompt path.
    """
    now = datetime(2026, 8, 19, tzinfo=UTC)
    plan = plan_of(make_task("a"))
    budget = BudgetSnapshot(window_start=now, window_end=now + timedelta(hours=5), observed_at=now)
    manifest = build_manifest(plan, [], budget, generated_at=now)

    task = build_control_task(manifest, plan)
    prompt = control_instructions(manifest, plan)

    assert len(prompt) > 4_000, "the guarded case is a prompt longer than the cap"
    assert task.inputs.instructions is None, (
        "a sliced copy of the control prompt is worse than no copy"
    )


def test_control_cycle_parses_a_typed_stop_decision(tmp_path):
    now = datetime(2026, 8, 19, tzinfo=UTC)
    plan = plan_of(make_task("a"))
    budget = BudgetSnapshot(window_start=now, window_end=now + timedelta(hours=5), observed_at=now)
    manifest = build_manifest(plan, [], budget, generated_at=now)

    class Controller(ScriptedAdapter):
        name = Adapter.CLAUDE

        async def dispatch(self, request):
            request.workspace.prepare()
            request.workspace.write_text(
                "decision.json",
                json.dumps({"action": "stop", "reason": "Human input is required now.", "changes": []}),
            )
            return DispatchOutcome(status=AttemptStatus.SUCCEEDED, billing_mode=BillingMode.SUBSCRIPTION)

    routing = RoutingDecision(
        tier_requested=Tier.REASON, tier_final=Tier.REASON, model="brain",
        adapter=Adapter.CLAUDE, rationale="configured reason-tier brain",
    )
    decision, _, _ = asyncio.run(run_control_cycle(
        manifest, adapters={Adapter.CLAUDE: Controller()}, routing=routing,
        run_root=tmp_path, attempt=1, env={}, run_id="control-run",
    ))
    assert decision.action is ControlAction.STOP


def test_invalid_control_decision_preserves_outcome_for_durable_accounting(tmp_path):
    now = datetime(2026, 8, 19, tzinfo=UTC)
    plan = plan_of(make_task("a"))
    budget = BudgetSnapshot(window_start=now, window_end=now + timedelta(hours=5), observed_at=now)
    manifest = build_manifest(plan, [], budget, generated_at=now)

    class InvalidController(ScriptedAdapter):
        name = Adapter.CLAUDE

        async def dispatch(self, request):
            request.workspace.prepare()
            request.workspace.write_text("decision.json", "not valid control JSON")
            return DispatchOutcome(
                status=AttemptStatus.SUCCEEDED,
                billing_mode=BillingMode.SUBSCRIPTION,
            )

    routing = RoutingDecision(
        tier_requested=Tier.REASON,
        tier_final=Tier.REASON,
        model="brain",
        adapter=Adapter.CLAUDE,
    )
    with pytest.raises(ControlError) as captured:
        asyncio.run(run_control_cycle(
            manifest,
            adapters={Adapter.CLAUDE: InvalidController()},
            routing=routing,
            run_root=tmp_path,
            attempt=1,
            env={},
            run_id="control-run",
        ))
    assert captured.value.outcome is not None
    assert captured.value.output == tmp_path / "artifacts/task-sleipnir-control/attempt-01/decision.json"
