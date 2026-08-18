"""Tier -> concrete model resolution.

Tasks declare a *tier*. This module turns that into a model at dispatch time,
using live catalogue data plus the operator's config. It contains no model
names, no prices, and no provider knowledge — all of that arrives as data.

The routing rationale for every task is retained so `sleipnir explain` can show
not just what was chosen but what was rejected and why. A router you cannot
interrogate is a router you cannot trust with money.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sleipnir.config import Backend, SleipnirConfig, TierPolicy
from sleipnir.pricing import CatalogSnapshot, ModelInfo
from sleipnir.schema import (
    CHARS_PER_TOKEN,
    DOWNSHIFT_LADDER,
    RoutingDecision,
    Task,
    Tier,
)

#: Headroom for the prompt scaffolding, dependency summaries and the model's
#: own output. A heuristic, and deliberately generous: routing a task to a model
#: whose context it overflows fails the task outright, while over-reserving only
#: narrows the candidate pool slightly.
BASE_CONTEXT_ALLOWANCE = 8_000


class RoutingError(RuntimeError):
    """No model satisfies the tier. Raised before dispatch, never mid-run."""


@dataclass(slots=True)
class CandidateEval:
    model_id: str
    backend: str
    accepted: bool
    reason: str
    blended_per_mtok: float | None = None
    context_length: int | None = None

    def render(self) -> str:
        mark = "OK  " if self.accepted else "SKIP"
        price = f"${self.blended_per_mtok:.2f}/Mtok" if self.blended_per_mtok is not None else "price unknown"
        ctx = f"{self.context_length:,} ctx" if self.context_length else "ctx unknown"
        return f"  {mark} {self.model_id:<40} [{self.backend}] {price:>18}  {ctx:>16}  {self.reason}"


@dataclass(slots=True)
class RoutingExplanation:
    task_id: str
    tier_requested: Tier
    tier_final: Tier
    required_context: int
    decision: RoutingDecision | None
    candidates: list[CandidateEval] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines = [
            f"task {self.task_id}",
            f"  tier declared : {self.tier_requested.value}",
            f"  tier used     : {self.tier_final.value}"
            + ("  (DOWNSHIFTED)" if self.decision and self.decision.downshifted else "")
            + ("  (ESCALATED)" if self.decision and self.decision.escalated else ""),
            f"  context needed: {self.required_context:,} tokens",
        ]
        if self.decision:
            lines.append(f"  chosen        : {self.decision.model} via {self.decision.adapter.value}")
            if self.decision.downshift_reason:
                lines.append(f"  downshift why : {self.decision.downshift_reason}")
            lines.append(f"  rationale     : {self.decision.rationale}")
        else:
            lines.append("  chosen        : NOTHING — no candidate satisfied the tier")
        lines.append("  candidates:")
        lines.extend(candidate.render() for candidate in self.candidates)
        lines.extend(f"  ! {note}" for note in self.notes)
        return "\n".join(lines)


def required_context_tokens(task: Task, policy: TierPolicy) -> int:
    """How much context this task plausibly needs.

    Driven by what the task *declared* it would read, not by the global
    max_input_bytes default — using the cap would demand a 70k-token window for
    a task that reads nothing.
    """
    declared = int(task.inputs.declared_input_bytes / CHARS_PER_TOKEN)
    return max(policy.min_context, declared + BASE_CONTEXT_ALLOWANCE)


class TierRouter:
    """Resolves tier -> model. Implements the executor's Router protocol."""

    def __init__(self, config: SleipnirConfig, catalog: CatalogSnapshot) -> None:
        self.config = config
        self.catalog = catalog

    def resolve(
        self,
        task: Task,
        *,
        attempt: int,
        tier: Tier,
        downshift_reason: str | None = None,
    ) -> RoutingDecision:
        explanation = self.explain(
            task, attempt=attempt, tier=tier, downshift_reason=downshift_reason
        )
        if explanation.decision is None:
            rejected = "\n".join(c.render() for c in explanation.candidates)
            raise RoutingError(
                f"task {task.id!r}: no model satisfies tier {tier.value!r} "
                f"(needs {explanation.required_context:,} tokens of context)\n{rejected}"
            )
        return explanation.decision

    def explain(
        self,
        task: Task,
        *,
        attempt: int = 1,
        tier: Tier | None = None,
        downshift_reason: str | None = None,
    ) -> RoutingExplanation:
        tier = tier or task.tier
        policy = self.config.policy(tier)
        needed = required_context_tokens(task, policy)
        explanation = RoutingExplanation(
            task_id=task.id,
            tier_requested=task.tier,
            tier_final=tier,
            required_context=needed,
            decision=None,
        )
        if self.catalog.stale:
            explanation.notes.append(
                f"catalogue is stale (fetched {self.catalog.fetched_at.isoformat()}); "
                "prices may be out of date"
            )

        for backend_name in policy.prefer:
            backend = self.config.backends[backend_name]
            accepted, evaluated = self._evaluate(backend, policy, needed)
            explanation.candidates.extend(evaluated)
            if not accepted:
                continue

            # Rotate by attempt rather than always taking the cheapest.
            # Free models rate-limit individually — one returned HTTP 429 while
            # its neighbour answered instantly — so an identical retry fails
            # identically. Taking the nth-cheapest makes a retry a genuinely
            # different call, and as a side effect gives tier escalation
            # (second-cheapest is usually the stronger model) with no ladder.
            winner, info = accepted[(max(attempt, 1) - 1) % len(accepted)]
            explanation.decision = self._decide(
                task, tier, backend, winner, info, policy, downshift_reason, attempt
            )
            return explanation

        return explanation

    # -- candidate evaluation -------------------------------------------------

    def _evaluate(
        self, backend: Backend, policy: TierPolicy, needed: int
    ) -> tuple[list[tuple[str, ModelInfo | None]], list[CandidateEval]]:
        """Return (accepted, all-evaluated). Accepted is already ranked."""
        evaluated: list[CandidateEval] = []
        accepted: list[tuple[str, ModelInfo | None, float]] = []

        if backend.uses_catalog:
            pool = [(model.id, model, None) for model in self.catalog.models.values()]
        else:
            pool = [
                (option.id, self.catalog.get(option.id), option) for option in backend.models
            ]

        for model_id, info, option in pool:
            context = self._context_of(info, option)
            price = self._price_of(info, option, policy)
            verdict = self._verdict(model_id, info, option, policy, needed, context, price)
            evaluated.append(
                CandidateEval(
                    model_id=model_id,
                    backend=backend.name,
                    accepted=verdict is None,
                    reason=verdict or "satisfies the tier",
                    blended_per_mtok=price,
                    context_length=context,
                )
            )
            if verdict is None:
                accepted.append((model_id, info, price if price is not None else 0.0))

        if backend.uses_catalog:
            # Catalogue pools are large and unordered: cheapest satisfying wins.
            accepted.sort(key=lambda item: (item[2], item[0]))
        # Explicit model lists keep config order — the operator knows their plan
        # better than a price table does.
        return [(model_id, info) for model_id, info, _ in accepted], evaluated

    @staticmethod
    def _context_of(info: ModelInfo | None, option) -> int | None:
        if option is not None and option.context:
            return option.context
        return info.context_length if info else None

    @staticmethod
    def _price_of(info: ModelInfo | None, option, policy: TierPolicy) -> float | None:
        if option is not None and option.price_per_mtok is not None:
            return option.price_per_mtok
        return info.blended_per_mtok(policy.output_ratio) if info else None

    @staticmethod
    def _verdict(
        model_id: str,
        info: ModelInfo | None,
        option,
        policy: TierPolicy,
        needed: int,
        context: int | None,
        price: float | None,
    ) -> str | None:
        """None means accepted; a string is the rejection reason."""
        if policy.deny and any(pattern in model_id for pattern in policy.deny):
            return "matches a deny pattern"
        if policy.allow and not any(pattern in model_id for pattern in policy.allow):
            return "does not match any allow pattern"
        if context is None:
            return "context window unknown"
        if context < needed:
            return f"context {context:,} < {needed:,} required"
        if policy.max_price_per_mtok is not None:
            if price is None:
                return "price unknown and the tier caps price"
            if price > policy.max_price_per_mtok:
                return f"${price:.2f}/Mtok exceeds cap ${policy.max_price_per_mtok:.2f}"
        if policy.require_parameters:
            # Only enforced when the catalogue actually reports capabilities.
            # An operator-declared subscription model has none, and rejecting it
            # for that would make require_parameters silently exclude every
            # subscription backend.
            if info is not None and info.supported_parameters:
                missing = [
                    parameter
                    for parameter in policy.require_parameters
                    if parameter not in info.supported_parameters
                ]
                if missing:
                    return f"missing required parameter(s): {', '.join(missing)}"
        return None

    def _decide(
        self,
        task: Task,
        tier: Tier,
        backend: Backend,
        model_id: str,
        info: ModelInfo | None,
        policy: TierPolicy,
        downshift_reason: str | None,
        attempt: int,
    ) -> RoutingDecision:
        downshifted, escalated = _movement(task.tier, tier)
        # A tier change the governor did not explain is an escalation from the
        # retry ladder, not a downshift; the schema rejects an unexplained one.
        if downshifted and not downshift_reason:
            downshift_reason = f"tier lowered from {task.tier.value} to {tier.value}"

        price = self._price_of(info, None, policy)
        bits = [f"backend {backend.name!r} ({backend.billing.value})"]
        if price is not None:
            bits.append(f"${price:.2f}/Mtok blended")
        if backend.dispatch_overhead_tokens:
            bits.append(f"+{backend.dispatch_overhead_tokens:,} tok fixed dispatch overhead")
        if attempt > 1:
            bits.append(f"attempt {attempt}")

        return RoutingDecision(
            tier_requested=task.tier,
            tier_final=tier,
            model=model_id,
            adapter=backend.adapter,
            downshifted=downshifted,
            escalated=escalated,
            downshift_reason=downshift_reason if downshifted else None,
            candidates_considered=[model_id][:20],
            rationale=(
                f"tier {tier.value!r} prefers {list(policy.prefer)}; chose {model_id} from "
                + ", ".join(bits)
            )[:1_000],
        )


def _movement(requested: Tier, final: Tier) -> tuple[bool, bool]:
    """Is `final` cheaper or more capable than `requested`?

    longctx sits outside the ladder on purpose: moving a task off longctx is
    not a cost decision, it is a correctness failure.
    """
    if requested is final:
        return False, False
    if requested not in DOWNSHIFT_LADDER or final not in DOWNSHIFT_LADDER:
        return False, False
    return (
        DOWNSHIFT_LADDER.index(final) > DOWNSHIFT_LADDER.index(requested),
        DOWNSHIFT_LADDER.index(final) < DOWNSHIFT_LADDER.index(requested),
    )


__all__ = [
    "BASE_CONTEXT_ALLOWANCE",
    "CandidateEval",
    "RoutingError",
    "RoutingExplanation",
    "TierRouter",
    "required_context_tokens",
]
