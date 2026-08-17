"""Claude adapter — shells out to `claude -p` headless.

Auth is entirely the CLI's: it uses whatever subscription or API credentials
`claude` already holds. Sleipnir never sees, stores, or refreshes a token.

The result parsing below was written against real output from
`claude -p --output-format json` (CLI 2.1.234), not from memory. Two things in
that output are easy to get wrong and both were verified:

* ``usage`` describes only the FINAL assistant message. ``modelUsage``
  describes the whole dispatch, per model. On a one-word reply the two read
  ``input_tokens: 10`` and ``inputTokens: 907`` respectively — reading
  ``usage`` under-counts input by ~90x. This adapter reads ``modelUsage``.
* ``total_cost_usd`` is present and authoritative, so a Claude dispatch needs
  no pricing lookup at all and is recorded with ``is_estimate=False``.

Also measured: a `claude -p` spawn carries ~30k cache-creation tokens of
system-prompt overhead before it does any work — roughly $0.06 on Haiku for a
one-word answer. That floor is a routing input, not a rounding error; see
DESIGN.md.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

from sleipnir.adapters.base import (
    BaseAdapter,
    DispatchOutcome,
    DispatchPreview,
    DispatchRequest,
)
from sleipnir.artifacts import OUTCOME_FILENAME
from sleipnir.process import ProcessRunner, Spawner
from sleipnir.schema import (
    Adapter,
    AttemptStatus,
    BillingMode,
    FailureKind,
    TokenUsage,
    estimate_tokens,
)

#: Permission mode for dispatched subagents. Tasks run unattended, so an
#: interactive prompt would hang until the per-task timeout fires.
DEFAULT_PERMISSION_MODE = "acceptEdits"


class ClaudeAdapter(BaseAdapter):
    name = Adapter.CLAUDE

    def __init__(
        self,
        *,
        executable: str = "claude",
        permission_mode: str = DEFAULT_PERMISSION_MODE,
        billing_mode: BillingMode = BillingMode.SUBSCRIPTION,
        extra_args: list[str] | None = None,
        spawn: Spawner | None = None,
    ) -> None:
        self.executable = executable
        self.permission_mode = permission_mode
        self.billing_mode = billing_mode
        self.extra_args = list(extra_args or [])
        self._runner = ProcessRunner(spawn=spawn)

    # -- argv ---------------------------------------------------------------

    def build_argv(self, request: DispatchRequest) -> list[str]:
        """Flags verified against `claude --help` (CLI 2.1.234).

        The prompt goes over stdin rather than argv: task prompts carry file
        contents and would blow past ARG_MAX, and argv is world-readable in
        /proc.
        """
        return [
            self.executable,
            "-p",
            "--output-format",
            "json",
            "--model",
            request.model,
            "--permission-mode",
            self.permission_mode,
            "--session-id",
            self._session_id(request),
            "--add-dir",
            str(request.workspace.dir),
            *self.extra_args,
        ]

    @staticmethod
    def _session_id(request: DispatchRequest) -> str:
        """Deterministic within a run, unique across runs.

        The run_id is load-bearing, not decoration. Seeding on (task, attempt)
        alone produces the same UUID every time attempt N of a task is
        dispatched, and the CLI rejects a reused id outright:

            Error: Session ID 150180bb-... is already in use.

        That turns every resume and every re-run into an immediate
        provider_error, burning a retry before any work starts — observed live,
        not theorised.
        """
        seed = f"sleipnir/{request.run_id}/{request.task.id}/{request.attempt}"
        return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))

    # -- dispatch -----------------------------------------------------------

    async def dispatch(self, request: DispatchRequest) -> DispatchOutcome:
        workspace = request.workspace
        workspace.prepare()
        workspace.write_text("prompt.txt", request.prompt)

        argv = self.build_argv(request)
        try:
            result = await self._runner.run(
                argv,
                stdout_path=workspace.stdout_path,
                stderr_path=workspace.stderr_path,
                cwd=workspace.dir,
                env=request.env or None,
                stdin_data=request.prompt,
                timeout_s=request.timeout_s,
                grace_s=request.grace_s,
            )
        except asyncio.CancelledError:
            # The runner has already killed the process group. Re-raise so the
            # executor can record the cancellation.
            raise
        except FileNotFoundError as exc:
            return DispatchOutcome(
                status=AttemptStatus.FAILED,
                failure_kind=FailureKind.ADAPTER_ERROR,
                billing_mode=self.billing_mode,
                stderr_tail=f"{self.executable} not found on PATH: {exc}",
            )

        outcome = self._parse(
            request, workspace.stdout_path if result.stdout_bytes else None
        )
        outcome.exit_code = result.exit_code
        outcome.stderr_tail = result.stderr_tail

        if result.timed_out:
            outcome.status = AttemptStatus.FAILED
            outcome.failure_kind = FailureKind.TIMEOUT
        elif result.exit_code not in (0, None) and outcome.failure_kind is None:
            outcome.status = AttemptStatus.FAILED
            outcome.failure_kind = FailureKind.PROVIDER_ERROR

        workspace.write_json(
            OUTCOME_FILENAME,
            {
                "argv": argv,
                "exit_code": result.exit_code,
                "timed_out": result.timed_out,
                "signalled": result.signalled,
                "duration_s": round(result.duration_s, 3),
                "provider": outcome.provider_meta,
            },
        )
        return outcome

    # -- parsing ------------------------------------------------------------

    def _parse(self, request: DispatchRequest, stdout_path: Path | None) -> DispatchOutcome:
        outcome = DispatchOutcome(
            status=AttemptStatus.SUCCEEDED, billing_mode=self.billing_mode
        )
        if stdout_path is None or not stdout_path.exists():
            return outcome.with_failure(FailureKind.PROVIDER_ERROR)

        raw = stdout_path.read_text(encoding="utf-8", errors="replace").strip()
        if not raw:
            return outcome.with_failure(FailureKind.PROVIDER_ERROR)

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            # `--output-format json` emits one object. Anything else means the
            # CLI died mid-write or changed shape; keep the bytes and say so
            # rather than guessing.
            outcome.response_text = raw[-2_000:]
            return outcome.with_failure(FailureKind.PROVIDER_ERROR)

        if not isinstance(payload, dict):
            return outcome.with_failure(FailureKind.PROVIDER_ERROR)

        return self._from_payload(payload, outcome)

    def _from_payload(self, payload: dict[str, Any], outcome: DispatchOutcome) -> DispatchOutcome:
        model_usage: dict[str, Any] = payload.get("modelUsage") or {}
        outcome.usage = self._aggregate_usage(model_usage, payload.get("usage") or {})
        outcome.model_used = self._primary_model(model_usage)
        outcome.response_text = str(payload.get("result") or "")

        cost = payload.get("total_cost_usd")
        if isinstance(cost, int | float):
            outcome.reported_cost_usd = float(cost)

        outcome.provider_meta = {
            "session_id": payload.get("session_id"),
            "subtype": payload.get("subtype"),
            "stop_reason": payload.get("stop_reason"),
            "terminal_reason": payload.get("terminal_reason"),
            "num_turns": payload.get("num_turns"),
            "duration_ms": payload.get("duration_ms"),
            "permission_denials": payload.get("permission_denials") or [],
            "api_error_status": payload.get("api_error_status"),
            "model_usage": model_usage,
        }

        return self._classify(payload, outcome)

    @staticmethod
    def _classify(payload: dict[str, Any], outcome: DispatchOutcome) -> DispatchOutcome:
        """Map the CLI's own status vocabulary onto FailureKind."""
        if payload.get("api_error_status"):
            return outcome.with_failure(FailureKind.PROVIDER_ERROR)
        if payload.get("stop_reason") == "max_tokens":
            # Real work may exist on disk; the executor decides partial vs
            # failed once it has seen which outputs landed.
            outcome.failure_kind = FailureKind.TRUNCATED
            outcome.status = AttemptStatus.PARTIAL
            return outcome
        if payload.get("is_error") or payload.get("subtype") not in (None, "success"):
            kind = (
                FailureKind.TOOL_ERROR
                if payload.get("permission_denials")
                else FailureKind.PROVIDER_ERROR
            )
            return outcome.with_failure(kind)
        # NOTE: a non-empty `permission_denials` on an otherwise clean run does
        # NOT downgrade the status. Observed live: a subagent was denied one
        # tool, worked around it, and produced correct output — marking that
        # partial triggered a retry that would have doubled the cost for
        # nothing. Denials stay in provider_meta as a signal; whether the work
        # is good is decided by the output contract and the acceptance checks,
        # which inspect what actually landed on disk.
        return outcome

    @staticmethod
    def _aggregate_usage(model_usage: dict[str, Any], fallback: dict[str, Any]) -> TokenUsage:
        """Sum `modelUsage` across every model the dispatch actually used.

        A dispatch can touch more than one model (`--fallback-model`), so this
        sums rather than taking the first entry. Falls back to the last-message
        `usage` block only when `modelUsage` is absent, and that path is known
        to under-count — it is a floor, not an estimate.
        """
        if model_usage:
            usage = TokenUsage()
            for entry in model_usage.values():
                if not isinstance(entry, dict):
                    continue
                usage.input_tokens += int(entry.get("inputTokens") or 0)
                usage.output_tokens += int(entry.get("outputTokens") or 0)
                usage.cache_read_tokens += int(entry.get("cacheReadInputTokens") or 0)
                # The aggregate does not break cache writes down by TTL. The
                # observed TTL for this CLI is 1h, and cost comes from the
                # provider anyway, so attribution here only affects window
                # accounting, where the total is what matters.
                usage.cache_write_1h_tokens += int(entry.get("cacheCreationInputTokens") or 0)
            return usage

        details = fallback.get("output_tokens_details") or {}
        creation = fallback.get("cache_creation") or {}
        return TokenUsage(
            input_tokens=int(fallback.get("input_tokens") or 0),
            output_tokens=int(fallback.get("output_tokens") or 0),
            thinking_tokens=int(details.get("thinking_tokens") or 0),
            cache_read_tokens=int(fallback.get("cache_read_input_tokens") or 0),
            cache_write_5m_tokens=int(creation.get("ephemeral_5m_input_tokens") or 0),
            cache_write_1h_tokens=int(creation.get("ephemeral_1h_input_tokens") or 0),
        )

    @staticmethod
    def _primary_model(model_usage: dict[str, Any]) -> str | None:
        """The model that produced the most output — the one that did the work
        if a fallback kicked in partway."""
        if not model_usage:
            return None
        return max(
            model_usage.items(),
            key=lambda item: (item[1] or {}).get("outputTokens", 0)
            if isinstance(item[1], dict)
            else 0,
        )[0]

    # -- dry run ------------------------------------------------------------

    def preview(self, request: DispatchRequest) -> DispatchPreview:
        argv = self.build_argv(request)
        notes: list[str] = []
        if request.task.inputs.artifacts:
            notes.append(
                f"reads {len(request.task.inputs.artifacts)} full artifact(s) from upstream"
            )
        notes.append("~30k cache-creation tokens of CLI system-prompt overhead per spawn")
        return DispatchPreview(
            task_id=request.task.id,
            attempt=request.attempt,
            adapter=self.name,
            tier_final=request.tier_final,
            model=request.model,
            target=" ".join(argv),
            prompt_bytes=len(request.prompt.encode()),
            estimated_input_tokens=estimate_tokens(request.prompt),
            timeout_s=request.timeout_s,
            workspace=request.workspace.rel_dir,
            notes=notes,
        )


__all__ = ["ClaudeAdapter"]
