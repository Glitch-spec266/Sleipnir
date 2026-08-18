"""Tier -> concrete model.

The split this module enforces: **a human declares capability, the machine
decides cost.** Putting a model in a tier's candidate list is a claim that it can
do that class of work — nothing in the price catalogue can establish that, and
the router never tries to infer it. Among candidates already declared capable,
the router picks on price and on whether the model can physically hold the
task's declared input.

Two facts from Phase 2's live measurements drive the scoring:

* **Every CLI spawn costs a fixed floor** — about 30k cache-creation tokens
  before any work happens, measured at $0.0404 on Haiku 4.5 and $0.2022 on
  Opus 5 at current prices. For a small task that floor is the whole bill, so
  it is scored as a first-class term rather than folded into a per-token rate.
* **Dollars and window quota do not convert.** A subscription CLI call spends
  window and ~no dollars; an OpenRouter call spends dollars and no window. The
  caller names which resource is scarce, and the other is only a tie-breaker.

``resolve`` also uses its ``attempt`` argument, which the Phase 2 placeholder
ignored: attempt *n* takes the *n*-th cheapest viable candidate. A live test
found one free model returning HTTP 429 while its neighbour answered instantly,
so a retry that repeats the identical call fails identically. Rotating makes a
retry a genuinely different attempt for free.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping, Sequence

from sleipnir.pricing import PriceBook
from sleipnir.schema import (
    Adapter,
    BillingMode,
    RoutingDecision,
    Task,
    Tier,
    TokenUsage,
)

#: Matches ``schema.estimate_tokens``: conservative, over-estimates, no
#: tokenizer dependency. Over-estimating input size makes the fit check
#: pessimistic, which is the safe direction — it excludes a model that might
#: just barely have fitted rather than overflowing one mid-dispatch.
BYTES_PER_TOKEN = 3.6

#: Headroom for the prompt scaffolding ``context.py`` wraps around inputs
#: (task description, dependency summaries, output contract, check descriptions).
PROMPT_OVERHEAD_TOKENS = 4_000

#: Assumed output size when scoring. Output is priced several times higher than
#: input, so a candidate's ranking is sensitive to it; this is deliberately
#: generous rather than optimistic.
ASSUMED_OUTPUT_TOKENS = 8_000

#: Observed floor for a ``claude -p`` spawn: cache-creation tokens burned before
#: the subagent does any work. Measured in Phase 2's live smoke run.
CLI_SPAWN_FLOOR_TOKENS = 30_000

#: RoutingDecision.candidates_considered is capped at 20 by the schema.
MAX_CANDIDATES_RECORDED = 20


class NoViableCandidate(RuntimeError):
    """No declared candidate can run this task.

    Always raised rather than falling back to a best-effort pick. A router that
    quietly returns an unpriced or too-small model produces a dispatch that
    fails late and expensively, after the attempt directory and the log record
    already exist.
    """


class ScarceResource(StrEnum):
    """Which budget the router optimises. The other one breaks ties."""

    WINDOW = "window"  # subscription quota — the constraint on a Claude plan
    USD = "usd"  # metered spend — the constraint on API-key billing


@dataclass(frozen=True, slots=True)
class Candidate:
    """One concrete way to run a task at some tier.

    ``model`` is what the adapter is handed; ``price_model`` is the catalogue id
    used to cost it. They differ for the CLIs, where ``claude --model sonnet``
    takes an alias that does not appear in any price catalogue.
    """

    adapter: Adapter
    model: str
    billing_mode: BillingMode
    #: Tokens burned per dispatch before any work happens. Nonzero for the CLIs.
    fixed_window_tokens: int = 0
    #: Catalogue id for pricing. Defaults to ``model``.
    price_model: str | None = None
    #: Overrides the catalogue's context length when it is known to be wrong.
    context_window: int | None = None
    note: str = ""

    @property
    def priced_as(self) -> str:
        return self.price_model or self.model


@dataclass(slots=True)
class RouterConfig:
    candidates: Mapping[Tier, Sequence[Candidate]]
    scarce: ScarceResource = ScarceResource.WINDOW
    assumed_output_tokens: int = ASSUMED_OUTPUT_TOKENS
    prompt_overhead_tokens: int = PROMPT_OVERHEAD_TOKENS


@dataclass(frozen=True, slots=True)
class _Scored:
    candidate: Candidate
    window_tokens: int
    usd: float
    context_window: int | None

    def key(self, scarce: ScarceResource) -> tuple[float, float]:
        if scarce is ScarceResource.WINDOW:
            return (self.window_tokens, self.usd)
        return (self.usd, self.window_tokens)


@dataclass(slots=True)
class TierRouter:
    """The real Phase 3 router. Replaces ``executor.StaticRouter``."""

    prices: PriceBook
    config: RouterConfig
    _rejections: list[str] = field(default_factory=list, init=False, repr=False)

    # -- public API ---------------------------------------------------------

    def resolve(self, task: Task, *, attempt: int, tier: Tier) -> RoutingDecision:
        self._guard_tier_movement(task, tier)

        declared = self._input_tokens(task)
        candidates = tuple(self.config.candidates.get(tier, ()))
        if not candidates:
            raise NoViableCandidate(
                f"tier {tier.value!r} has no candidates configured; "
                f"task {task.id!r} cannot be routed"
            )

        rejections: list[str] = []
        viable: list[_Scored] = []
        rejected_models: list[str] = []
        for candidate in candidates:
            before = len(rejections)
            scored = self._score(candidate, declared, rejections)
            if scored is not None:
                viable.append(scored)
            elif len(rejections) > before:
                rejected_models.append(candidate.model)

        if not viable:
            raise NoViableCandidate(
                f"no viable candidate for task {task.id!r} at tier {tier.value!r} "
                f"(needs ~{declared:,} input tokens): " + "; ".join(rejections)
            )

        viable.sort(key=lambda s: s.key(self.config.scarce))
        chosen = viable[(max(attempt, 1) - 1) % len(viable)]

        return RoutingDecision(
            tier_requested=task.tier,
            tier_final=tier,
            model=chosen.candidate.model,
            adapter=chosen.candidate.adapter,
            downshifted=self._is_downshift(task.tier, tier),
            escalated=self._is_escalation(task.tier, tier),
            downshift_reason=(
                f"governor moved {task.tier.value} -> {tier.value}"
                if self._is_downshift(task.tier, tier)
                else None
            ),
            # Everything examined, not just what survived: `sleipnir explain`
            # needs to show what was ruled out, and the rationale carries why.
            # Viable first, in score order, so a truncated list keeps the models
            # that were actually in the running.
            candidates_considered=(
                [s.candidate.model for s in viable] + rejected_models
            )[:MAX_CANDIDATES_RECORDED],
            rationale=self._rationale(chosen, viable, attempt, declared, rejections),
        )

    # -- scoring ------------------------------------------------------------

    def _input_tokens(self, task: Task) -> int:
        """Conservative upper bound on the prompt this task will produce."""
        declared_bytes = task.inputs.declared_input_bytes
        return (
            int(declared_bytes / BYTES_PER_TOKEN) + self.config.prompt_overhead_tokens
        )

    def _score(
        self, candidate: Candidate, input_tokens: int, rejections: list[str]
    ) -> _Scored | None:
        """Cost this candidate, or record why it is out of the running."""
        try:
            snapshot = self.prices.get(candidate.priced_as)
        except KeyError:
            # A missing price is never zero. Zero would read as free forever and
            # this candidate would win every comparison it entered.
            rejections.append(
                f"{candidate.model}: no price for {candidate.priced_as!r}"
            )
            return None

        context = candidate.context_window or snapshot.context_window
        needed = input_tokens + self.config.assumed_output_tokens
        if context is not None and needed > context:
            rejections.append(
                f"{candidate.model}: context {context:,} < required {needed:,}"
            )
            return None
        # An unknown context window does not exclude: unknown is not too-small,
        # and refusing on absent data over-refuses.

        usage = TokenUsage(
            input_tokens=input_tokens,
            output_tokens=self.config.assumed_output_tokens,
        )
        variable_usd = snapshot.cost_usd(usage)

        if candidate.billing_mode is BillingMode.SUBSCRIPTION:
            # Spends window, not dollars. The dollar figure is notional: what
            # this would have cost at metered rates, used only to break ties.
            window = candidate.fixed_window_tokens + input_tokens
            window += self.config.assumed_output_tokens
            fixed_usd = self._fixed_usd(candidate, snapshot)
            return _Scored(candidate, window, variable_usd + fixed_usd, context)

        # Metered: dollars only, no window at all.
        return _Scored(candidate, 0, variable_usd, context)

    def _fixed_usd(self, candidate: Candidate, snapshot) -> float:
        """Notional dollar value of the per-dispatch spawn floor."""
        if not candidate.fixed_window_tokens:
            return 0.0
        return snapshot.cost_usd(
            TokenUsage(cache_write_1h_tokens=candidate.fixed_window_tokens)
        )

    # -- tier movement ------------------------------------------------------

    @staticmethod
    def _is_downshift(requested: Tier, final: Tier) -> bool:
        from sleipnir.schema import DOWNSHIFT_LADDER

        if requested is final:
            return False
        if requested not in DOWNSHIFT_LADDER or final not in DOWNSHIFT_LADDER:
            return False
        return DOWNSHIFT_LADDER.index(final) > DOWNSHIFT_LADDER.index(requested)

    @staticmethod
    def _is_escalation(requested: Tier, final: Tier) -> bool:
        from sleipnir.schema import DOWNSHIFT_LADDER

        if requested is final:
            return False
        if requested not in DOWNSHIFT_LADDER or final not in DOWNSHIFT_LADDER:
            return False
        return DOWNSHIFT_LADDER.index(final) < DOWNSHIFT_LADDER.index(requested)

    @staticmethod
    def _guard_tier_movement(task: Task, tier: Tier) -> None:
        if task.tier is Tier.LONGCTX and tier is not Tier.LONGCTX:
            raise NoViableCandidate(
                f"task {task.id!r} is longctx; moving it to {tier.value!r} is a "
                "correctness failure, not a cost decision. DOWNSHIFT_LADDER "
                "excludes longctx for exactly this reason."
            )

    # -- explainability -----------------------------------------------------

    def _rationale(
        self,
        chosen: _Scored,
        viable: Sequence[_Scored],
        attempt: int,
        input_tokens: int,
        rejections: Sequence[str],
    ) -> str:
        scarce = self.config.scarce.value
        parts = [
            f"optimising for {scarce}",
            f"~{input_tokens:,} input tokens declared",
            f"{len(viable)} viable of "
            f"{len(viable) + len(rejections)} candidates",
        ]
        if chosen.candidate.fixed_window_tokens:
            parts.append(
                f"fixed spawn cost {chosen.candidate.fixed_window_tokens:,} tokens "
                "included in the score"
            )
        else:
            parts.append("no fixed spawn cost")
        if attempt > 1:
            parts.append(
                f"attempt {attempt}: rotated to candidate "
                f"{((attempt - 1) % len(viable)) + 1} of {len(viable)} so a retry "
                "is not an identical call"
            )
        if self.prices.stale:
            parts.append(
                f"WARNING: prices are stale (fetched {self.prices.fetched_at:%Y-%m-%d})"
            )
        if rejections:
            parts.append("rejected: " + "; ".join(rejections[:3]))
        return "; ".join(parts)[:1_000]


# ---------------------------------------------------------------------------
# Default table
# ---------------------------------------------------------------------------
#
# A STARTING POINT, not an authority. Every entry is a human claim that the
# model can do that tier's work; none of it is derived from the catalogue,
# because the catalogue has no capability column. Prices and context windows are
# always live — only the membership of these lists is hand-written.
#
# Verified 2026-08-18 against the live OpenRouter catalogue: every price_model
# below exists in it. `openrouter/*` meta-models are deliberately absent — they
# price at -1 (cost depends on which model the meta-router picks), which makes
# their cost unknowable before dispatch and would score as infinitely cheap.

_CLAUDE_OPUS = Candidate(
    adapter=Adapter.CLAUDE,
    model="opus",
    billing_mode=BillingMode.SUBSCRIPTION,
    fixed_window_tokens=CLI_SPAWN_FLOOR_TOKENS,
    price_model="anthropic/claude-opus-5",
    note="subscription; spends window, not dollars",
)

_CLAUDE_SONNET = Candidate(
    adapter=Adapter.CLAUDE,
    model="sonnet",
    billing_mode=BillingMode.SUBSCRIPTION,
    fixed_window_tokens=CLI_SPAWN_FLOOR_TOKENS,
    price_model="anthropic/claude-sonnet-5",
)

_CLAUDE_HAIKU = Candidate(
    adapter=Adapter.CLAUDE,
    model="haiku",
    billing_mode=BillingMode.SUBSCRIPTION,
    fixed_window_tokens=CLI_SPAWN_FLOOR_TOKENS,
    price_model="anthropic/claude-haiku-4.5",
)

_CODEX = Candidate(
    adapter=Adapter.CODEX,
    model="gpt-5.1-codex",
    billing_mode=BillingMode.SUBSCRIPTION,
    fixed_window_tokens=CLI_SPAWN_FLOOR_TOKENS,
    price_model="openai/gpt-5.1-codex",
    note="UNVERIFIED: codex CLI flags not yet confirmed against a real run",
)

#: Free-tier OpenRouter models. Zero dollars, zero window, but rate-limited per
#: day and observed to 429 individually — which is what attempt-rotation is for.
_FREE_LARGE = Candidate(
    adapter=Adapter.OPENROUTER,
    model="nvidia/nemotron-3-ultra-550b-a55b:free",
    billing_mode=BillingMode.METERED,
)
_FREE_FAST = Candidate(
    adapter=Adapter.OPENROUTER,
    model="nvidia/nemotron-3.5-lightning:free",
    billing_mode=BillingMode.METERED,
)
_FREE_CODE = Candidate(
    adapter=Adapter.OPENROUTER,
    model="poolside/laguna-s-2.1:free",
    billing_mode=BillingMode.METERED,
)

#: Cheapest metered models, as a paid fallback when the free tier is exhausted.
_CHEAP = Candidate(
    adapter=Adapter.OPENROUTER,
    model="inclusionai/ling-2.6-flash",
    billing_mode=BillingMode.METERED,
)
_CHEAP_LONG = Candidate(
    adapter=Adapter.OPENROUTER,
    model="upstage/solar-pro4",
    billing_mode=BillingMode.METERED,
)

DEFAULT_CANDIDATES: Mapping[Tier, tuple[Candidate, ...]] = {
    # Architecture and ambiguous judgment. No free model is trusted here; this
    # is the tier where being wrong is expensive downstream.
    Tier.REASON: (_CLAUDE_OPUS, _CLAUDE_SONNET),
    # Bulk implementation against a clear spec.
    Tier.CODE: (_CLAUDE_SONNET, _CODEX, _FREE_CODE),
    # Summarisation and structured extraction — cheap models do this well.
    Tier.EXTRACT: (_FREE_FAST, _CHEAP, _CLAUDE_HAIKU),
    # Renames and deterministic transforms. The spawn floor is the entire
    # argument for keeping these off the CLIs.
    Tier.MECHANICAL: (_FREE_FAST, _CHEAP, _CLAUDE_HAIKU),
    # Large inputs. Membership here is a context-window claim as much as a
    # capability one; the fit check enforces the rest.
    Tier.LONGCTX: (_FREE_LARGE, _CLAUDE_SONNET, _CHEAP_LONG),
}
