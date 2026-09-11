"""Tier-based dispatch for the local voice lane.

The local model is not good enough for every question it is asked, and the
honest answer to that is to hand the work somewhere better. This module is the
seam: it turns the operator's configured *tiers* into a menu a small model can
read, and turns a tier the model names back into one concrete free model.

Two rules shape everything here.

* **The local model sees tiers, never models.** Tiers already carry the
  operator's capability and price policy, and :class:`~sleipnir.router.TierRouter`
  turns one into a model. So the standing "no model name in source" rule is
  satisfied for free, and the menu costs about sixty prompt tokens rather than
  four hundred.
* **Zero incremental dollars.** The operator's constraint is free models only,
  not cheap ones, so the price ceiling here is a hard zero regardless of what
  the tier's own ``max_price_per_mtok`` allows. A lane that cannot find a free
  model refuses; it never falls back to a paid one.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from pathlib import Path

from sleipnir.config import ConfigError, SleipnirConfig
from sleipnir.pricing import CatalogSnapshot
from sleipnir.router import RoutingError, TierRouter
from sleipnir.schema import (
    ExpectedOutput,
    InputContract,
    OutputContract,
    OutputKind,
    Task,
    Tier,
)

#: All that returns to the local model from a delegated turn. Delegation
#: happens because the local model already lost this problem; handing it the
#: whole reply to summarise spends its context on work it cannot do.
MAX_SPOKEN_CHARS = 300
_SPOKEN_MARKER = "SPOKEN:"

#: Asked of every delegated worker. The first line is the only part that comes
#: back, so it has to be able to stand alone when spoken.
SPOKEN_CONTRACT = (
    "Begin your reply with a single line starting with 'SPOKEN:' that answers "
    "the operator in one spoken sentence. Put any detail after it."
)


class DispatchRefused(RuntimeError):
    """No free model can serve this tier, or the tier is not one on the menu."""


@dataclass(frozen=True, slots=True)
class ModelChoice:
    tier: Tier
    model: str
    backend: str
    adapter: str
    #: Endpoint and the *name* of the variable holding its credential. The
    #: value is read at call time and never stored here, the same rule the
    #: config schema follows.
    base_url: str = ""
    api_key_env: str = ""


def delegation_menu(config: SleipnirConfig) -> str:
    """Render the operator's configured tiers as a menu for the local model.

    Only tiers the operator actually configured appear: a tier with no backends
    behind it is not something the model may choose, and offering it would
    produce a refusal the model cannot understand.
    """
    lines = [
        f"- {tier.value}: {policy.description}" if policy.description else f"- {tier.value}"
        for tier, policy in config.tiers.items()
    ]
    return "\n".join(lines)


def menu_for(workspace: Path) -> str:
    """The delegation menu for this workspace, or an empty string if there is none.

    A machine with no ``sleipnir.toml`` has no tiers, and that is an ordinary
    state rather than an error: the local model simply keeps every other tool
    and never offers a lane that would refuse.
    """
    try:
        path = SleipnirConfig.discover(workspace)
        return delegation_menu(SleipnirConfig.load(path)) if path else ""
    except (ConfigError, OSError):
        return ""


def spoken_line(reply: str) -> str:
    """Reduce a worker's full answer to the one sentence that is spoken.

    A worker that honours :data:`SPOKEN_CONTRACT` names its own sentence. One
    that ignores it is still bounded, because the cap is what protects the
    local context, not the worker's cooperation.
    """
    text = reply.strip()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith(_SPOKEN_MARKER):
            spoken = stripped[len(_SPOKEN_MARKER):].strip()
            if spoken:
                return spoken[:MAX_SPOKEN_CHARS]
    return " ".join(text.split())[:MAX_SPOKEN_CHARS]


def pick_model(
    config: SleipnirConfig,
    catalog: CatalogSnapshot,
    *,
    tier: Tier | str,
    attempt: int = 1,
) -> ModelChoice:
    """Resolve a tier the local model named into one free model.

    ``tier`` arrives as untrusted model output, so an unrecognised value is
    refused rather than defaulted. A silent fallback would let a hallucinated
    word decide where the operator's work and quota go -- the same rule as the
    router's unknown effort level and the Phase 14 tier pattern list.
    """
    try:
        requested = Tier(tier)
    except ValueError as error:
        raise DispatchRefused(
            f"unknown tier {tier!r}; the menu offers {[t.value for t in config.tiers]}"
        ) from error
    if requested not in config.tiers:
        raise DispatchRefused(
            f"tier {requested.value!r} is not configured; the menu offers "
            f"{[t.value for t in config.tiers]}"
        )

    # The free ceiling is imposed here rather than trusted from the file: the
    # operator's constraint is a property of this lane, and a tier written for
    # the orchestrator may legitimately allow paid models elsewhere.
    policy = dataclasses.replace(config.tiers[requested], max_price_per_mtok=0.0)
    free_only = dataclasses.replace(config, tiers={**config.tiers, requested: policy})

    try:
        decision = TierRouter(free_only, catalog).resolve(
            _placeholder_task(requested), attempt=attempt, tier=requested
        )
    except RoutingError as error:
        raise DispatchRefused(
            f"no free model serves tier {requested.value!r}; this lane never "
            f"falls back to a paid one.\n{error}"
        ) from error
    backend = free_only.backends.get(decision.backend or "")
    return ModelChoice(
        tier=requested,
        model=decision.model,
        backend=decision.backend or "",
        adapter=str(decision.adapter),
        base_url=(backend.base_url or "") if backend else "",
        api_key_env=(backend.api_key_env or "") if backend else "",
    )


def _placeholder_task(tier: Tier) -> Task:
    """A throwaway task, because the router's unit of routing is a task.

    Nothing here is dispatched. The router needs a task to size context
    against, and a voice turn has no plan entry of its own; fabricating one is
    smaller than teaching the router a second entry point.
    """
    return Task(
        id="voice-delegation",
        description="Answer one spoken operator question.",
        tier=tier,
        inputs=InputContract(),
        outputs=OutputContract(
            outputs=[
                ExpectedOutput(
                    name="answer",
                    kind=OutputKind.FILE,
                    path="answer.txt",
                    description="The spoken answer.",
                )
            ]
        ),
    )


__all__ = [
    "DispatchRefused", "MAX_SPOKEN_CHARS", "ModelChoice", "SPOKEN_CONTRACT",
    "delegation_menu", "menu_for", "pick_model", "spoken_line",
]
