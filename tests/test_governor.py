"""Phase 4 budget governor tests.

The governor is the only component allowed to refuse work. Its failure modes are
asymmetric: refusing a task that would have fitted wastes a little time, while
allowing one that blows the 5-hour window strands the whole run. So the tests
below lean on the safe side and, above all, pin the rule that it must never
invent a limit it does not know.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from test_schema import make_task

from sleipnir.governor import (
    Governor,
    GovernorConfig,
    StaticWindowSource,
    Verdict,
)
from sleipnir.schema import BillingMode, CostEstimate, Tier

T0 = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
WINDOW_START = T0 - timedelta(hours=1)


def source(*, used=0, limit=None, spend=0.0, budget=None, warnings=()):
    return StaticWindowSource(
        window_start=WINDOW_START,
        window_tokens_used=used,
        window_tokens_limit=limit,
        metered_spend_usd=spend,
        metered_budget_usd=budget,
        parse_warnings=list(warnings),
    )


def gov(src=None, **cfg) -> Governor:
    return Governor(config=GovernorConfig(**cfg), source=src or source())


def sub(window_tokens: int) -> CostEstimate:
    return CostEstimate(
        billing_mode=BillingMode.SUBSCRIPTION, window_tokens=window_tokens
    )


def metered(usd: float) -> CostEstimate:
    return CostEstimate(billing_mode=BillingMode.METERED, amount_usd=usd)


# ---------------------------------------------------------------------------
# The rule that matters most: never guess a limit
# ---------------------------------------------------------------------------


def test_unknown_window_limit_allows_and_never_invents_a_number():
    """A guessed limit is worse than no limit: it throttles or overruns at random.

    Claude Code reads real utilisation from an authenticated endpoint we
    deliberately do not touch, so locally the limit is genuinely unknown.
    """
    g = gov(source(used=500_000, limit=None))
    d = g.before_dispatch(make_task("t0"), tier=Tier.CODE, attempt=1, estimate=sub(10**9))

    assert d.verdict is Verdict.ALLOW
    assert d.snapshot.window_tokens_limit is None
    assert d.snapshot.window_headroom_tokens is None
    assert "unknown" in d.reason.lower()


def test_burn_rate_is_still_reported_when_the_limit_is_unknown():
    g = gov(source(used=360_000, limit=None))
    d = g.before_dispatch(
        make_task("t0"), tier=Tier.CODE, attempt=1, estimate=sub(1), now=T0
    )
    # 360,000 tokens over one elapsed hour. `now` must be pinned: without it the
    # governor reads the wall clock, which is correct behaviour but untestable.
    assert d.snapshot.burn_rate_tokens_per_hour == pytest.approx(360_000, rel=0.01)


# ---------------------------------------------------------------------------
# Window headroom
# ---------------------------------------------------------------------------


def test_a_dispatch_that_fits_is_allowed():
    g = gov(source(used=100_000, limit=1_000_000), reserve_fraction=0.0)
    d = g.before_dispatch(make_task("t0"), tier=Tier.CODE, attempt=1, estimate=sub(50_000))
    assert d.verdict is Verdict.ALLOW


def test_a_dispatch_that_would_exhaust_the_window_is_downshifted():
    g = gov(source(used=990_000, limit=1_000_000), reserve_fraction=0.0)
    d = g.before_dispatch(
        make_task("t0", tier=Tier.REASON), tier=Tier.REASON, attempt=1, estimate=sub(50_000)
    )
    assert d.verdict is Verdict.DOWNSHIFT
    assert d.tier is Tier.CODE  # one rung down the ladder
    assert d.reason


def test_downshift_walks_the_ladder_one_rung_at_a_time():
    g = gov(source(used=999_999, limit=1_000_000), reserve_fraction=0.0)
    for start, expected in [
        (Tier.REASON, Tier.CODE),
        (Tier.CODE, Tier.EXTRACT),
        (Tier.EXTRACT, Tier.MECHANICAL),
    ]:
        d = g.before_dispatch(
            make_task("t0", tier=start), tier=start, attempt=1, estimate=sub(50_000)
        )
        assert d.verdict is Verdict.DOWNSHIFT
        assert d.tier is expected


def test_the_cheapest_tier_cannot_be_downshifted_so_it_is_denied():
    g = gov(source(used=999_999, limit=1_000_000), reserve_fraction=0.0)
    d = g.before_dispatch(
        make_task("t0", tier=Tier.MECHANICAL),
        tier=Tier.MECHANICAL,
        attempt=1,
        estimate=sub(50_000),
    )
    assert d.verdict is Verdict.DENY


def test_longctx_is_denied_rather_than_downshifted():
    """Downshifting longctx is a correctness failure, not a saving.

    DOWNSHIFT_LADDER excludes it; the governor must not route around that.
    """
    g = gov(source(used=999_999, limit=1_000_000), reserve_fraction=0.0)
    d = g.before_dispatch(
        make_task("t0", tier=Tier.LONGCTX),
        tier=Tier.LONGCTX,
        attempt=1,
        estimate=sub(50_000),
    )
    assert d.verdict is Verdict.DENY
    assert "longctx" in d.reason.lower()


def test_a_reserve_fraction_is_held_back():
    """Headroom is not spent to the last token; a run needs room to finish."""
    lenient = gov(source(used=800_000, limit=1_000_000), reserve_fraction=0.0)
    strict = gov(source(used=800_000, limit=1_000_000), reserve_fraction=0.5)
    est = sub(150_000)
    assert lenient.before_dispatch(make_task("t"), tier=Tier.CODE, attempt=1, estimate=est).verdict is Verdict.ALLOW
    assert strict.before_dispatch(make_task("t"), tier=Tier.CODE, attempt=1, estimate=est).verdict is Verdict.DOWNSHIFT


# ---------------------------------------------------------------------------
# Metered dollars are a separate resource
# ---------------------------------------------------------------------------


def test_a_metered_call_does_not_consume_window_headroom():
    """The two resources do not convert. A near-full window must not block
    an OpenRouter call that spends no window at all."""
    g = gov(source(used=999_999, limit=1_000_000), reserve_fraction=0.0)
    d = g.before_dispatch(make_task("t0"), tier=Tier.CODE, attempt=1, estimate=metered(0.01))
    assert d.verdict is Verdict.ALLOW


def test_exceeding_the_dollar_budget_is_denied_not_downshifted():
    """A cheaper model still costs dollars. Only a refusal actually stops spend."""
    g = gov(source(spend=9.99, budget=10.0))
    d = g.before_dispatch(make_task("t0"), tier=Tier.REASON, attempt=1, estimate=metered(5.0))
    assert d.verdict is Verdict.DENY
    assert "budget" in d.reason.lower()


def test_an_unset_dollar_budget_never_denies():
    g = gov(source(spend=1_000.0, budget=None))
    d = g.before_dispatch(make_task("t0"), tier=Tier.CODE, attempt=1, estimate=metered(5.0))
    assert d.verdict is Verdict.ALLOW


# ---------------------------------------------------------------------------
# The 429 is ground truth
# ---------------------------------------------------------------------------


def test_an_observed_rate_limit_stops_subscription_dispatch():
    """Observed live: rate limits surface as apiErrorStatus 429, error rate_limit.

    That is the only authoritative "you are out" signal available locally, so it
    outranks any local estimate.
    """
    g = gov(source(limit=None))
    g.note_rate_limit(at=T0, resets_at=T0 + timedelta(minutes=30))
    d = g.before_dispatch(
        make_task("t0"), tier=Tier.CODE, attempt=1, estimate=sub(1), now=T0
    )
    assert d.verdict is Verdict.DOWNSHIFT
    assert "rate limit" in d.reason.lower()


def test_a_rate_limit_does_not_block_metered_dispatch():
    """The window is exhausted; dollars are not. OpenRouter is unaffected."""
    g = gov(source(limit=None))
    g.note_rate_limit(at=T0, resets_at=T0 + timedelta(minutes=30))
    d = g.before_dispatch(
        make_task("t0"), tier=Tier.CODE, attempt=1, estimate=metered(0.01), now=T0
    )
    assert d.verdict is Verdict.ALLOW


def test_a_rate_limit_expires_at_its_reset_time():
    g = gov(source(limit=None))
    g.note_rate_limit(at=T0, resets_at=T0 + timedelta(minutes=30))
    later = T0 + timedelta(minutes=31)
    d = g.before_dispatch(
        make_task("t0"), tier=Tier.CODE, attempt=1, estimate=sub(1), now=later
    )
    assert d.verdict is Verdict.ALLOW


# ---------------------------------------------------------------------------
# Honesty
# ---------------------------------------------------------------------------


def test_parse_warnings_reach_the_snapshot():
    """A silently wrong budget is worse than no budget — surface, never swallow."""
    g = gov(source(warnings=["unrecognised usage field 'new_channel'"]))
    d = g.before_dispatch(make_task("t0"), tier=Tier.CODE, attempt=1, estimate=sub(1))
    assert d.snapshot.parse_warnings == ["unrecognised usage field 'new_channel'"]


def test_every_decision_carries_a_reason():
    g = gov(source(used=10, limit=1_000_000))
    for est in (sub(1), metered(0.01)):
        d = g.before_dispatch(make_task("t0"), tier=Tier.CODE, attempt=1, estimate=est)
        assert d.reason.strip()


def test_a_denial_is_never_silently_retryable_at_the_same_tier():
    """FailureKind.BUDGET_DENIED must not be retried at the tier that was denied."""
    g = gov(source(spend=100.0, budget=1.0))
    d = g.before_dispatch(make_task("t0"), tier=Tier.CODE, attempt=1, estimate=metered(1.0))
    assert d.verdict is Verdict.DENY
    assert d.retryable_at_same_tier is False
