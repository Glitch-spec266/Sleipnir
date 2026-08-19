"""Phase 1 schema tests.

The load-bearing test is `test_manifest_size_is_constant_in_task_count`: it is
the executable form of the size math in DESIGN.md. If a later phase adds a
field that reintroduces O(n) growth, that test fails.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from sleipnir.projection import build_manifest, fold_results
from sleipnir.schema import (
    DEFAULT_CAPS,
    AttemptFinished,
    AttemptStarted,
    AttemptStatus,
    BillingMode,
    BudgetSnapshot,
    CostEstimate,
    ExpectedOutput,
    FailureKind,
    FileExistsCheck,
    InputContract,
    ArtifactRef,
    OutputContract,
    OutputKind,
    Plan,
    PriceSnapshot,
    ProducedArtifact,
    RetryPolicy,
    RoutingDecision,
    Adapter,
    Task,
    TaskStatus,
    Tier,
    TokenUsage,
)

T0 = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def make_task(task_id: str, *, deps: list[str] | None = None, **kwargs) -> Task:
    deps = deps or []
    defaults = dict(
        id=task_id,
        description=f"Implement the {task_id} component against the agreed spec.",
        tier=Tier.CODE,
        depends_on=deps,
        inputs=InputContract(summaries=list(deps)),
        outputs=OutputContract(
            outputs=[
                ExpectedOutput(
                    name="result",
                    kind=OutputKind.FILE,
                    path="out.py",
                    description=f"Output of {task_id}.",
                )
            ]
        ),
    )
    defaults.update(kwargs)
    return Task(**defaults)


@pytest.mark.parametrize("path", ["../secret", "a/../../secret", "/etc/passwd"])
def test_repository_input_paths_cannot_escape_the_run_root(path: str):
    with pytest.raises(ValueError, match="must not escape|relative"):
        InputContract(files=[path])


@pytest.mark.parametrize(
    "path",
    ["summary.md", "prompt.txt", "stdout.log", "stderr.log", ".checks/result.out"],
)
def test_outputs_cannot_overwrite_harness_owned_files(path: str):
    with pytest.raises(ValueError, match="harness-owned"):
        ExpectedOutput(
            name="result",
            kind=OutputKind.FILE,
            path=path,
            description="A result that must not collide with harness state.",
        )


def _plan(tasks: list[Task]) -> Plan:
    return Plan(
        plan_id="demo",
        goal="Build a budget-aware orchestrator end to end.",
        created_at=T0,
        tasks=tasks,
    )


def make_chain(n: int) -> Plan:
    """t0000 -> t0001 -> ... Simple shape for status-folding tests."""
    return _plan(
        [make_task(f"t{i:04d}", deps=[f"t{i - 1:04d}"] if i else []) for i in range(n)]
    )


LAYER_SIZE = 20


def make_layered(n: int, *, groups: int = 4) -> Plan:
    """A wide layered DAG: every task in layer k depends on three in layer k-1.

    This is the shape that puts maximum pressure on the manifest caps — a whole
    layer goes READY at once (saturating the frontier) and each of those tasks
    drags in completed dependencies. The strides are coprime-ish with the layer
    width so that neighbouring tasks do not share the same dependency set;
    otherwise the evidence list never fills and the cap goes untested.
    """
    tasks: list[Task] = []
    for i in range(n):
        layer = i // LAYER_SIZE
        deps: list[str] = []
        if layer:
            start = (layer - 1) * LAYER_SIZE
            width = min(layer * LAYER_SIZE, n) - start
            deps = sorted({f"t{start + (i + k) % width:04d}" for k in (0, 5, 11)})
        tasks.append(make_task(f"t{i:04d}", deps=deps, group=f"g{i % groups:02d}"))
    return _plan(tasks)


def routing(tier: Tier = Tier.CODE) -> RoutingDecision:
    return RoutingDecision(
        tier_requested=tier,
        tier_final=tier,
        model="vendor/some-model",
        adapter=Adapter.OPENROUTER,
        rationale="cheapest model meeting the tier's context requirement",
    )


def finished(
    task_id: str,
    *,
    attempt: int = 1,
    status: AttemptStatus = AttemptStatus.SUCCEEDED,
    spec_hash: str,
    summary: str = "Wrote out.py; all acceptance checks passed.",
    failure_kind: FailureKind | None = None,
    missing: list[str] | None = None,
) -> AttemptFinished:
    return AttemptFinished(
        run_id="run-1",
        task_id=task_id,
        attempt=attempt,
        spec_hash=spec_hash,
        plan_revision=0,
        routing=routing(),
        status=status,
        failure_kind=failure_kind,
        missing_outputs=missing or [],
        started_at=T0,
        ended_at=T0 + timedelta(seconds=42),
        wall_time_s=42.0,
        usage=TokenUsage(input_tokens=10, output_tokens=500, cache_write_1h_tokens=20_000),
        cost=CostEstimate(billing_mode=BillingMode.METERED, amount_usd=0.12),
        artifacts=[ProducedArtifact(name="result", path="artifacts/task-x/attempt-01/out.py", bytes=100)],
        summary=summary,
    )


def budget() -> BudgetSnapshot:
    return BudgetSnapshot(
        window_start=T0 - timedelta(hours=1),
        window_end=T0 + timedelta(hours=4),
        observed_at=T0,
        window_tokens_used=120_000,
        window_tokens_limit=1_000_000,
        metered_spend_usd=1.5,
        projected_plan_cost_usd=3.0,
        projected_plan_window_tokens=200_000,
    )


# ---------------------------------------------------------------------------
# DAG validation
# ---------------------------------------------------------------------------


def test_plan_rejects_dependency_cycle():
    a = make_task("a", deps=["b"])
    b = make_task("b", deps=["a"])
    with pytest.raises(ValidationError, match="cycle"):
        Plan(plan_id="p", goal="g", created_at=T0, tasks=[a, b])


def test_plan_rejects_unknown_dependency():
    with pytest.raises(ValidationError, match="unknown task"):
        Plan(plan_id="p", goal="g", created_at=T0, tasks=[make_task("a", deps=["ghost"])])


def test_plan_rejects_duplicate_task_ids():
    with pytest.raises(ValidationError, match="duplicate task id"):
        Plan(plan_id="p", goal="g", created_at=T0, tasks=[make_task("a"), make_task("a")])


def test_task_cannot_read_from_undeclared_dependency():
    with pytest.raises(ValidationError, match="does not declare it in depends_on"):
        make_task("b", deps=[], inputs=InputContract(summaries=["a"]))


def test_artifact_ref_must_name_a_real_output():
    producer = make_task("a")
    consumer = make_task(
        "b",
        deps=["a"],
        inputs=InputContract(
            artifacts=[
                ArtifactRef(
                    task_id="a",
                    path="nope.py",
                    reason="needs the full implementation to refactor it faithfully",
                )
            ]
        ),
    )
    with pytest.raises(ValidationError, match="declares no such output"):
        Plan(plan_id="p", goal="g", created_at=T0, tasks=[producer, consumer])


def test_artifact_ref_rejects_wildcard_everything():
    with pytest.raises(ValidationError, match="wildcard-everything"):
        ArtifactRef(task_id="a", path="**", reason="I want absolutely everything please")


def test_artifact_ref_rejects_path_escape():
    with pytest.raises(ValidationError, match="escape upward"):
        ArtifactRef(task_id="a", path="../../etc/passwd", reason="entirely legitimate use")


def test_artifact_budget_must_fit_max_input_bytes():
    with pytest.raises(ValidationError, match="max_input_bytes"):
        InputContract(
            summaries=[],
            artifacts=[
                ArtifactRef(
                    task_id="a", path="big.bin", reason="needs the whole corpus verbatim", max_bytes=10_000
                )
            ],
            max_input_bytes=1_000,
        )


def test_topological_order_respects_dependencies():
    plan = make_chain(5)
    order = plan.topological_order()
    assert order == [f"t{i:04d}" for i in range(5)]


def test_descendants_are_transitive():
    plan = make_chain(4)
    assert plan.descendants("t0000") == {"t0001", "t0002", "t0003"}


# ---------------------------------------------------------------------------
# spec_hash / revision semantics  (DESIGN.md Q3)
# ---------------------------------------------------------------------------


def test_spec_hash_ignores_routing_fields():
    """Re-tiering a task must NOT invalidate its completed work."""
    base = make_task("a")
    retiered = base.model_copy(update={"tier": Tier.MECHANICAL, "priority": 9, "timeout_s": 60})
    assert base.spec_hash() == retiered.spec_hash()


def test_spec_hash_changes_with_semantic_fields():
    base = make_task("a")
    respecced = base.model_copy(update={"description": "Something materially different now."})
    assert base.spec_hash() != respecced.spec_hash()


def test_spec_hash_is_stable_across_reserialization():
    task = make_task("a")
    assert task.spec_hash() == Task.model_validate(task.model_dump(mode="json")).spec_hash()


def test_completed_task_is_superseded_when_spec_changes():
    plan = make_chain(2)
    records = [finished("t0000", spec_hash="stale-hash-value")]
    states = fold_results(plan, records)
    assert states["t0000"].status is TaskStatus.SUPERSEDED
    assert states["t0000"].spec_mismatch


# ---------------------------------------------------------------------------
# Result record invariants  (DESIGN.md Q2)
# ---------------------------------------------------------------------------


def test_succeeded_attempt_cannot_have_missing_outputs():
    with pytest.raises(ValidationError, match="use status=partial"):
        finished("a", spec_hash="h", missing=["result"])


def test_failed_attempt_requires_a_failure_kind():
    with pytest.raises(ValidationError, match="requires a failure_kind"):
        finished("a", spec_hash="h", status=AttemptStatus.FAILED)


def test_partial_attempt_with_no_artifacts_is_a_failure():
    with pytest.raises(ValidationError, match="that is status=failed"):
        AttemptFinished(
            run_id="r", task_id="a", attempt=1, spec_hash="h", plan_revision=0,
            routing=routing(), status=AttemptStatus.PARTIAL,
            failure_kind=FailureKind.TRUNCATED,
            started_at=T0, ended_at=T0, wall_time_s=0.0,
            cost=CostEstimate(billing_mode=BillingMode.METERED),
            artifacts=[],
        )


def test_summary_is_hard_capped():
    with pytest.raises(ValidationError, match="~200 tokens"):
        finished("a", spec_hash="h", summary="x" * 721)


def test_partial_status_survives_when_retries_are_exhausted():
    plan = make_chain(1)
    task = plan.tasks[0]
    records = [
        finished(
            task.id, attempt=i, spec_hash=task.spec_hash(),
            status=AttemptStatus.PARTIAL, failure_kind=FailureKind.TRUNCATED,
        )
        for i in (1, 2)
    ]
    assert fold_results(plan, records)[task.id].status is TaskStatus.PARTIAL


def test_partial_becomes_ready_again_while_retries_remain():
    plan = make_chain(1)
    task = plan.tasks[0]
    records = [
        finished(
            task.id, attempt=1, spec_hash=task.spec_hash(),
            status=AttemptStatus.PARTIAL, failure_kind=FailureKind.TRUNCATED,
        )
    ]
    assert fold_results(plan, records)[task.id].status is TaskStatus.READY


def test_retry_policy_rejects_non_retryable_kinds():
    with pytest.raises(ValidationError, match="non-retryable"):
        RetryPolicy(retry_on=[FailureKind.BUDGET_DENIED])


def test_escalation_ladder_cannot_exceed_retries():
    with pytest.raises(ValidationError, match="longer than the number of retries"):
        RetryPolicy(max_attempts=1, escalation=[{"tier": Tier.REASON}])


def test_tier_for_attempt_walks_the_ladder():
    policy = RetryPolicy(max_attempts=3, escalation=[{"tier": Tier.CODE}, {"tier": Tier.REASON}])
    assert policy.tier_for_attempt(Tier.MECHANICAL, 1) is Tier.MECHANICAL
    assert policy.tier_for_attempt(Tier.MECHANICAL, 2) is Tier.CODE
    assert policy.tier_for_attempt(Tier.MECHANICAL, 3) is Tier.REASON


def test_downshift_must_be_explained():
    with pytest.raises(ValidationError, match="record why"):
        RoutingDecision(
            tier_requested=Tier.REASON, tier_final=Tier.CODE, model="m",
            adapter=Adapter.CLAUDE, downshifted=True,
        )


# ---------------------------------------------------------------------------
# Crash recovery  (DESIGN.md Q4)
# ---------------------------------------------------------------------------


def test_started_without_finished_is_running():
    plan = make_chain(2)
    records = [
        AttemptStarted(
            run_id="r", task_id="t0000", attempt=1,
            spec_hash=plan.tasks[0].spec_hash(), plan_revision=0,
            routing=routing(), started_at=T0,
        )
    ]
    states = fold_results(plan, records)
    assert states["t0000"].status is TaskStatus.RUNNING
    assert states["t0000"].open_attempt == 1
    # Downstream work stays blocked rather than racing the in-flight task.
    assert states["t0001"].status is TaskStatus.BLOCKED


def test_fold_is_idempotent_over_replayed_records():
    """Replaying the log must not double-count cost — recovery depends on it."""
    plan = make_chain(1)
    record = finished(plan.tasks[0].id, spec_hash=plan.tasks[0].spec_hash())
    once = fold_results(plan, [record])
    twice = fold_results(plan, [record, record])
    assert once[plan.tasks[0].id].cost_usd == twice[plan.tasks[0].id].cost_usd


def test_attempt_directories_never_collide():
    task = make_task("a")
    assert task.attempt_dir(1) != task.attempt_dir(2)
    assert task.attempt_dir(1).startswith(task.artifact_dir)


def test_failed_dependency_skips_dependents():
    plan = make_chain(3)
    head = plan.tasks[0]
    records = [
        finished(
            head.id, attempt=i, spec_hash=head.spec_hash(),
            status=AttemptStatus.FAILED, failure_kind=FailureKind.PROVIDER_ERROR,
        )
        for i in (1, 2)
    ]
    states = fold_results(plan, records)
    assert states["t0000"].status is TaskStatus.FAILED
    assert states["t0001"].status is TaskStatus.SKIPPED


# ---------------------------------------------------------------------------
# Token accounting — shaped to the real usage record
# ---------------------------------------------------------------------------


def test_total_input_counts_cache_creation_tokens():
    """The trap found in the real ~/.claude/projects record: input_tokens=2
    while cache_creation_input_tokens=47052."""
    usage = TokenUsage(input_tokens=2, cache_write_1h_tokens=47_052, output_tokens=901)
    assert usage.total_input_tokens == 47_054
    assert usage.input_tokens != usage.total_input_tokens


def test_cache_write_ttls_are_priced_separately():
    price = PriceSnapshot(
        source="test", fetched_at=T0, model="m",
        input_per_mtok=3.0, output_per_mtok=15.0,
        cache_read_per_mtok=0.3, cache_write_5m_per_mtok=3.75, cache_write_1h_per_mtok=6.0,
    )
    five_min = TokenUsage(cache_write_5m_tokens=1_000_000)
    one_hour = TokenUsage(cache_write_1h_tokens=1_000_000)
    assert price.cost_usd(five_min) == pytest.approx(3.75)
    assert price.cost_usd(one_hour) == pytest.approx(6.0)


def test_missing_cache_prices_fall_back_without_undercounting():
    price = PriceSnapshot(source="test", fetched_at=T0, model="m", input_per_mtok=3.0, output_per_mtok=15.0)
    assert price.cost_usd(TokenUsage(cache_read_tokens=1_000_000)) == pytest.approx(3.0)


def test_thinking_tokens_cannot_exceed_output():
    with pytest.raises(ValidationError, match="cannot exceed output_tokens"):
        TokenUsage(output_tokens=10, thinking_tokens=11)


def test_metered_calls_do_not_consume_the_window():
    with pytest.raises(ValidationError, match="do not consume the subscription window"):
        CostEstimate(billing_mode=BillingMode.METERED, window_tokens=100)


def test_budget_headroom_is_none_when_limit_unknown():
    snapshot = budget().model_copy(update={"window_tokens_limit": None})
    assert snapshot.window_headroom_tokens is None
    assert snapshot.will_exhaust_window is False


def test_burn_rate_and_exhaustion():
    snapshot = budget()
    assert snapshot.burn_rate_tokens_per_hour == pytest.approx(120_000.0)
    assert snapshot.window_headroom_tokens == 880_000
    assert snapshot.will_exhaust_window is False
    hungry = snapshot.model_copy(update={"projected_plan_window_tokens": 2_000_000})
    assert hungry.will_exhaust_window is True


# ---------------------------------------------------------------------------
# The manifest bound — the executable form of the size math
# ---------------------------------------------------------------------------


def _manifest_for(n: int, *, groups: int = 4):
    """Manifest for a layered plan with every layer but the last two completed.

    Structural pressure is therefore identical at every n: one full layer is
    READY, one is BLOCKED, and all the rest is completed bulk. Only the size of
    that completed bulk varies — which is exactly the thing the manifest is
    supposed to be insensitive to.
    """
    plan = make_layered(n, groups=groups)
    layers = -(-n // LAYER_SIZE)
    cutoff = max(0, layers - 2) * LAYER_SIZE
    records = [
        finished(
            task.id,
            spec_hash=task.spec_hash(),
            summary="Completed the unit and wrote out.py. " * 12,
        )
        for task in plan.tasks[:cutoff]
    ]
    return build_manifest(plan, records, budget(), generated_at=T0)


def test_manifest_size_is_constant_in_task_count():
    """This is the whole design in one assertion.

    A 600-task run must not cost the orchestrator meaningfully more context per
    cycle than a 20-task run. If this fails, delegation has stopped paying for
    itself.
    """
    small = _manifest_for(60).estimate_tokens()
    large = _manifest_for(2000).estimate_tokens()
    growth = (large - small) / small
    assert growth < 0.05, f"manifest grew {growth:.1%} from 60 to 2000 tasks"
    assert large < DEFAULT_CAPS.hard_token_ceiling, f"{large} tokens exceeds ceiling"


@pytest.mark.parametrize("n", [1, 5, 20, 60, 200, 600, 2000])
def test_manifest_never_exceeds_the_ceiling(n: int):
    assert _manifest_for(n).estimate_tokens() < DEFAULT_CAPS.hard_token_ceiling


def test_manifest_caps_are_enforced_not_merely_documented():
    manifest = _manifest_for(600, groups=25)
    # Frontier and evidence must both be saturated, or this proves nothing.
    assert len(manifest.frontier) == DEFAULT_CAPS.max_frontier
    assert len(manifest.evidence) == DEFAULT_CAPS.max_evidence
    assert len(manifest.frontier) <= DEFAULT_CAPS.max_frontier
    assert len(manifest.evidence) <= DEFAULT_CAPS.max_evidence
    assert len(manifest.groups) <= DEFAULT_CAPS.max_groups
    assert len(manifest.alerts) <= DEFAULT_CAPS.max_alerts


def test_manifest_reports_when_it_elided_content():
    """The orchestrator must never infer completeness from silence."""
    manifest = _manifest_for(600)
    assert manifest.truncation_note is not None
    assert "beyond frontier cap" in manifest.truncation_note


def test_small_manifest_hides_nothing():
    manifest = _manifest_for(5)
    assert manifest.truncation_note is None


def test_manifest_carries_no_artifact_contents():
    """Paths may cross into the manifest. Bytes may not."""
    manifest = _manifest_for(60)
    rendered = manifest.render()
    for item in manifest.evidence:
        for path in item.artifact_paths:
            assert path in rendered
    assert len(rendered) < 20_000


def test_manifest_totals_track_the_fold():
    manifest = _manifest_for(60, groups=1)
    assert manifest.totals.tasks == 60
    assert manifest.totals.done == 20  # layer 0 complete; layers 1 and 2 outstanding
    assert manifest.totals.attempts_logged == 20
    assert manifest.totals.remaining == 40
