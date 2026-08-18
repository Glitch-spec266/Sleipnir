"""Budget governor: the only component allowed to refuse work.

It consults two scarce resources that do not convert into each other. A
subscription dispatch spends 5-hour window quota and ~no dollars; a metered
dispatch spends dollars and no window. A near-exhausted window must therefore
never block an OpenRouter call, and a blown dollar budget must never be
"solved" by picking a cheaper model — only a refusal actually stops spend.

## Why this does not simply read the true limit

Claude Code itself learns window utilisation from an authenticated endpoint
(``fetchUtilization: GET /api/oauth/usage``, buckets ``five_hour``,
``seven_day``, ``seven_day_opus``, ``seven_day_sonnet``). Reaching it needs the
OAuth credential the CLI holds, and Sleipnir's standing rule is that it never
touches provider credentials — the adapters shell out precisely so the secret
stays with the tool that owns it. So :class:`WindowSource` is a seam: the
default implementation estimates locally, and a credential-reading one can be
dropped in *if the operator decides that trade is acceptable*.

Locally the limit is therefore genuinely unknown, and the governor **must not
invent one**. A guessed limit is worse than no limit: it throttles a run that
had room, or clears one that did not, and there is no way to tell which. With no
limit it reports burn rate, allows the dispatch, and leans on the one
authoritative local signal that does exist — an observed HTTP 429.

## Measured facts this design rests on

From 2,760 real usage records on 2026-08-18:

* Deduplicating on ``requestId`` **halves** the totals (1,454 duplicates against
  1,328 retained). A governor without it believes it has spent twice what it has.
* Cache reads are 97.1% of all input, and a 1:1 versus price-weighted sum of the
  same corpus differs by **6.44x**. The 1:1 default over-estimates, which
  downshifts too eagerly rather than blowing the window — the safe direction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

from sleipnir.schema import (
    DOWNSHIFT_LADDER,
    BillingMode,
    BudgetSnapshot,
    CostEstimate,
    Task,
    Tier,
)

#: The subscription window Claude Code meters against.
WINDOW_HOURS = 5.0

#: Fraction of known headroom held back so a run has room to finish rather than
#: stopping one task short of done.
DEFAULT_RESERVE_FRACTION = 0.10


class Verdict(StrEnum):
    ALLOW = "allow"
    DOWNSHIFT = "downshift"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class GovernorDecision:
    verdict: Verdict
    tier: Tier
    reason: str
    snapshot: BudgetSnapshot

    @property
    def retryable_at_same_tier(self) -> bool:
        """A budget denial must never be retried at the tier that was denied.

        Retrying an identical call against an identical budget fails identically
        and burns a retry from the ladder for nothing.
        """
        return self.verdict is not Verdict.DENY


@dataclass(slots=True)
class GovernorConfig:
    window_hours: float = WINDOW_HOURS
    reserve_fraction: float = DEFAULT_RESERVE_FRACTION


class WindowSource(Protocol):
    """Where the governor's view of current consumption comes from."""

    def observe(self, now: datetime) -> BudgetSnapshot: ...


@dataclass(slots=True)
class StaticWindowSource:
    """A fixed reading. Used by tests and by callers that measure elsewhere."""

    window_start: datetime
    window_tokens_used: int = 0
    window_tokens_limit: int | None = None
    metered_spend_usd: float = 0.0
    metered_budget_usd: float | None = None
    parse_warnings: list[str] = field(default_factory=list)
    window_hours: float = WINDOW_HOURS

    def observe(self, now: datetime) -> BudgetSnapshot:
        return BudgetSnapshot(
            window_start=self.window_start,
            window_end=self.window_start + timedelta(hours=self.window_hours),
            observed_at=now,
            window_tokens_used=self.window_tokens_used,
            window_tokens_limit=self.window_tokens_limit,
            metered_spend_usd=self.metered_spend_usd,
            metered_budget_usd=self.metered_budget_usd,
            parse_warnings=list(self.parse_warnings),
        )


@dataclass(slots=True)
class TranscriptWindowSource:
    """Estimates window consumption from Claude Code's own transcripts.

    ``window_tokens_limit`` stays ``None`` unless the operator supplies one: the
    transcripts carry consumption but never the limit, and guessing it is the
    one thing this module refuses to do.
    """

    window_hours: float = WINDOW_HOURS
    window_tokens_limit: int | None = None
    metered_budget_usd: float | None = None
    cache_read_weight: float = 1.0
    transcript_root: object | None = None

    def observe(self, now: datetime) -> BudgetSnapshot:
        from sleipnir.usage import scan_default

        window_start = now - timedelta(hours=self.window_hours)
        scan = scan_default(since=window_start, root=self.transcript_root)
        return BudgetSnapshot(
            window_start=window_start,
            window_end=window_start + timedelta(hours=self.window_hours),
            observed_at=now,
            window_tokens_used=scan.window_tokens(
                cache_read_weight=self.cache_read_weight
            ),
            window_tokens_limit=self.window_tokens_limit,
            metered_budget_usd=self.metered_budget_usd,
            parse_warnings=list(scan.warnings[:10]),
        )


