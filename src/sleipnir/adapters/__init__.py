"""Dispatch backends.

Three implementations of one interface. None of them implements provider auth:
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
from sleipnir.adapters.claude import ClaudeAdapter
from sleipnir.adapters.codex import CodexAdapter, CodexInvocation
from sleipnir.adapters.openrouter import OpenRouterAdapter

__all__ = [
    "AdapterError",
    "BaseAdapter",
    "ClaudeAdapter",
    "CodexAdapter",
    "CodexInvocation",
    "DispatchOutcome",
    "DispatchPreview",
    "DispatchRequest",
    "OpenRouterAdapter",
]
