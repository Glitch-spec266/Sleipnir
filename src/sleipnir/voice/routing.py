"""Cheap deterministic pre-router for voice turns.

This classifier does not execute anything.  It only decides whether the turn
can stay on an inexpensive conversational lane or should show an escalation
decision before a Claude/Codex work session receives it.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class RouteMode(StrEnum):
    AMBIENT = "ambient"
    HIGH = "high"
    CONFIRM_ESCALATION = "confirm_escalation"
    CONFIRM_DEESCALATION = "confirm_deescalation"


@dataclass(frozen=True, slots=True)
class RouteDecision:
    mode: RouteMode
    target: str
    reason: str
    requires_confirmation: bool


_WORK_PATTERN = re.compile(
    r"\b(build|implement|fix|refactor|debug|deploy|release|install|configure|"
    r"test|commit|push|edit|write|create|redesign|research|presentation|slides|"
    r"full[ -]?stack|repository|codebase|project)\b",
    re.IGNORECASE,
)
_DEEP_PATTERN = re.compile(
    r"\b(architecture|security|migration|production|multi[ -]?stage|thorough|"
    r"investigate|root cause|autonomous|entire|everything)\b",
    re.IGNORECASE,
)


def choose_ambient_provider(environment: Mapping[str, str] | None = None) -> str | None:
    environment = os.environ if environment is None else environment
    # Gemini's free allowance makes it the default duty-officer lane when the
    # user has activated both. OpenRouter remains the broad-model fallback.
    if environment.get("GEMINI_API_KEY"):
        return "gemini"
    if environment.get("OPENROUTER_API_KEY"):
        return "openrouter"
    if environment.get("NVIDIA_API_KEY"):
        return "nvidia-nim"
    return None


def route_utterance(
    text: str,
    *,
    force: RouteMode | None = None,
    preferred_worker: str = "codex",
) -> RouteDecision:
    clean = " ".join(text.split())
    if not clean:
        raise ValueError("voice instruction cannot be empty")
    if force is RouteMode.HIGH:
        return RouteDecision(RouteMode.HIGH, preferred_worker, "Operator forced the work lane.", False)
    if force is RouteMode.AMBIENT:
        return RouteDecision(RouteMode.AMBIENT, "ambient", "Operator forced the fast lane.", False)

    looks_like_work = bool(_WORK_PATTERN.search(clean))
    looks_deep = bool(_DEEP_PATTERN.search(clean)) or len(clean) > 240
    if looks_like_work:
        target = "claude" if looks_deep else preferred_worker
        return RouteDecision(
            RouteMode.CONFIRM_ESCALATION,
            target,
            "This request can change a project or the host, so a capable work lane is appropriate.",
            True,
        )
    return RouteDecision(
        RouteMode.AMBIENT,
        "ambient",
        "A short informational response can stay on the fast lane.",
        False,
    )


__all__ = ["RouteDecision", "RouteMode", "choose_ambient_provider", "route_utterance"]