@dataclass(slots=True)
class Governor:
    config: GovernorConfig = field(default_factory=GovernorConfig)
    source: WindowSource = field(
        default_factory=lambda: TranscriptWindowSource()
    )
    _rate_limited_until: datetime | None = field(default=None, init=False)

    # -- ground truth -------------------------------------------------------

    def note_rate_limit(self, *, at: datetime, resets_at: datetime | None = None) -> None:
        """Record an observed HTTP 429.

        This is the only authoritative local signal that the window is spent, so
        it outranks any estimate. Observed in real transcripts as
        ``{"error": "rate_limit", "apiErrorStatus": 429}``.
        """
        self._rate_limited_until = resets_at or (
            at + timedelta(hours=self.config.window_hours)
        )

    def rate_limited_at(self, now: datetime) -> bool:
        return (
            self._rate_limited_until is not None
            and now < self._rate_limited_until
        )

    # -- the gate -----------------------------------------------------------

    def before_dispatch(
        self,
        task: Task,
        *,
        tier: Tier,
        attempt: int,
        estimate: CostEstimate,
        now: datetime | None = None,
    ) -> GovernorDecision:
        """Consulted at the ``Executor._launch`` seam, before anything is spent."""
        observed_at = now or datetime.now(estimate_tz(self.source))
        snapshot = self.source.observe(observed_at)

        if estimate.billing_mode is BillingMode.METERED:
            return self._judge_dollars(task, tier, estimate, snapshot)
        return self._judge_window(task, tier, estimate, snapshot, observed_at)

    # -- dollars ------------------------------------------------------------

    def _judge_dollars(
        self,
        task: Task,
        tier: Tier,
        estimate: CostEstimate,
        snapshot: BudgetSnapshot,
    ) -> GovernorDecision:
        budget = snapshot.metered_budget_usd
        if budget is None:
            return GovernorDecision(
                Verdict.ALLOW,
                tier,
                "metered dispatch; no dollar budget set, so nothing to enforce",
                snapshot,
            )
        projected = snapshot.metered_spend_usd + estimate.amount_usd
        if projected > budget:
            # Denied, not downshifted: a cheaper model still spends dollars, so
            # only refusing actually stops the bleeding.
            return GovernorDecision(
                Verdict.DENY,
                tier,
                f"metered budget exhausted: ${snapshot.metered_spend_usd:.4f} spent "
                f"+ ${estimate.amount_usd:.4f} projected > ${budget:.2f} budget. "
                "A cheaper tier still costs dollars, so this is a refusal.",
                snapshot,
            )
        return GovernorDecision(
            Verdict.ALLOW,
            tier,
            f"metered dispatch; ${projected:.4f} of ${budget:.2f} budget, "
            "consumes no window quota",
            snapshot,
        )

    # -- window -------------------------------------------------------------

    def _judge_window(
        self,
        task: Task,
        tier: Tier,
        estimate: CostEstimate,
        snapshot: BudgetSnapshot,
        now: datetime,
    ) -> GovernorDecision:
        if self.rate_limited_at(now):
            return self._step_down(
                task,
                tier,
                snapshot,
                f"observed rate limit (HTTP 429); window is spent until "
                f"{self._rate_limited_until:%H:%M}. This is ground truth and "
                "outranks any local estimate.",
            )

        headroom = snapshot.window_headroom_tokens
        if headroom is None:
            # The limit is genuinely unknown locally and must not be invented.
            return GovernorDecision(
                Verdict.ALLOW,
                tier,
                "window limit unknown (not derivable from transcripts); "
                f"burn rate {snapshot.burn_rate_tokens_per_hour:,.0f} tokens/hour, "
                f"{snapshot.window_tokens_used:,} used this window. "
                "Refusing to guess a limit.",
                snapshot,
            )

        usable = int(headroom * (1.0 - self.config.reserve_fraction))
        if estimate.window_tokens > usable:
            return self._step_down(
                task,
                tier,
                snapshot,
                f"projected {estimate.window_tokens:,} window tokens exceeds "
                f"usable headroom {usable:,} "
                f"({headroom:,} left, {self.config.reserve_fraction:.0%} reserved)",
            )

        return GovernorDecision(
            Verdict.ALLOW,
            tier,
            f"subscription dispatch; {estimate.window_tokens:,} of {usable:,} "
            "usable window tokens",
            snapshot,
        )

    def _step_down(
        self, task: Task, tier: Tier, snapshot: BudgetSnapshot, why: str
    ) -> GovernorDecision:
        """One rung down the ladder, or a refusal if there is no rung left."""
        if tier is Tier.LONGCTX:
            return GovernorDecision(
                Verdict.DENY,
                tier,
                f"{why}; longctx cannot be downshifted — a task that needs a large "
                "context window fails on correctness, not on cost, so this is a "
                "refusal rather than a cheaper model.",
                snapshot,
            )
        if tier not in DOWNSHIFT_LADDER:
            return GovernorDecision(
                Verdict.DENY, tier, f"{why}; tier {tier.value!r} has no ladder rung", snapshot
            )
        index = DOWNSHIFT_LADDER.index(tier)
        if index + 1 >= len(DOWNSHIFT_LADDER):
            return GovernorDecision(
                Verdict.DENY,
                tier,
                f"{why}; already at the cheapest tier ({tier.value}), "
                "nothing left to downshift to",
                snapshot,
            )
        return GovernorDecision(
            Verdict.DOWNSHIFT,
            DOWNSHIFT_LADDER[index + 1],
            f"{why}; downshifting {tier.value} -> {DOWNSHIFT_LADDER[index + 1].value}",
            snapshot,
        )


def estimate_tz(source: WindowSource):
    """Timezone for a default ``now``. Always UTC; kept explicit, never naive."""
    from datetime import UTC

    return UTC
