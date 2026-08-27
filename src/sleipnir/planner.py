"""Decomposition: one prompt in, a validated task DAG out.

The planner is itself a dispatched task. It builds a synthetic `Task` whose
declared output is `plan.json`, sends it through the ordinary adapter path, and
validates what comes back against the real schema. Reusing the executor's own
machinery means the planning call gets the same artifact layout, the same
timeout and cancellation handling, and the same cost accounting as any other
dispatch — and it is testable with the same fakes.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from sleipnir.adapters.base import BaseAdapter, DispatchRequest
from sleipnir.artifacts import AttemptWorkspace, contained_regular_file
from sleipnir.schema import (
    Adapter,
    ExpectedOutput,
    InputContract,
    OutputContract,
    OutputKind,
    Plan,
    RoutingDecision,
    Task,
    Tier,
)

PLANNER_TASK_ID = "sleipnir-plan"  # leading underscore is not a legal TaskId
PLAN_OUTPUT = "plan.json"

_FENCED_JSON = re.compile(r"```(?:json)?\s*\n(?P<body>.*?)```", re.DOTALL)


class PlanningError(RuntimeError):
    """The planner did not return a usable DAG."""


def planning_instructions(goal: str) -> str:
    """The decomposition brief.

    Written to steer toward the economics the whole system exists for: tasks
    sized so a cheap tier can finish them, and dependencies that pass bounded
    summaries rather than whole artifacts.
    """
    return f"""You are decomposing a project into a task DAG for a budget-aware orchestrator.

# The project
{goal.strip()}

# What to produce
Write `{PLAN_OUTPUT}` containing a JSON object: {{"tasks": [ ... ]}}

Each task object has these fields:
  id            short stable slug, lowercase, e.g. "schema" or "api-routes"
  description   one clear paragraph. This is the ONLY instruction the worker gets.
  tier          exactly one of: reason, code, mechanical, extract, longctx
  depends_on    list of task ids this task needs finished first
  inputs        {{"summaries": [ids whose ~200-token summary suffices],
                 "artifacts": [{{"task_id": id, "path": "relative/path",
                               "reason": "why a summary is not enough"}}]}}
  outputs       {{"outputs": [{{"name": slug, "kind": "file"|"patch"|"json"|"text",
                              "path": "relative/path", "required": true,
                              "description": "..."}}]}}
  acceptance    optional list, e.g. [{{"type": "command", "command": "pytest -q"}}]
                or [{{"type": "file_exists", "outputs": ["name"]}}]
  no_downshift  optional true if this task must never run on a cheaper tier

# Tier meanings — choose the CHEAPEST tier that can actually do the job
  reason      architecture, decomposition, ambiguous judgment
  code        bulk implementation against a clear spec
  mechanical  renames, formatting, boilerplate, deterministic transforms
  extract     summarization, parsing, structured extraction
  longctx     digesting large inputs

# Rules
- Every id in depends_on and in inputs.summaries MUST be another task's id.
- A task may only list a dependency's summary if it declares that dependency.
- No cycles.
- Prefer many small tasks with clear contracts over few vague ones. A task
  whose description a `code`-tier model cannot follow alone is too big.
- Depend on summaries, not full artifacts. A summary is ~200 tokens and is all
  most consumers need.
- But a task whose acceptance command EXECUTES a dependency's output — importing
  it, compiling it, linking it — needs the file itself, not a description of it.
  Declare it under inputs.artifacts. Each task runs in its own directory, so an
  undeclared file is simply absent and no attempt at that task can ever pass.
- Only name an acceptance command that will be installed on the machine running
  the plan. A plan naming a program that is not on PATH is refused before any
  task is dispatched.
- Give every task at least one required output with a concrete file path.
- Keep each task description at 600 characters or fewer. Split work that
  needs more instruction into dependent tasks instead of exceeding the schema.
- Artifact references default to a combined 262144-byte input cap. Request a
  larger explicit `inputs.max_input_bytes` only when it is truly necessary.

