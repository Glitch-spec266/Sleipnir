"""Dispatch backends.

Several implementations of one interface. None of them persists provider auth:
`claude` and `codex` inherit credentials from the official CLIs they shell out
to, and `openrouter` reads a plain bearer key from the environment.
"""

from sleipnir.adapters.base import (
    AdapterError,
    BaseAdapter,
    DispatchOutcome,
    DispatchPreview,
    DispatchRequest,
)
from sleipnir.adapters.anthropic import AnthropicAdapter
from sleipnir.adapters.claude import ClaudeAdapter
from sleipnir.adapters.codex import CodexAdapter, CodexInvocation
from sleipnir.adapters.openrouter import OpenAICompatibleAdapter, OpenRouterAdapter

__all__ = [
    "AdapterError",
    "AnthropicAdapter",
    "BaseAdapter",
    "ClaudeAdapter",
    "CodexAdapter",
    "CodexInvocation",
    "DispatchOutcome",
    "DispatchPreview",
    "DispatchRequest",
    "OpenRouterAdapter",
    "OpenAICompatibleAdapter",
]
