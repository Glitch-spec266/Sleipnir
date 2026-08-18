"""Phase 3 router tests.

The router turns a declared tier into a concrete model. Its job is narrow: a
human declares *capability* by putting a model in a tier's candidate list, and
the router decides *cost* among the candidates that can actually hold the task's
input. It never invents capability, and it never invents a price.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from test_schema import make_task

from sleipnir.pricing import build_price_book
from sleipnir.router import (
    Candidate,
    NoViableCandidate,
    RouterConfig,
    ScarceResource,
    TierRouter,
)
from sleipnir.schema import (
    Adapter,
    ArtifactRef,
    BillingMode,
    InputContract,
    Tier,
)

T0 = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)


def prices(**models: dict) -> object:
    """Price book from ``model_id -> {prompt, completion, context}`` per-token."""
    rows = []
    for model_id, spec in models.items():
        rows.append(
            {
                "id": model_id.replace("__", "/").replace("_", "-"),
                "pricing": {
                    "prompt": str(spec.get("prompt", 0.000001)),
                    "completion": str(spec.get("completion", 0.000002)),
                },
                "context_length": spec.get("context", 200_000),
            }
        )
    return build_price_book({"data": rows}, T0)


def cand(
    model: str,
    *,
    adapter: Adapter = Adapter.OPENROUTER,
    billing: BillingMode = BillingMode.METERED,
    fixed_window_tokens: int = 0,
    price_model: str | None = None,
) -> Candidate:
    return Candidate(
        adapter=adapter,
        model=model,
        billing_mode=billing,
        fixed_window_tokens=fixed_window_tokens,
        price_model=price_model,
    )


def router(candidates, book, *, scarce=ScarceResource.WINDOW) -> TierRouter:
    return TierRouter(
        prices=book,
        config=RouterConfig(candidates=candidates, scarce=scarce),
    )


# ---------------------------------------------------------------------------
# Resolution basics
# ---------------------------------------------------------------------------


def test_resolves_a_tier_to_its_only_candidate():
    book = prices(**{"vendor__only": {}})
    r = router({Tier.CODE: (cand("vendor/only"),)}, book)

    decision = r.resolve(make_task("t0"), attempt=1, tier=Tier.CODE)

    assert decision.model == "vendor/only"
    assert decision.adapter is Adapter.OPENROUTER
    assert decision.tier_requested is Tier.CODE
    assert decision.tier_final is Tier.CODE
    assert decision.candidates_considered == ["vendor/only"]
    assert decision.rationale


def test_tier_with_no_candidates_is_refused():
    book = prices(**{"vendor__a": {}})
    r = router({Tier.CODE: (cand("vendor/a"),)}, book)
    with pytest.raises(NoViableCandidate):
        r.resolve(make_task("t0"), attempt=1, tier=Tier.MECHANICAL)


def test_candidate_priced_by_a_model_absent_from_the_book_is_refused():
    """A missing price must never silently become zero — that is free-forever."""
    book = prices(**{"vendor__a": {}})
    r = router({Tier.CODE: (cand("vendor/ghost"),)}, book)
    with pytest.raises(NoViableCandidate) as excinfo:
        r.resolve(make_task("t0"), attempt=1, tier=Tier.CODE)
    assert "price" in str(excinfo.value).lower()


def test_price_model_is_used_for_costing_not_the_adapter_model():
    """`claude --model sonnet` is not a catalogue id; it must be priced by proxy."""
    book = prices(**{"anthropic__claude_sonnet_5": {"prompt": 0.000002}})
    r = router(
        {
            Tier.CODE: (
                cand(
                    "sonnet",
                    adapter=Adapter.CLAUDE,
                    billing=BillingMode.SUBSCRIPTION,
                    price_model="anthropic/claude-sonnet-5",
                ),
            )
        },
        book,
    )
    decision = r.resolve(make_task("t0"), attempt=1, tier=Tier.CODE)
    assert decision.model == "sonnet"  # what the adapter is handed


# ---------------------------------------------------------------------------
# The reason this phase exists: fixed per-dispatch cost
# ---------------------------------------------------------------------------


def test_fixed_spawn_cost_beats_a_cheaper_per_token_price_on_a_small_task():
    """A ~30k-token spawn floor can cost more than the whole task is worth.

    The CLI is cheaper per token here and must still lose, because the floor
    dominates for a task this small.
    """
    book = prices(
        **{
            "anthropic__claude_haiku_4_5": {"prompt": 0.0000001},
            "vendor__cheap": {"prompt": 0.000001},
        }
    )
    r = router(
        {
            Tier.MECHANICAL: (
                cand(
                    "haiku",
                    adapter=Adapter.CLAUDE,
                    billing=BillingMode.SUBSCRIPTION,
                    price_model="anthropic/claude-haiku-4.5",
                    fixed_window_tokens=30_000,
                ),
                cand("vendor/cheap"),
            )
        },
        book,
        scarce=ScarceResource.USD,
    )

    decision = r.resolve(make_task("t0"), attempt=1, tier=Tier.MECHANICAL)
    assert decision.model == "vendor/cheap"
    assert "fixed" in decision.rationale.lower()


def test_zero_fixed_cost_candidate_wins_when_window_is_the_scarce_resource():
    book = prices(
        **{
            "anthropic__claude_haiku_4_5": {"prompt": 0.0},
            "vendor__metered": {"prompt": 0.00001},
        }
    )
    r = router(
        {
            Tier.MECHANICAL: (
                cand(
                    "haiku",
                    adapter=Adapter.CLAUDE,
                    billing=BillingMode.SUBSCRIPTION,
                    price_model="anthropic/claude-haiku-4.5",
                    fixed_window_tokens=30_000,
                ),
                cand("vendor/metered"),
            )
        },
        book,
        scarce=ScarceResource.WINDOW,
    )
    decision = r.resolve(make_task("t0"), attempt=1, tier=Tier.MECHANICAL)
    # Metered spends no window at all, so under a window constraint it wins
    # even though it costs real dollars.
    assert decision.model == "vendor/metered"


def test_dollars_break_ties_when_window_cost_is_equal():
    book = prices(
        **{"vendor__pricey": {"prompt": 0.001}, "vendor__thrifty": {"prompt": 0.000001}}
    )
    r = router(
        {Tier.CODE: (cand("vendor/pricey"), cand("vendor/thrifty"))},
        book,
        scarce=ScarceResource.WINDOW,
    )
    decision = r.resolve(make_task("t0"), attempt=1, tier=Tier.CODE)
    assert decision.model == "vendor/thrifty"


# ---------------------------------------------------------------------------
# Fit: a candidate that cannot hold the input is not a candidate
# ---------------------------------------------------------------------------


def big_input_task(task_id: str, *, max_bytes: int):
    producer = make_task("dep")
    task = make_task(
        task_id,
        deps=["dep"],
        inputs=InputContract(
            summaries=[],
            max_input_bytes=max_bytes,
            artifacts=[
                ArtifactRef(
                    task_id="dep",
                    path="out.py",
                    max_bytes=max_bytes,
                    reason="needs the full generated module to refactor it",
                )
            ],
        ),
    )
    return producer, task


def test_candidate_whose_context_cannot_hold_the_input_is_excluded():
    _, task = big_input_task("t0", max_bytes=4_000_000)  # ~1.1M tokens
    book = prices(
        **{
            "vendor__small": {"prompt": 0.0000001, "context": 8_000},
            "vendor__huge": {"prompt": 0.00001, "context": 2_000_000},
        }
    )
    r = router(
        {Tier.LONGCTX: (cand("vendor/small"), cand("vendor/huge"))},
        book,
        scarce=ScarceResource.USD,
    )
    decision = r.resolve(task, attempt=1, tier=Tier.LONGCTX)
    assert decision.model == "vendor/huge"
    assert "vendor/small" in decision.candidates_considered


def test_no_candidate_fits_is_a_refusal_not_a_best_effort():
    _, task = big_input_task("t0", max_bytes=4_000_000)
    book = prices(**{"vendor__small": {"context": 8_000}})
    r = router({Tier.LONGCTX: (cand("vendor/small"),)}, book)
    with pytest.raises(NoViableCandidate) as excinfo:
        r.resolve(task, attempt=1, tier=Tier.LONGCTX)
    assert "context" in str(excinfo.value).lower()


def test_unknown_context_window_does_not_exclude_a_candidate():
    """Unknown is not the same as too small; refusing on absent data over-refuses."""
    _, task = big_input_task("t0", max_bytes=1_000_000)
    book = build_price_book(
        {
            "data": [
                {
                    "id": "vendor/unknown-ctx",
                    "pricing": {"prompt": "0.000001", "completion": "0.000002"},
                    "context_length": None,
                }
            ]
        },
        T0,
    )
    r = router({Tier.LONGCTX: (cand("vendor/unknown-ctx"),)}, book)
    decision = r.resolve(task, attempt=1, tier=Tier.LONGCTX)
    assert decision.model == "vendor/unknown-ctx"


# ---------------------------------------------------------------------------
# Attempt rotation: a retry must not repeat an identical failing call
# ---------------------------------------------------------------------------


def test_successive_attempts_rotate_through_candidates():
    """A free model can 429 while its neighbour answers instantly (observed live).

    Retrying the identical call would fail identically, so attempt N picks the
    Nth-cheapest candidate rather than the cheapest again.
    """
    book = prices(
        **{
            "vendor__a": {"prompt": 0.000001},
            "vendor__b": {"prompt": 0.000002},
            "vendor__c": {"prompt": 0.000003},
        }
    )
    r = router(
        {Tier.CODE: (cand("vendor/a"), cand("vendor/b"), cand("vendor/c"))},
        book,
        scarce=ScarceResource.USD,
    )
    task = make_task("t0")
    picks = [r.resolve(task, attempt=n, tier=Tier.CODE).model for n in (1, 2, 3, 4)]
    assert picks == ["vendor/a", "vendor/b", "vendor/c", "vendor/a"]


def test_rotation_only_covers_candidates_that_fit():
    _, task = big_input_task("t0", max_bytes=4_000_000)
    book = prices(
        **{
            "vendor__small": {"prompt": 0.0000001, "context": 8_000},
            "vendor__big1": {"prompt": 0.000001, "context": 2_000_000},
            "vendor__big2": {"prompt": 0.000002, "context": 2_000_000},
        }
    )
    r = router(
        {Tier.LONGCTX: (cand("vendor/small"), cand("vendor/big1"), cand("vendor/big2"))},
        book,
        scarce=ScarceResource.USD,
    )
    picks = [r.resolve(task, attempt=n, tier=Tier.LONGCTX).model for n in (1, 2, 3)]
    assert picks == ["vendor/big1", "vendor/big2", "vendor/big1"]


# ---------------------------------------------------------------------------
# Tier movement is recorded honestly
# ---------------------------------------------------------------------------


def test_a_downshift_records_that_it_happened_and_why():
    book = prices(**{"vendor__cheap": {}})
    r = router({Tier.MECHANICAL: (cand("vendor/cheap"),)}, book)
    task = make_task("t0", tier=Tier.REASON)

    decision = r.resolve(task, attempt=1, tier=Tier.MECHANICAL)

    assert decision.tier_requested is Tier.REASON
    assert decision.tier_final is Tier.MECHANICAL
    assert decision.downshifted is True
    assert decision.escalated is False
    assert decision.downshift_reason


def test_an_escalation_is_recorded_as_escalation_not_downshift():
    book = prices(**{"vendor__strong": {}})
    r = router({Tier.REASON: (cand("vendor/strong"),)}, book)
    task = make_task("t0", tier=Tier.MECHANICAL)

    decision = r.resolve(task, attempt=2, tier=Tier.REASON)

    assert decision.escalated is True
    assert decision.downshifted is False


def test_downshifting_a_longctx_task_is_refused():
    """Downshifting longctx is a correctness failure, not a cost decision.

    DOWNSHIFT_LADDER excludes longctx for this reason; the router enforces it.
    """
    book = prices(**{"vendor__cheap": {}})
    r = router({Tier.MECHANICAL: (cand("vendor/cheap"),)}, book)
    task = make_task("t0", tier=Tier.LONGCTX)

    with pytest.raises(NoViableCandidate) as excinfo:
        r.resolve(task, attempt=1, tier=Tier.MECHANICAL)
    assert "longctx" in str(excinfo.value).lower()


def test_same_tier_is_neither_downshift_nor_escalation():
    book = prices(**{"vendor__a": {}})
    r = router({Tier.CODE: (cand("vendor/a"),)}, book)
    decision = r.resolve(make_task("t0", tier=Tier.CODE), attempt=1, tier=Tier.CODE)
    assert decision.downshifted is False
    assert decision.escalated is False


# ---------------------------------------------------------------------------
# Explainability — `sleipnir explain` reads these fields
# ---------------------------------------------------------------------------


def test_candidates_considered_is_bounded_to_the_schema_cap():
    """RoutingDecision caps the list at 20; a big table must not blow validation."""
    models = {f"vendor__m{i:02d}": {"prompt": 0.000001 * (i + 1)} for i in range(30)}
    book = prices(**models)
    candidates = tuple(cand(f"vendor/m{i:02d}") for i in range(30))
    r = router({Tier.CODE: candidates}, book, scarce=ScarceResource.USD)

    decision = r.resolve(make_task("t0"), attempt=1, tier=Tier.CODE)
    assert len(decision.candidates_considered) <= 20
    assert decision.model == "vendor/m00"


def test_rationale_names_the_scarce_resource_being_optimised():
    book = prices(**{"vendor__a": {}})
    r = router({Tier.CODE: (cand("vendor/a"),)}, book, scarce=ScarceResource.WINDOW)
    decision = r.resolve(make_task("t0"), attempt=1, tier=Tier.CODE)
    assert "window" in decision.rationale.lower()


def test_stale_prices_are_surfaced_in_the_rationale():
    """A routing decision made on month-old prices must say so in the record."""
    book = prices(**{"vendor__a": {}})
    book.stale = True
    r = router({Tier.CODE: (cand("vendor/a"),)}, book)
    decision = r.resolve(make_task("t0"), attempt=1, tier=Tier.CODE)
    assert "stale" in decision.rationale.lower()


# ---------------------------------------------------------------------------
# The default table is a starting point, not an authority
# ---------------------------------------------------------------------------


def test_default_candidates_cover_every_tier():
    from sleipnir.router import DEFAULT_CANDIDATES

    assert set(DEFAULT_CANDIDATES) == set(Tier)
    for tier, candidates in DEFAULT_CANDIDATES.items():
        assert candidates, f"tier {tier} has no candidates"


def test_default_candidates_declare_a_spawn_floor_for_cli_adapters():
    """The ~30k-token floor is the whole reason mechanical work leaves the CLI."""
    from sleipnir.router import DEFAULT_CANDIDATES

    cli = [
        c
        for candidates in DEFAULT_CANDIDATES.values()
        for c in candidates
        if c.adapter in (Adapter.CLAUDE, Adapter.CODEX)
    ]
    assert cli
    assert all(c.fixed_window_tokens > 0 for c in cli)


def test_default_candidates_never_reference_openrouter_meta_models():
    """openrouter/auto and friends price at -1: cost unknowable before dispatch."""
    from sleipnir.router import DEFAULT_CANDIDATES

    for candidates in DEFAULT_CANDIDATES.values():
        for c in candidates:
            assert not (c.price_model or c.model).startswith("openrouter/")


# ---------------------------------------------------------------------------
# The executor must accept this in place of the Phase 2 placeholder
# ---------------------------------------------------------------------------


def test_executor_accepts_the_tier_router_in_place_of_static_router(tmp_path):
    """TierRouter satisfies executor.Router structurally, not just nominally."""
    from sleipnir.executor import Executor, ExecutorConfig
    from sleipnir.runlog import ResultLog
    from sleipnir.schema import Plan

    book = prices(**{"vendor__a": {}})
    r = router({t: (cand("vendor/a"),) for t in Tier}, book)
    plan = Plan(plan_id="p", goal="g", created_at=T0, tasks=[make_task("a")])

    executor = Executor(
        plan,
        adapters={},
        router=r,
        log=ResultLog(tmp_path / "r.jsonl"),
        config=ExecutorConfig(run_root=tmp_path, env={}),
    )
    decision = executor.router.resolve(plan.tasks[0], attempt=1, tier=Tier.CODE)
    assert decision.model == "vendor/a"
