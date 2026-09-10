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


# A greeting must never enter the twelve-step tool loop. Answering "what's up"
# used to cost a screenshot, a vision encode and up to twelve model calls.
_SMALLTALK_PATTERN = re.compile(
    r"^(hi|hey|hello|hiya|yo|sup|what'?s up|what'?s good|how'?s it going|"
    r"how are (you|things)|you (there|awake|up)|are you (there|awake|up)|"
    r"good (morning|afternoon|evening|night)|thanks|thank you|cheers|"
    r"nice one|never mind|nevermind|forget it)\b",
    re.IGNORECASE,
)
# The desktop frame is only worth its latency when the request is about what is
# displayed. Attaching it unconditionally is also what made a small model
# narrate -- and hallucinate -- a screen nobody asked about.
_SCREEN_PATTERN = re.compile(
    r"\b(screen|display|monitor|window|desktop|browser|tab|page|dialog|"
    r"looking at|see (this|that|here)|read (this|that|the)|on screen|"
    r"in front of me|this (form|question|image|picture|chart|error))\b",
    re.IGNORECASE,
)
# MEASURED on this machine: with ``think: false`` every candidate model got
# 17*24+139 wrong (425, 445) and answered 547 correctly only once allowed a
# scratchpad. Arithmetic and physics are exactly the shapes that need one.
_REASONING_PATTERN = re.compile(
    r"\b(calculat\w*|comput\w*|deriv\w*|prove|proof|solve|evaluate|"
    r"how (much|many|far|high|fast|long|old)|"
    r"times|multipl\w*|divid\w*|plus|minus|percent|square root|"
    r"equation|formula|physics|algebra|geometry|calculus|probability|"
    r"velocity|acceleration|momentum|energy|force|voltage|molar|"
    r"interest|average|median|ratio|convert)\b",
    re.IGNORECASE,
)
_DIGIT_RUN = re.compile(r"\d")

_SMALLTALK_MAX_CHARS = 48


def is_smalltalk(text: str) -> bool:
    """True for a greeting or an acknowledgement that deserves one fast reply."""
    clean = " ".join(text.split()).strip(" .,!?:;-")
    if not clean or len(clean) > _SMALLTALK_MAX_CHARS:
        return False
    if _SCREEN_PATTERN.search(clean) or _WORK_PATTERN.search(clean):
        return False
    return bool(_SMALLTALK_PATTERN.match(clean))


def needs_screen(text: str) -> bool:
    """True when the operator is asking about what is currently displayed."""
    return bool(_SCREEN_PATTERN.search(" ".join(text.split())))


def needs_reasoning(text: str) -> bool:
    """True when the answer needs a scratchpad rather than a fast reply."""
    clean = " ".join(text.split())
    if not clean or is_smalltalk(clean) or needs_screen(clean):
        return False
    if not _REASONING_PATTERN.search(clean):
        return False
    # A bare "how many tabs" is a lookup; a sum has numbers in it or names a
    # named technique. Requiring one of the two keeps ordinary chat off a lane
    # that costs ten seconds of deliberation.
    return bool(_DIGIT_RUN.search(clean)) or bool(
        re.search(r"\b(deriv\w*|prove|proof|solve|equation|formula|physics|"
                  r"algebra|geometry|calculus|probability)\b", clean, re.IGNORECASE)
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


__all__ = [
    "RouteDecision", "RouteMode", "choose_ambient_provider", "is_smalltalk",
    "needs_reasoning", "needs_screen", "route_utterance",
]
