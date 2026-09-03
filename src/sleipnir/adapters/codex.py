"""Codex adapter — shells out to `codex exec`.

The default invocation and JSONL usage shape were verified against Codex CLI
0.148.0 on 2026-08-18.  The invocation remains configuration
(:class:`CodexInvocation`) so future CLI changes do not leak into dispatch
logic, and the parser remains structure-agnostic because event envelopes can
change independently of their usage payload.

Auth is the CLI's own. Sleipnir never touches OpenAI credentials.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from sleipnir import platform
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
_CACHE_READ_KEYS = (
    "cached_input_tokens",
    "cached_tokens",
    "cache_read_input_tokens",
    "cacheReadInputTokens",
)
_REASONING_KEYS = (
    "reasoning_output_tokens",
    "reasoning_tokens",
    "thinking_tokens",
    "reasoningTokens",
)

#: Configuration sentinel for subscription-backed Codex CLI runs that should
#: use the operator's installed CLI/account default.  It is deliberately not a
#: model alias: aliases age out, while the authenticated CLI can negotiate a
#: supported default without Sleipnir needing to know account entitlements.
CODEX_CLI_DEFAULT_MODEL = "@cli-default"


@dataclass(slots=True)
class CodexInvocation:
    """How to call the CLI. Data, not dispatch logic."""

    executable: str = "codex"
    subcommand: tuple[str, ...] = ("exec",)
    model_flag: str = "--model"
    json_flag: str | None = "--json"
    extra_args: list[str] = field(
        default_factory=lambda: [
            "--approve-for-me",
            "--skip-git-repo-check",
        ]
    )
    prompt_via: Literal["stdin", "argv"] = "stdin"

    def __post_init__(self) -> None:
        # CreateProcess resolves a bare name's ".exe" for us but not a
        # ".cmd"/".bat" shim -- which is exactly what an npm-installed CLI
        # like codex is. Resolved once here, at construction, rather than
        # per dispatch: shutil.which() is a PATH walk, and every dispatch
        # already re-reads self.invocation.executable through argv().
        # Idempotent and inert everywhere else: a name already on PATH
        # resolves to itself in substance, and a name not found (e.g. a
        # test's "fake-codex") is returned unchanged.
        self.executable = platform.resolve_executable(self.executable)

    def argv(self, model: str, prompt: str) -> list[str]:
        argv = [self.executable, *self.subcommand]
        if model != CODEX_CLI_DEFAULT_MODEL:
            argv.extend((self.model_flag, model))
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
                env=self._subprocess_env(request.env),
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
                input_tokens = _first_int(node, _INPUT_KEYS)
                cache_read_tokens = _first_int(node, _CACHE_READ_KEYS)
                candidate = TokenUsage(
                    # Codex/OpenAI reports cached input as a subset of input,
                    # while TokenUsage stores disjoint billing channels.
                    input_tokens=max(0, input_tokens - cache_read_tokens),
                    output_tokens=_first_int(node, _OUTPUT_KEYS),
                    cache_read_tokens=cache_read_tokens,
                    thinking_tokens=min(
                        _first_int(node, _REASONING_KEYS),
                        _first_int(node, _OUTPUT_KEYS),
                    ),
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
            notes=["codex exec JSONL surface verified with Codex CLI 0.148.0"],
        )


def _first_int(node: dict[str, Any], keys: tuple[str, ...]) -> int:
    for key in keys:
        value = node.get(key)
        if isinstance(value, int | float):
            return int(value)
    return 0


__all__ = ["CODEX_CLI_DEFAULT_MODEL", "CodexAdapter", "CodexInvocation"]
