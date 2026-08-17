"""Codex adapter — shells out to `codex exec`.

**Unverified surface.** `codex` is not installed in the environment this was
written in, so unlike the Claude adapter the flags below could not be checked
against a real `--help`. Rather than hardcode a guess, the entire invocation is
*configuration* (:class:`CodexInvocation`): if the real CLI disagrees, correct
the dataclass, not this module's logic. The parsing is written defensively for
the same reason — it scans for usage rather than assuming a key path, and says
so explicitly when it finds none.

Auth is the CLI's own. Sleipnir never touches OpenAI credentials.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

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

#: Key aliases seen across OpenAI-compatible tooling. The scan below accepts
#: any of them so a naming change does not silently zero the budget.
_INPUT_KEYS = ("input_tokens", "prompt_tokens", "inputTokens", "promptTokens")
_OUTPUT_KEYS = ("output_tokens", "completion_tokens", "outputTokens", "completionTokens")
_CACHE_READ_KEYS = ("cached_tokens", "cache_read_input_tokens", "cacheReadInputTokens")
_REASONING_KEYS = ("reasoning_tokens", "thinking_tokens", "reasoningTokens")


@dataclass(slots=True)
class CodexInvocation:
    """How to call the CLI. Data, not code — correct this after verifying."""

    executable: str = "codex"
    subcommand: tuple[str, ...] = ("exec",)
    model_flag: str = "--model"
    json_flag: str | None = "--json"
    extra_args: list[str] = field(default_factory=list)
    prompt_via: Literal["stdin", "argv"] = "stdin"

    def argv(self, model: str, prompt: str) -> list[str]:
        argv = [self.executable, *self.subcommand, self.model_flag, model]
        if self.json_flag:
            argv.append(self.json_flag)
        argv.extend(self.extra_args)
        if self.prompt_via == "argv":
            argv.append(prompt)
        return argv


class CodexAdapter(BaseAdapter):
    name = Adapter.CODEX

    def __init__(
        self,
        *,
        invocation: CodexInvocation | None = None,
        billing_mode: BillingMode = BillingMode.SUBSCRIPTION,
        spawn: Spawner | None = None,
    ) -> None:
        self.invocation = invocation or CodexInvocation()
        self.billing_mode = billing_mode
        self._runner = ProcessRunner(spawn=spawn)

    async def dispatch(self, request: DispatchRequest) -> DispatchOutcome:
        workspace = request.workspace
        workspace.prepare()
        workspace.write_text("prompt.txt", request.prompt)

        argv = self.invocation.argv(request.model, request.prompt)
        stdin_data = request.prompt if self.invocation.prompt_via == "stdin" else None

        try:
            result = await self._runner.run(
                argv,
                stdout_path=workspace.stdout_path,
                stderr_path=workspace.stderr_path,
                cwd=workspace.dir,
                env=request.env or None,
                stdin_data=stdin_data,
                timeout_s=request.timeout_s,
                grace_s=request.grace_s,
            )
        except asyncio.CancelledError:
            raise
        except FileNotFoundError as exc:
            return DispatchOutcome(
                status=AttemptStatus.FAILED,
                failure_kind=FailureKind.ADAPTER_ERROR,
                billing_mode=self.billing_mode,
                stderr_tail=f"{self.invocation.executable} not found on PATH: {exc}",
            )

        outcome = self._parse(workspace.stdout_path)
        outcome.billing_mode = self.billing_mode
        outcome.exit_code = result.exit_code
        outcome.stderr_tail = result.stderr_tail
        outcome.model_used = outcome.model_used or request.model

        if result.timed_out:
            outcome.status = AttemptStatus.FAILED
            outcome.failure_kind = FailureKind.TIMEOUT
        elif result.exit_code not in (0, None):
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

    def _parse(self, stdout_path: Path) -> DispatchOutcome:
        outcome = DispatchOutcome(status=AttemptStatus.SUCCEEDED)
        if not stdout_path.exists():
            return outcome.with_failure(FailureKind.PROVIDER_ERROR)

        events: list[dict[str, Any]] = []
        text_parts: list[str] = []
        for line in stdout_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                # Non-JSON line: the CLI was run without its JSON flag, or it
                # interleaves human output. Keep it as response text.
                text_parts.append(line)
                continue
            if isinstance(payload, dict):
                events.append(payload)

        usage, found = self._scan_usage(events)
        outcome.usage = usage
        outcome.response_text = "\n".join(text_parts)[-4_000:]
        outcome.provider_meta = {
            "events": len(events),
            "usage_found": found,
            "last_event": events[-1] if events else None,
        }
        if not found:
            # Explicit, not silent. A zeroed usage record would make the budget
            # governor believe this dispatch was free.
            outcome.provider_meta["warning"] = (
                "no usage block recognised in codex output; token counts are "
                "unknown and cost must be treated as unmeasured"
            )
        return outcome

    @staticmethod
    def _scan_usage(events: list[dict[str, Any]]) -> tuple[TokenUsage, bool]:
        """Walk every event for the last recognisable usage block.

        Deliberately structure-agnostic: it recurses rather than indexing a
        known path, because that path is exactly what could not be verified.
        """
        usage = TokenUsage()
        found = False

        def visit(node: Any) -> None:
            nonlocal found, usage
            if isinstance(node, list):
                for item in node:
                    visit(item)
                return
            if not isinstance(node, dict):
                return
            if any(key in node for key in _INPUT_KEYS + _OUTPUT_KEYS):
                candidate = TokenUsage(
                    input_tokens=_first_int(node, _INPUT_KEYS),
                    output_tokens=_first_int(node, _OUTPUT_KEYS),
                    cache_read_tokens=_first_int(node, _CACHE_READ_KEYS),
                )
                details = node.get("output_tokens_details") or node.get("completion_tokens_details")
                if isinstance(details, dict):
                    thinking = _first_int(details, _REASONING_KEYS)
                    candidate.thinking_tokens = min(thinking, candidate.output_tokens)
                if candidate.total_tokens:
                    usage, found = candidate, True
            for value in node.values():
                visit(value)

        for event in events:
            visit(event)
        return usage, found

    def preview(self, request: DispatchRequest) -> DispatchPreview:
        argv = self.invocation.argv(request.model, "<prompt via stdin>")
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
            notes=["codex CLI surface is UNVERIFIED — confirm flags before trusting a real run"],
        )


def _first_int(node: dict[str, Any], keys: tuple[str, ...]) -> int:
    for key in keys:
        value = node.get(key)
        if isinstance(value, int | float):
            return int(value)
    return 0


__all__ = ["CodexAdapter", "CodexInvocation"]
