"""Sparse Claude control cycles over the bounded manifest.

Workers execute autonomously.  The expensive brain is called only when the DAG
reaches a terminal decision point it cannot resolve itself, and it sees exactly
the capped Manifest—never artifact contents or accumulated transcripts.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sleipnir.adapters.base import BaseAdapter, DispatchOutcome, DispatchRequest
from sleipnir.artifacts import AttemptWorkspace, contained_regular_file
from sleipnir.schema import (
    Adapter,
    ExpectedOutput,
    Manifest,
    OutputContract,
    OutputKind,
    RevisionChange,
    RoutingDecision,
    Task,
    Tier,
    Plan,
)

CONTROL_TASK_ID = "sleipnir-control"
CONTROL_OUTPUT = "decision.json"
_FENCED_JSON = re.compile(r"```(?:json)?\s*\n(?P<body>.*?)```", re.DOTALL)


class ControlError(RuntimeError):
    """The control model did not produce a safe, usable decision."""

    def __init__(
        self,
        message: str,
        *,
        outcome: DispatchOutcome | None = None,
        output: Path | None = None,
    ) -> None:
        super().__init__(message)
        self.outcome = outcome
        self.output = output


class ControlAction(StrEnum):
    CONTINUE = "continue"
    REVISE = "revise"
    STOP = "stop"


class ControlDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: ControlAction
    reason: str = Field(min_length=8, max_length=1_000)
    changes: list[RevisionChange] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def _changes_match_action(self):
        if self.action is ControlAction.REVISE and not self.changes:
            raise ValueError("revise requires at least one change")
        if self.action is not ControlAction.REVISE and self.changes:
            raise ValueError("only revise may carry changes")
        return self


def control_plan_context(
    plan: Plan, manifest: Manifest, *, max_tasks: int = 4, max_chars: int = 24_000
) -> str:
    """Constant-bounded full specs for urgent frontier tasks only."""
    included: list[dict] = []
    used = 2
    omitted: list[str] = []
    for entry in manifest.frontier[:max_tasks]:
        task = plan.by_id.get(entry.id)
        if task is None:
            continue
        payload = task.model_dump(mode="json")
        encoded = json.dumps(payload, separators=(",", ":"))
        if used + len(encoded) + 1 > max_chars:
            omitted.append(entry.id)
            continue
        included.append(payload)
        used += len(encoded) + 1
    return json.dumps(
        {"tasks": included, "omitted_due_to_cap": omitted}, separators=(",", ":")
    )


def control_instructions(manifest: Manifest, plan: Plan | None = None) -> str:
    change_schema = RevisionChange.model_json_schema()
    return f"""You are the scarce orchestration brain for Sleipnir.

You see ONLY the bounded manifest below. Never ask for artifact contents or
worker transcripts. Workers have already exhausted every automatic retry that
was safe. Choose one action:

- continue: only when the unchanged plan can make new progress on a later run.
- revise: repair the DAG with the smallest valid list of revision changes.
- stop: the goal is complete, unsafe, budget-blocked, or needs human input.

For retarget_task, provide the complete task but change routing fields only
(tier, priority, timeout_s, retry, adapter_hint, group). For respec_task or
add_task, provide the complete replacement task. Edge operations use
dependency_id. Do not smuggle worker output into any task field.

Write `{CONTROL_OUTPUT}` as JSON matching:
{{"action":"continue|revise|stop","reason":"...","changes":[]}}

RevisionChange JSON Schema:
{json.dumps(change_schema, separators=(',', ':'))}

Bounded manifest ({manifest.estimate_tokens()} estimated tokens):
{manifest.model_dump_json()}

Bounded on-demand frontier task specs (never artifact content):
{control_plan_context(plan, manifest) if plan is not None else '{"tasks":[],"omitted_due_to_cap":[]}'}
"""


def build_control_task(manifest: Manifest, plan: Plan | None = None) -> Task:
    prompt = control_instructions(manifest, plan)
    return Task(
        id=CONTROL_TASK_ID,
        description="Choose the next safe harness action from the bounded run manifest.",
        tier=Tier.REASON,
        outputs=OutputContract(outputs=[ExpectedOutput(
            name="decision",
            kind=OutputKind.JSON,
            path=CONTROL_OUTPUT,
            description="A continue, revise, or stop control decision.",
        )]),
        no_downshift=True,
        timeout_s=900,
        inputs={"instructions": prompt[:4_000]},
    )


def _extract_decision(text: str) -> ControlDecision | None:
    for candidate in (text, *(match.group("body") for match in _FENCED_JSON.finditer(text))):
        try:
            return ControlDecision.model_validate_json(candidate.strip())
        except ValueError:
            continue
    return None


async def run_control_cycle(
    manifest: Manifest,
    *,
    plan: Plan | None = None,
    adapters: Mapping[Adapter, BaseAdapter],
    routing: RoutingDecision,
    run_root: Path,
    attempt: int,
    env: Mapping[str, str],
    run_id: str,
) -> tuple[ControlDecision, DispatchOutcome, Path]:
    task = build_control_task(manifest, plan)
    adapter = adapters.get(routing.adapter)
    if adapter is None:
        raise ControlError(f"no adapter registered for {routing.adapter.value!r}")
    workspace = AttemptWorkspace(run_root, task.id, attempt)
    workspace.prepare_fresh()
    prompt = control_instructions(manifest, plan)
    request = DispatchRequest(
        task=task,
        attempt=attempt,
        tier_final=routing.tier_final,
        model=routing.model,
        prompt=prompt,
        workspace=workspace,
        timeout_s=float(task.timeout_s),
        env=env,
        run_id=run_id,
    )
    outcome = await adapter.dispatch(request)
    output = workspace.dir / CONTROL_OUTPUT
    decision = None
    if contained_regular_file(output, workspace.dir):
        decision = _extract_decision(output.read_text(encoding="utf-8", errors="replace"))
    if decision is None:
        decision = _extract_decision(outcome.response_text)
    if decision is None:
        raise ControlError(
            f"control model produced no valid decision; inspect {workspace.rel('stdout.log')}",
            outcome=outcome,
            output=output,
        )
    return decision, outcome, output


__all__ = [
    "CONTROL_OUTPUT", "CONTROL_TASK_ID", "ControlAction", "ControlDecision",
    "ControlError", "build_control_task", "control_instructions", "control_plan_context",
    "run_control_cycle",
]