Write only `{PLAN_OUTPUT}`. No commentary."""


#: The schema's ceiling for a task's instructions.
_INSTRUCTION_LIMIT = 4_000
_CLIPPED = " …[goal truncated]"


def _fit_goal(goal: str) -> str:
    """Clip the goal, never the rules that follow it.

    The goal is interpolated near the top of the prompt, so clipping the
    assembled string kept the goal and discarded the output contract and every
    rule — leaving the planner asked for a plan with no definition of one.
    """
    budget = _INSTRUCTION_LIMIT - len(planning_instructions("")) - len(_CLIPPED)
    return goal if len(goal) <= budget else goal[:budget] + _CLIPPED


def build_planner_task(goal: str) -> Task:
    return Task(
        id=PLANNER_TASK_ID,
        description="Decompose the project prompt into a validated task DAG.",
        tier=Tier.REASON,
        inputs=InputContract(instructions=planning_instructions(_fit_goal(goal))),
        outputs=OutputContract(
            outputs=[
                ExpectedOutput(
                    name="plan",
                    kind=OutputKind.JSON,
                    path=PLAN_OUTPUT,
                    description="The task DAG as {\"tasks\": [...]}.",
                )
            ]
        ),
        no_downshift=True,  # decomposition is the one job worth the expensive tier
        timeout_s=900,
    )


def extract_plan_json(text: str) -> dict | None:
    """Pull a JSON object out of a model response.

    Tries the whole response first, then fenced blocks. Models wrap JSON in
    prose often enough that failing on the first attempt is not evidence the
    model got it wrong.
    """
    for candidate in (text, *(m.group("body") for m in _FENCED_JSON.finditer(text))):
        candidate = candidate.strip()
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def assemble_plan(payload: dict, *, goal: str, plan_id: str) -> Plan:
    """Validate the model's task list into a real Plan.

    The model supplies only `tasks`; identity and provenance are ours. Every
    schema invariant — acyclicity, referential closure, contract consistency —
    is enforced here, so an unusable plan fails now rather than at task 40.
    """
    tasks = payload.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise PlanningError(
            f"expected a non-empty 'tasks' list, got {type(payload.get('tasks')).__name__}"
        )
    try:
        return Plan(
            plan_id=plan_id,
            goal=goal,
            created_at=datetime.now(UTC),
            tasks=tasks,
        )
    except ValidationError as exc:
        raise PlanningError(f"the generated DAG is invalid:\n{exc}") from exc


async def generate_plan(
    goal: str,
    *,
    adapters: Mapping[Adapter, BaseAdapter],
    routing: RoutingDecision,
    run_root: Path,
    plan_id: str = "plan",
    attempt: int = 1,
    env: Mapping[str, str] | None = None,
    run_id: str = "plan-run",
) -> tuple[Plan, Path]:
    """Dispatch the planning task and return the validated Plan."""
    fitted_goal = _fit_goal(goal)
    task = build_planner_task(fitted_goal)
    adapter = adapters.get(routing.adapter)
    if adapter is None:
        raise PlanningError(f"no adapter registered for {routing.adapter.value!r}")

    workspace = AttemptWorkspace(run_root, task.id, attempt)
    workspace.prepare_fresh()
    request = DispatchRequest(
        task=task,
        attempt=attempt,
        tier_final=routing.tier_final,
        model=routing.model,
        prompt=planning_instructions(fitted_goal),
        workspace=workspace,
        timeout_s=float(task.timeout_s),
        env=env or {},
        run_id=run_id,
    )

    outcome = await adapter.dispatch(request)

    written = workspace.dir / PLAN_OUTPUT
    payload: dict | None = None
    if contained_regular_file(written, workspace.dir):
        payload = extract_plan_json(written.read_text(encoding="utf-8", errors="replace"))
    if payload is None:
        payload = extract_plan_json(outcome.response_text)
    if payload is None:
        raise PlanningError(
            f"the planner produced no parseable JSON "
            f"(status={outcome.status.value}, failure={outcome.failure_kind}). "
            f"Full output: {workspace.rel('stdout.log')}"
        )

    return assemble_plan(payload, goal=fitted_goal, plan_id=plan_id), written


__all__ = [
    "PLANNER_TASK_ID",
    "PLAN_OUTPUT",
    "PlanningError",
    "assemble_plan",
    "build_planner_task",
    "extract_plan_json",
    "generate_plan",
    "planning_instructions",
]
