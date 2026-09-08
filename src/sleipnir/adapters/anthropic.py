"""Anthropic Messages API adapter using the shared fenced-file protocol."""

from __future__ import annotations

from typing import Any

from sleipnir.adapters.base import DispatchRequest
from sleipnir.adapters.openrouter import OpenRouterAdapter
from sleipnir.schema import Adapter, TokenUsage


class AnthropicAdapter(OpenRouterAdapter):
    """Direct, SDK-free access to an Anthropic-compatible Messages endpoint."""

    name = Adapter.ANTHROPIC
    endpoint_path = "messages"

    def __init__(
        self,
        *,
        max_output_tokens: int = 16_384,
        anthropic_version: str = "2023-06-01",
        **kwargs: Any,
    ) -> None:
        if max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive")
        self.max_output_tokens = max_output_tokens
        self.anthropic_version = anthropic_version
        kwargs["stream"] = False
        kwargs["openrouter_usage"] = False
        super().__init__(**kwargs)

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": str(self.api_key),
            "anthropic-version": self.anthropic_version,
            "Content-Type": "application/json",
        }

    def body(self, request: DispatchRequest, prompt: str) -> dict[str, Any]:
        return {
            "model": request.model,
            "max_tokens": self.max_output_tokens,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }

    @staticmethod
    def _content_of(payload: dict[str, Any]) -> str:
        return "".join(
            block.get("text", "")
            for block in payload.get("content") or []
            if isinstance(block, dict) and block.get("type") == "text"
        )

    @staticmethod
    def _finish_reason(payload: dict[str, Any]) -> str | None:
        reason = payload.get("stop_reason")
        return "length" if reason == "max_tokens" else reason

    @staticmethod
    def _usage_of(payload: dict[str, Any]) -> TokenUsage:
        usage = payload.get("usage") or {}
        return TokenUsage(
            input_tokens=max(0, int(usage.get("input_tokens") or 0)),
            cache_read_tokens=max(0, int(usage.get("cache_read_input_tokens") or 0)),
            cache_write_5m_tokens=max(
                0, int(usage.get("cache_creation_input_tokens") or 0)
            ),
            output_tokens=max(0, int(usage.get("output_tokens") or 0)),
        )


__all__ = ["AnthropicAdapter"]
