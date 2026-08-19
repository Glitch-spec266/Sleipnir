"""The adapter interface.

An adapter's job is narrow on purpose: take a fully-resolved dispatch, run it,
stream everything to disk, and report *what it observed*. It does not assemble
the `AttemptFinished` record.

That split is deliberate and is a refinement of the brief's "returns a result
record". An adapter cannot know an attempt's cost — for metered providers that
needs a price snapshot the router owns (Phase 3), and it cannot know whether
acceptance checks passed, because those run after it returns. Letting adapters
build the record would either duplicate that logic three times or force pricing
into the adapter layer. So adapters return facts; the executor composes the
record.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar

from sleipnir.artifacts import AttemptWorkspace
from sleipnir.schema import (
    Adapter,
    AttemptStatus,
    BillingMode,
    FailureKind,
    Task,
    Tier,
    TokenUsage,
)


class AdapterError(RuntimeError):
    """Adapter could not dispatch at all — a bug or a misconfiguration here,
    not a failure of the model. Surfaces as FailureKind.ADAPTER_ERROR."""


@dataclass(slots=True)
class DispatchRequest:
    """Everything an adapter needs. Fully resolved — adapters never route."""

    task: Task
    attempt: int
    tier_final: Tier
    model: str
    prompt: str
    workspace: AttemptWorkspace
    timeout_s: float
    env: Mapping[str, str] = field(default_factory=dict)
    grace_s: float = 5.0
    #: Unique per execution, including a resume of the same plan. Adapters that
    #: mint provider-side identifiers must fold this in — see
    #: ClaudeAdapter._session_id.
    run_id: str = "run-adhoc"


@dataclass(slots=True)
class DispatchOutcome:
    """What the adapter observed. Raw facts only, no derived accounting."""

    status: AttemptStatus
    failure_kind: FailureKind | None = None
    usage: TokenUsage = field(default_factory=TokenUsage)
    billing_mode: BillingMode = BillingMode.METERED
    #: Provider-reported cost. When present it is authoritative and the
    #: executor marks the CostEstimate `is_estimate=False` — no pricing lookup.
    reported_cost_usd: float | None = None
    model_used: str | None = None
    exit_code: int | None = None
    stderr_tail: str = ""
    summary_text: str = ""
    response_text: str = ""
    provider_meta: dict[str, Any] = field(default_factory=dict)

    def with_failure(self, kind: FailureKind) -> DispatchOutcome:
        self.status = AttemptStatus.FAILED
        self.failure_kind = kind
        return self


@dataclass(slots=True)
class DispatchPreview:
    """What a dry run prints. Must be producible without spending anything."""

    task_id: str
    attempt: int
    adapter: Adapter
    tier_final: Tier
    model: str
    target: str
    prompt_bytes: int
    estimated_input_tokens: int
    timeout_s: float
    workspace: str
    notes: list[str] = field(default_factory=list)

    def render(self) -> str:
        line = (
            f"{self.task_id:<16} {self.adapter.value:<11} {self.tier_final.value:<11} "
            f"{self.model:<34} {self.estimated_input_tokens:>8}tok  {self.target}"
        )
        if self.notes:
            line += "\n" + "\n".join(f"{'':<16} ! {note}" for note in self.notes)
        return line


class BaseAdapter(ABC):
    """One dispatch backend.

    Auth is never implemented here. The `claude` and `codex` adapters shell out
    to the official CLIs and inherit whatever credentials those already hold;
    the `openrouter` adapter reads a plain API key from the environment. No
    adapter performs an OAuth flow, and none ever should — doing so for a
    subscription provider would be a terms-of-service violation.
    """

    name: ClassVar[Adapter]
    # Concrete subscription adapters override this on the instance. Keeping a
    # metered default makes crash-recovery records conservative for adapters
    # that do not need a configurable billing mode (notably OpenRouter).
    billing_mode: BillingMode = BillingMode.METERED

    @abstractmethod
    async def dispatch(self, request: DispatchRequest) -> DispatchOutcome:
        """Run the request to completion, a timeout, or a cancellation.

        Implementations must stream output to ``request.workspace`` as it
        arrives, and must re-raise ``asyncio.CancelledError`` after killing any
        child process they own.
        """

    @abstractmethod
    def preview(self, request: DispatchRequest) -> DispatchPreview:
        """Describe the dispatch without performing it. No network, no spawn."""

    @staticmethod
    def _redact(env: Mapping[str, str]) -> dict[str, str]:
        """Never let a credential reach a preview, a log, or an artifact."""
        secret = ("KEY", "TOKEN", "SECRET", "PASSWORD", "AUTH")
        return {
            key: ("***" if any(marker in key.upper() for marker in secret) else value)
            for key, value in env.items()
        }

    @staticmethod
    def _subprocess_env(env: Mapping[str, str]) -> dict[str, str]:
        """Environment for an agent CLI, stripped of unrelated credentials.

        The official CLIs use their own credential stores. Passing the entire
        parent environment would also hand a delegated coding agent every API
        key and CI token in the operator's shell. Empty request environments
        mean "use the parent environment safely", not raw inheritance.
        """
        source = env or os.environ
        secret = ("KEY", "TOKEN", "SECRET", "PASSWORD", "AUTH", "CREDENTIAL")
        return {
            key: value
            for key, value in source.items()
            if not any(marker in key.upper() for marker in secret)
        }


__all__ = [
    "AdapterError",
    "BaseAdapter",
    "DispatchOutcome",
    "DispatchPreview",
    "DispatchRequest",
]
