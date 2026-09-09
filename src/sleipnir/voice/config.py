"""Validated non-secret voice preferences.

Provider keys are intentionally absent.  Preferences may name an environment
variable, but the value remains in the operator's process environment and is
never serialized beside these settings.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_WAKE_NAME = re.compile(r"^[\w][\w '\u2019-]*$", re.UNICODE)


def validate_wake_name(value: str) -> str:
    name = " ".join(value.split())
    if not 2 <= len(name) <= 32:
        raise ValueError("wake name must contain 2 to 32 characters")
    if not _WAKE_NAME.fullmatch(name):
        raise ValueError("wake name may contain letters, numbers, spaces, apostrophes, and hyphens")
    return name


class VoiceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    wake_name: str = "Sleipnir"
    local_wake: bool = True
    start_at_login: bool = False
    push_to_talk_shortcut: str = Field(default="Space", min_length=1, max_length=80)
    transcription: Literal["local", "gemini"] = "local"
    response_model: str = Field(default="openrouter/auto", min_length=1, max_length=200)
    escalation: Literal["automatic", "confirm"] = "automatic"
    voice_provider: Literal["system", "gemini", "openrouter", "elevenlabs"] = "system"
    voice_id: str = Field(default="system-natural", min_length=1, max_length=100)
    accent: Literal["neutral", "american", "british", "australian", "indian"] = "neutral"
    interruptible: bool = True

    @field_validator("wake_name")
    @classmethod
    def _valid_wake_name(cls, value: str) -> str:
        return validate_wake_name(value)


__all__ = ["VoiceConfig", "validate_wake_name"]
