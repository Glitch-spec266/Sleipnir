"""Terminal dashboard rendering stays bounded, useful, and content-safe."""

from __future__ import annotations

from datetime import UTC, datetime

from test_executor import plan_of
from test_schema import make_task

from sleipnir.schema import (
    Adapter,
    AttemptFinished,
    AttemptStatus,
    BillingMode,
    CostEstimate,
    RoutingDecision,
    Tier,
    TokenUsage,
)
from sleipnir.tui import render_dashboard


def test_dashboard_shows_progress_tasks_and_routes_without_summaries():
    plan = plan_of(make_task("schema"), make_task("api", deps=["schema"]))
    task = plan.by_id["schema"]
    now = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    record = AttemptFinished(
        run_id="run",
        task_id="schema",
        attempt=1,
        spec_hash=task.spec_hash(),
        plan_revision=0,
        routing=RoutingDecision(
            tier_requested=Tier.CODE,
            tier_final=Tier.CODE,
            model="worker/model",
            adapter=Adapter.CODEX,
            rationale="configured route",
        ),
        status=AttemptStatus.SUCCEEDED,
        started_at=now,
        ended_at=now,
        wall_time_s=0,
        cost=CostEstimate(billing_mode=BillingMode.SUBSCRIPTION, amount_usd=0.1),
        summary="PRIVATE SUBAGENT CONTENT",
    )

    screen = render_dashboard(plan, [record], width=100, height=30, now=now)
    assert "SLEIPNIR" in screen
    assert "schema" in screen and "api" in screen
    assert "codex/worker/model" in screen
    assert "1/2" in screen
    assert "PRIVATE SUBAGENT CONTENT" not in screen


def test_dashboard_bounds_large_plans_to_terminal_height():
    plan = plan_of(*[make_task(f"task-{index:03d}") for index in range(100)])
    screen = render_dashboard(plan, [], width=80, height=20)
    assert len(screen.splitlines()) <= 22
    assert "hidden" in screen


def test_dashboard_surfaces_brain_proposals_needing_review():
    plan = plan_of(make_task("a"))
    screen = render_dashboard(plan, [], width=100, height=24, proposed_revisions=2)
    assert "REVIEW 2 PROPOSAL(S)" in screen
    assert "SLEIPNIR  REVIEW" in screen


def test_dashboard_separates_codex_quota_and_does_not_count_stale_as_done():
    plan = plan_of(make_task("a"))
    task = plan.by_id["a"]
    now = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    record = AttemptFinished(
        run_id="run",
        task_id="a",
        attempt=1,
        spec_hash=task.spec_hash(),
        plan_revision=0,
        routing=RoutingDecision(
            tier_requested=Tier.CODE,
            tier_final=Tier.CODE,
            model="@cli-default",
            adapter=Adapter.CODEX,
        ),
        status=AttemptStatus.SUCCEEDED,
        started_at=now,
        ended_at=now,
        wall_time_s=0,
        usage=TokenUsage(input_tokens=120, output_tokens=30),
        cost=CostEstimate(
            billing_mode=BillingMode.SUBSCRIPTION,
            quota_pool="codex",
        ),
    )
    screen = render_dashboard(plan, [record], width=100, height=24, now=now)
    assert "claude 0 tok" in screen
    assert "codex 150 tok" in screen
    assert "SLEIPNIR  COMPLETE" in screen

    stale = render_dashboard(
        plan, [record], width=100, height=24, now=now, staled_at={"a": 1}
    )
    assert "0/1" in stale


def test_dashboard_strips_terminal_control_sequences_from_untrusted_text():
    plan = plan_of(make_task("a")).model_copy(
        update={"goal": "safe\x1b[2J\nforged dashboard"}
    )
    screen = render_dashboard(
        plan,
        [],
        width=100,
        height=24,
        activity="brain says\x1b[H\nowned",
    )
    assert "\x1b" not in screen
    assert "forged dashboard" in screen
    assert "brain says [H owned" in screen
