"""Sleipnir state schema.

Three on-disk shapes plus one derived shape:

    plan.json       the task DAG. Versioned, revised by append, never rewritten
                    in place. Declares *tiers*, never concrete models.
    results.jsonl   append-only log of attempt records. The only source of
                    truth for what has happened. Task status is a *fold* of
                    this file over the plan, never a stored field.
    revisions.jsonl append-only log of plan revisions, so mid-run re-planning
                    is auditable and completed work is provably preserved.
    Manifest        derived, never stored as truth. The ONLY thing the
                    orchestrator model sees on re-invocation. Its serialized
                    size is bounded by construction — see ManifestCaps and
                    Manifest.estimate_tokens().

Design rationale, tradeoffs, and the manifest size math live in DESIGN.md.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath, PureWindowsPath
from typing import Annotated, Any, ClassVar, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

SCHEMA_VERSION = 1

_RESERVED_WORKSPACE_PATHS = frozenset(
    {
        "summary.md",
        "prompt.txt",
        "input-manifest.json",
        "stdout.log",
        "stderr.log",
        "outcome.json",
    }
)

# ---------------------------------------------------------------------------
# Token accounting helper
# ---------------------------------------------------------------------------

#: Chars-per-token heuristic. Deliberately NOT a real tokenizer: pulling in
#: tiktoken/anthropic-tokenizers for a budget *bound* would be a dependency we
#: do not need. Every cap in this module is enforced in characters (exact,
#: cheap, deterministic); token numbers are advisory and stated as estimates.
#: 3.6 is conservative for English prose + JSON punctuation, which tokenizes
#: denser than the usual "4 chars/token" rule of thumb.
CHARS_PER_TOKEN = 3.6


def estimate_tokens(text: str) -> int:
    """Estimated token count for ``text``. Conservative (over-estimates)."""
    return int(len(text) / CHARS_PER_TOKEN) + 1


def _canonical_json(payload: Any) -> str:
    """Stable JSON encoding for hashing: sorted keys, no incidental whitespace."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _escapes_workspace(value: str) -> bool:
    """True when ``value`` is not safely relative -- an absolute path, a
    drive-qualified path, a UNC share, or one that walks upward out of the
    workspace it is meant to stay inside.

    Every one of these strings is model- or plan-authored, so this is a
    security boundary, not a portability nicety, and it has to reject an
    escape shaped for *either* platform's conventions regardless of which
    platform Sleipnir is running on -- a plan written on Linux and run on
    Windows (or vice versa) must be validated the same way either place.
    Checking ``value.startswith("/")`` alone -- what this validated before --
    passes ``C:\\Windows\\System32\\...``, ``\\\\server\\share\\...``, and
    ``..\\..\\secret`` straight through, because none of them start with a
    forward slash; ``PurePath.is_absolute()`` on each of a POSIX and a
    Windows path object, plus a walk-upward check across *both* separators,
    is what actually closes that.
    """
    if not value:
        return True
    if PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute():
        return True
    if re.match(r"^[A-Za-z]:", value):
        # A drive-relative Windows path ("C:foo"): not is_absolute() by
        # PureWindowsPath's own definition (it is relative to that drive's
        # current directory, not a fixed location), but naming a drive at
        # all is not something a workspace-relative path should ever need
        # to do.
        return True
    parts = re.split(r"[/\\]", value)
    return ".." in parts


# ---------------------------------------------------------------------------
# Identifiers
# ---------------------------------------------------------------------------

_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,63}$"

#: Task ids are path-safe by construction because they are interpolated into
#: ``artifacts/task-<id>/``. No slashes, no dots-only, no leading separator.
TaskId = Annotated[str, StringConstraints(pattern=_ID_PATTERN)]
GroupId = Annotated[str, StringConstraints(pattern=_ID_PATTERN)]


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Tier(StrEnum):
    """Capability classes. A plan declares a tier; the router resolves a model.

    Fixed at five by architect decision. Adding a sixth requires sign-off.
    """

    REASON = "reason"  # architecture, decomposition, ambiguous judgment
    CODE = "code"  # bulk implementation against a clear spec
    MECHANICAL = "mechanical"  # renames, formatting, deterministic transforms
    EXTRACT = "extract"  # summarization, parsing, structured extraction
    LONGCTX = "longctx"  # digesting large inputs


#: Cheapness order used by the budget governor when it downshifts. Strictly a
#: *default* ordering hint — the router owns the real decision and may refuse a
#: downshift that would violate a task's input-size requirements.
DOWNSHIFT_LADDER: tuple[Tier, ...] = (
    Tier.REASON,
    Tier.CODE,
    Tier.EXTRACT,
    Tier.MECHANICAL,
)


class Adapter(StrEnum):
    """Dispatch backends. Auth is always delegated to the official tool."""

    CLAUDE = "claude"  # Claude Agent SDK / `claude -p` headless
    CODEX = "codex"  # `codex exec`
    OPENROUTER = "openrouter"  # plain HTTP, metered


class TaskStatus(StrEnum):
    """Folded status. Computed from results.jsonl — never stored in plan.json."""

    BLOCKED = "blocked"  # at least one dependency not satisfied
    READY = "ready"  # deps satisfied, no attempt open
    RUNNING = "running"  # attempt_started with no terminal record
    DONE = "done"  # succeeded, all required outputs present and accepted
    PARTIAL = "partial"  # some required outputs present, some not
    FAILED = "failed"  # terminal failure, retries exhausted
    SKIPPED = "skipped"  # deliberately not run (e.g. dependency failed)
    STALE = "stale"  # completed, but an upstream spec changed under it
    SUPERSEDED = "superseded"  # this task's own spec changed after completion
    CANCELLED = "cancelled"  # operator or budget cancelled it


#: Statuses that count as "this task produced usable output".
SATISFIED_STATUSES: frozenset[TaskStatus] = frozenset(
    {TaskStatus.DONE, TaskStatus.STALE}
)


class AttemptStatus(StrEnum):
    """Outcome of a single attempt. Deliberately small — *why* lives in FailureKind."""

    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FailureKind(StrEnum):
    """Why an attempt did not fully succeed.

    Separated from AttemptStatus so retry policy can key on cause: a TIMEOUT is
    worth retrying, an ACCEPTANCE_FAILED is worth escalating a tier, and a
    BUDGET_DENIED must never be retried at the same tier.
    """

    TIMEOUT = "timeout"
    TRUNCATED = "truncated"  # hit an output-token ceiling mid-work
    ACCEPTANCE_FAILED = "acceptance_failed"
    PROVIDER_ERROR = "provider_error"  # 5xx, rate limit, CLI crash
    TOOL_ERROR = "tool_error"  # subagent's own tool calls failed
    ADAPTER_ERROR = "adapter_error"  # our bug: bad spawn, bad parse
    BUDGET_DENIED = "budget_denied"  # governor refused to dispatch
    INTERRUPTED = "interrupted"  # process died; recovered by `resume`
    DEPENDENCY_FAILED = "dependency_failed"
    CANCELLED = "cancelled"


#: Failure kinds where retrying the identical dispatch is pointless.
NON_RETRYABLE: frozenset[FailureKind] = frozenset(
    {FailureKind.BUDGET_DENIED, FailureKind.CANCELLED, FailureKind.DEPENDENCY_FAILED}
)


class BillingMode(StrEnum):
    """How an attempt consumes budget.

    This split is load-bearing. A subscription-backed `claude -p` call has ~zero
    marginal dollar cost but consumes the 5-hour window quota. An OpenRouter
    call costs dollars and consumes no window. The governor optimizes over two
    scarce resources, not one, so every result records both.
    """

    SUBSCRIPTION = "subscription"  # spends window quota, not dollars
    METERED = "metered"  # spends dollars, not window quota


class OutputKind(StrEnum):
    FILE = "file"  # a written file at a known path
    PATCH = "patch"  # a unified diff to be applied
    JSON = "json"  # structured data, optionally schema-checked
    TEXT = "text"  # freeform prose artifact


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


class ArtifactRef(BaseModel):
    """A request for another task's *full* output rather than its summary.

    Three things keep this from becoming the default (see DESIGN.md Q1):

    1. ``reason`` is required and non-trivial — you must say why the 200-token
       summary is insufficient. The planner prompt is told this.
    2. ``max_bytes`` is mandatory and counts against the task's
       ``max_input_bytes``, so the cost is visible at plan time and feeds tier
       selection (a task pulling 400KB routes to ``longctx``).
    3. ``path`` must name specific files or a narrow glob. There is no
       "give me everything task X produced" form.

    Critically: artifact content is fed to the *subagent*, never to the
    orchestrator. Full output is a subagent-scoped privilege, so honoring one of
    these can never inflate the orchestrator's context.
    """

    model_config = ConfigDict(extra="forbid")

    task_id: TaskId
    path: str = Field(
        min_length=1,
        max_length=256,
        description="Path or narrow glob, relative to the producing task's artifact dir.",
    )
    reason: str = Field(
        min_length=16,
        max_length=400,
        description="Why the bounded summary is insufficient for this consumer.",
    )
    max_bytes: int = Field(default=65_536, gt=0, le=8_388_608)

    @field_validator("path")
    @classmethod
    def _path_is_contained(cls, value: str) -> str:
        if _escapes_workspace(value):
            raise ValueError("artifact path must be relative and must not escape upward")
        if value.strip() in {"*", "**", "**/*"}:
            raise ValueError(
                "wildcard-everything artifact refs are not allowed; name specific outputs"
            )
        return value

    @property
    def is_glob(self) -> bool:
        return any(ch in self.path for ch in "*?[")


class InputContract(BaseModel):
    """Everything a task is permitted to read. Nothing else is provided to it."""

    model_config = ConfigDict(extra="forbid")

    summaries: list[TaskId] = Field(
        default_factory=list,
        description="Dependencies whose ~200-token summary is enough. The cheap default.",
    )
    artifacts: list[ArtifactRef] = Field(
        default_factory=list,
        description="Dependencies whose full output is genuinely required.",
    )
    files: list[str] = Field(
        default_factory=list,
        description="Repository paths/globs the task may read, relative to the run root.",
    )
    instructions: str | None = Field(
        default=None,
        max_length=4_000,
        description="Task-specific context the planner wants injected verbatim.",
    )
    max_input_bytes: int = Field(default=262_144, gt=0, le=16_777_216)

    @field_validator("files")
    @classmethod
    def _files_are_contained(cls, values: list[str]) -> list[str]:
        for value in values:
            if _escapes_workspace(value):
                raise ValueError(
                    "input file paths/globs must be non-empty, relative, and must not escape upward"
                )
        return values

    @model_validator(mode="after")
    def _artifact_budget_fits(self) -> Self:
        requested = sum(ref.max_bytes for ref in self.artifacts)
        if requested > self.max_input_bytes:
            raise ValueError(
                f"artifact refs request {requested} bytes but max_input_bytes is "
                f"{self.max_input_bytes}; raise the cap explicitly or read less"
            )
        seen: set[tuple[str, str]] = set()
        for ref in self.artifacts:
            key = (ref.task_id, ref.path)
            if key in seen:
                raise ValueError(f"duplicate artifact ref {key}")
            seen.add(key)
        return self

    @property
    def declared_input_bytes(self) -> int:
        """Planner-declared upper bound on input size. Feeds tier selection."""
        return sum(ref.max_bytes for ref in self.artifacts)


class ExpectedOutput(BaseModel):
    """One item a task must produce. Named, so partial failure is expressible."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=_ID_PATTERN)
    kind: OutputKind
    path: str = Field(
        min_length=1,
        max_length=256,
        description="Path relative to artifacts/task-<id>/attempt-<n>/.",
    )
    required: bool = True
    description: str = Field(min_length=1, max_length=400)

    @field_validator("path")
    @classmethod
    def _contained(cls, value: str) -> str:
        if _escapes_workspace(value):
            raise ValueError("output path must be relative and must not escape upward")
        if value in _RESERVED_WORKSPACE_PATHS or value.startswith(".checks/"):
            raise ValueError("output path collides with a harness-owned workspace file")
        return value


class OutputContract(BaseModel):
    """What the task must produce, and how much of it may re-enter the manifest."""

    model_config = ConfigDict(extra="forbid")

    outputs: list[ExpectedOutput] = Field(min_length=1)
    summary_max_tokens: int = Field(
        default=200,
        gt=0,
        le=400,
        description="Hard cap on the summary that enters results.jsonl.",
    )

    @model_validator(mode="after")
    def _unique_names_and_paths(self) -> Self:
        names = [o.name for o in self.outputs]
        if len(set(names)) != len(names):
            raise ValueError("duplicate output names")
        paths = [o.path for o in self.outputs]
        if len(set(paths)) != len(paths):
            raise ValueError("duplicate output paths")
        if not any(o.required for o in self.outputs):
            raise ValueError("at least one output must be required")
        return self

    @property
    def required_names(self) -> frozenset[str]:
        return frozenset(o.name for o in self.outputs if o.required)


# ---------------------------------------------------------------------------
# Acceptance checks (discriminated union)
# ---------------------------------------------------------------------------


class CommandCheck(BaseModel):
    """Run a shell command; exit 0 passes.

    NOTE: this executes arbitrary code from plan.json. That is acceptable
    because the plan is generated on, and run on, the operator's own machine —
    but it means a plan file is executable content and must not be accepted
    from an untrusted source. Flagged in DESIGN.md.
    """

    model_config = ConfigDict(extra="forbid")
    type: Literal["command"] = "command"
    command: str = Field(min_length=1, max_length=2_000)
    cwd: str | None = None
    timeout_s: int = Field(default=120, gt=0, le=3_600)


class FileExistsCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["file_exists"] = "file_exists"
    outputs: list[str] = Field(
        min_length=1, description="ExpectedOutput names that must exist and be non-trivial."
    )
    min_bytes: int = Field(default=1, ge=0)


class JsonSchemaCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["json_schema"] = "json_schema"
    output: str = Field(description="ExpectedOutput name to validate.")
    json_schema: dict[str, Any]


class LlmJudgeCheck(BaseModel):
    """Rubric-graded check. Runs at `extract` tier by default — judging is cheap."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["llm_judge"] = "llm_judge"
    rubric: str = Field(min_length=16, max_length=2_000)
    tier: Tier = Tier.EXTRACT
    pass_threshold: float = Field(default=0.7, ge=0.0, le=1.0)


AcceptanceCheck = Annotated[
    CommandCheck | FileExistsCheck | JsonSchemaCheck | LlmJudgeCheck,
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Retry / escalation
# ---------------------------------------------------------------------------


class EscalationStep(BaseModel):
    """One rung of the escalation ladder, applied on the Nth retry."""

    model_config = ConfigDict(extra="forbid")
    tier: Tier
    note: str | None = Field(default=None, max_length=200)


class RetryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_attempts: int = Field(default=2, ge=1, le=6)
    retry_on: list[FailureKind] = Field(
        default_factory=lambda: [
            FailureKind.TIMEOUT,
            FailureKind.PROVIDER_ERROR,
            FailureKind.TRUNCATED,
            FailureKind.ACCEPTANCE_FAILED,
            FailureKind.INTERRUPTED,
        ]
    )
    escalation: list[EscalationStep] = Field(
        default_factory=list,
        description="Tier ladder applied on successive retries. Empty = retry same tier.",
    )
    reuse_partial: bool = Field(
        default=True,
        description="Feed the prior attempt's partial artifacts back in, so a retry "
        "resumes instead of restarting. See DESIGN.md Q2.",
    )
    backoff_s: float = Field(default=2.0, ge=0.0, le=120.0)
    backoff_factor: float = Field(default=2.0, ge=1.0, le=10.0)

    @model_validator(mode="after")
    def _sane(self) -> Self:
        if any(kind in NON_RETRYABLE for kind in self.retry_on):
            raise ValueError(
                f"retry_on contains a non-retryable kind: "
                f"{sorted(k for k in self.retry_on if k in NON_RETRYABLE)}"
            )
        if len(self.escalation) > self.max_attempts - 1:
            raise ValueError(
                "escalation ladder is longer than the number of retries available"
            )
        return self

    def tier_for_attempt(self, base_tier: Tier, attempt: int) -> Tier:
        """Tier to use on ``attempt`` (1-indexed). Falls back to ``base_tier``."""
        if attempt <= 1 or not self.escalation:
            return base_tier
        index = min(attempt - 2, len(self.escalation) - 1)
        return self.escalation[index].tier


# ---------------------------------------------------------------------------
# Task and Plan
# ---------------------------------------------------------------------------


class Task(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: TaskId
    group: GroupId = Field(
        default="default",
        description="Rollup bucket. Keeps the manifest constant-size as n grows.",
    )
    description: str = Field(min_length=8, max_length=600)
    tier: Tier
    depends_on: list[TaskId] = Field(default_factory=list)
    inputs: InputContract = Field(default_factory=InputContract)
    outputs: OutputContract
    acceptance: list[AcceptanceCheck] = Field(default_factory=list)
    retry: RetryPolicy = Field(default_factory=RetryPolicy)

    no_downshift: bool = Field(
        default=False,
        description="Governor may never route this below its declared tier.",
    )
    priority: int = Field(default=0, description="Higher runs first among ready tasks.")
    timeout_s: int = Field(default=900, gt=0, le=21_600)
    adapter_hint: Adapter | None = Field(
        default=None, description="Advisory. The router may override."
    )

    #: Fields whose change alters what the task *means*, and therefore
    #: invalidates completed work. Tier, priority, timeout, retry and
    #: adapter_hint are deliberately excluded: re-routing a task must not
    #: throw away its finished output. See DESIGN.md Q3.
    SEMANTIC_FIELDS: ClassVar[tuple[str, ...]] = (
        "id",
        "description",
        "depends_on",
        "inputs",
        "outputs",
        "acceptance",
    )

    @model_validator(mode="after")
    def _deps_consistent(self) -> Self:
        if self.id in self.depends_on:
            raise ValueError(f"task {self.id!r} depends on itself")
        if len(set(self.depends_on)) != len(self.depends_on):
            raise ValueError(f"task {self.id!r} has duplicate dependencies")
        declared = set(self.depends_on)
        # You may not read from a task you do not depend on. Without this, a
        # task could race its own input producer.
        for ref in self.inputs.artifacts:
            if ref.task_id not in declared:
                raise ValueError(
                    f"task {self.id!r} reads artifacts from {ref.task_id!r} "
                    "but does not declare it in depends_on"
                )
        for dep in self.inputs.summaries:
            if dep not in declared:
                raise ValueError(
                    f"task {self.id!r} reads the summary of {dep!r} "
                    "but does not declare it in depends_on"
                )
        known_outputs = {o.name for o in self.outputs.outputs}
        for check in self.acceptance:
            if isinstance(check, FileExistsCheck):
                missing = set(check.outputs) - known_outputs
                if missing:
                    raise ValueError(
                        f"task {self.id!r} file_exists check names undeclared outputs: "
                        f"{sorted(missing)}"
                    )
            elif isinstance(check, JsonSchemaCheck) and check.output not in known_outputs:
                raise ValueError(
                    f"task {self.id!r} json_schema check names undeclared output "
                    f"{check.output!r}"
                )
        return self

    def spec_hash(self) -> str:
        """Stable digest of the task's *meaning*.

        Completed results are keyed by (task_id, spec_hash). A revision that
        leaves this unchanged provably preserves completed work; one that
        changes it marks prior results superseded rather than deleting them.
        """
        payload = {
            field: self.model_dump(mode="json")[field] for field in self.SEMANTIC_FIELDS
        }
        return hashlib.sha256(_canonical_json(payload).encode()).hexdigest()[:16]

    @property
    def artifact_dir(self) -> str:
        return f"artifacts/task-{self.id}"

    def attempt_dir(self, attempt: int) -> str:
        """Attempts never share a directory, so a re-run can never clobber
        evidence from a prior attempt. This is what makes `resume` safe."""
        return f"{self.artifact_dir}/attempt-{attempt:02d}"


class PlanDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concurrency: int = Field(default=3, ge=1, le=32)
    task_timeout_s: int = Field(default=900, gt=0)
    summary_max_tokens: int = Field(default=200, gt=0, le=400)


class Plan(BaseModel):
    """The task DAG. Validated as acyclic and referentially closed on load."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = SCHEMA_VERSION
    plan_id: str = Field(pattern=_ID_PATTERN)
    goal: str = Field(min_length=1, max_length=4_000)
    created_at: datetime
    revision: int = Field(default=0, ge=0)
    defaults: PlanDefaults = Field(default_factory=PlanDefaults)
    tasks: list[Task] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_dag(self) -> Self:
        by_id: dict[str, Task] = {}
        for task in self.tasks:
            if task.id in by_id:
                raise ValueError(f"duplicate task id {task.id!r}")
            by_id[task.id] = task

        for task in self.tasks:
            for dep in task.depends_on:
                if dep not in by_id:
                    raise ValueError(f"task {task.id!r} depends on unknown task {dep!r}")

        # Exact (non-glob) artifact refs must name a real declared output of the
        # producer. Catches the most common planner typo at load time rather
        # than after a dispatch has already been paid for.
        for task in self.tasks:
            for ref in task.inputs.artifacts:
                if ref.is_glob:
                    continue
                producer = by_id[ref.task_id]
                if ref.path not in {o.path for o in producer.outputs.outputs}:
                    raise ValueError(
                        f"task {task.id!r} requests artifact {ref.path!r} from "
                        f"{ref.task_id!r}, which declares no such output"
                    )

        cycle = _find_cycle(by_id)
        if cycle:
            raise ValueError(f"plan contains a dependency cycle: {' -> '.join(cycle)}")
        return self

    @property
    def by_id(self) -> dict[str, Task]:
        return {task.id: task for task in self.tasks}

    @property
    def groups(self) -> list[str]:
        seen: dict[str, None] = {}
        for task in self.tasks:
            seen.setdefault(task.group, None)
        return list(seen)

    def spec_hashes(self) -> dict[str, str]:
        return {task.id: task.spec_hash() for task in self.tasks}

    def descendants(self, task_id: str) -> set[str]:
        """All tasks transitively downstream of ``task_id``."""
        children: dict[str, list[str]] = {t.id: [] for t in self.tasks}
        for task in self.tasks:
            for dep in task.depends_on:
                children[dep].append(task.id)
        out: set[str] = set()
        stack = list(children.get(task_id, []))
        while stack:
            current = stack.pop()
            if current in out:
                continue
            out.add(current)
            stack.extend(children.get(current, []))
        return out

    def topological_order(self) -> list[str]:
        by_id = self.by_id
        indegree = {tid: len(by_id[tid].depends_on) for tid in by_id}
        # Stable: higher priority first, then id, so runs are reproducible.
        ready = sorted(
            (t for t in by_id.values() if indegree[t.id] == 0),
            key=lambda t: (-t.priority, t.id),
        )
        order: list[str] = []
        queue = [t.id for t in ready]
        while queue:
            current = queue.pop(0)
            order.append(current)
            for task in self.tasks:
                if current in task.depends_on:
                    indegree[task.id] -= 1
                    if indegree[task.id] == 0:
                        queue.append(task.id)
                        queue.sort(key=lambda tid: (-by_id[tid].priority, tid))
        return order


def _find_cycle(by_id: dict[str, Task]) -> list[str] | None:
    """Return one concrete cycle as a readable path, or None. Iterative (deep
    DAGs must not blow the Python stack)."""
    WHITE, GREY, BLACK = 0, 1, 2
    color = dict.fromkeys(by_id, WHITE)
    parent: dict[str, str | None] = dict.fromkeys(by_id, None)

    for root in by_id:
        if color[root] != WHITE:
            continue
        stack: list[tuple[str, int]] = [(root, 0)]
        color[root] = GREY
        while stack:
            node, index = stack.pop()
            deps = by_id[node].depends_on
            if index < len(deps):
                stack.append((node, index + 1))
                nxt = deps[index]
                if color[nxt] == GREY:
                    path = [nxt, node]
                    walker = parent[node]
                    while walker is not None and path[-1] != nxt:
                        path.append(walker)
                        walker = parent[walker]
                    return list(reversed(path))
                if color[nxt] == WHITE:
                    color[nxt] = GREY
                    parent[nxt] = node
                    stack.append((nxt, 0))
            else:
                color[node] = BLACK
    return None


# ---------------------------------------------------------------------------
# Plan revision (mid-run re-planning)
# ---------------------------------------------------------------------------


class RevisionOp(StrEnum):
    ADD_TASK = "add_task"
    REMOVE_TASK = "remove_task"
    RETARGET_TASK = "retarget_task"  # non-semantic edit; completed work survives
    RESPEC_TASK = "respec_task"  # semantic edit; supersedes completed work
    ADD_EDGE = "add_edge"
    REMOVE_EDGE = "remove_edge"


class RevisionChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: RevisionOp
    task_id: TaskId
    detail: str = Field(max_length=400, default="")
    task: Task | None = Field(
        default=None,
        description="Complete replacement task for add, retarget, or respec operations.",
    )
    dependency_id: TaskId | None = Field(
        default=None, description="Dependency changed by add_edge or remove_edge."
    )

    @model_validator(mode="after")
    def _payload_matches_operation(self) -> Self:
        task_ops = {RevisionOp.ADD_TASK, RevisionOp.RETARGET_TASK, RevisionOp.RESPEC_TASK}
        edge_ops = {RevisionOp.ADD_EDGE, RevisionOp.REMOVE_EDGE}
        if (self.op in task_ops) != (self.task is not None):
            raise ValueError(f"{self.op.value} requires exactly one complete task payload")
        if self.task is not None and self.task.id != self.task_id:
            raise ValueError("revision task payload id must match task_id")
        if (self.op in edge_ops) != (self.dependency_id is not None):
            raise ValueError(f"{self.op.value} requires exactly one dependency_id")
        return self


class PlanRevision(BaseModel):
    """One append to revisions.jsonl. Makes re-planning auditable.

    ``superseded`` and ``staled`` are computed by the revision applier, not
    supplied by the model, so the blast radius of a re-plan is always recorded
    even when the orchestrator did not anticipate it.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = SCHEMA_VERSION
    revision: int = Field(ge=1)
    parent_revision: int = Field(ge=0)
    created_at: datetime
    reason: str = Field(min_length=8, max_length=1_000)
    changes: list[RevisionChange] = Field(min_length=1)
    superseded: list[TaskId] = Field(
        default_factory=list,
        description="Completed tasks whose own spec changed; results kept, status reset.",
    )
    staled: list[TaskId] = Field(
        default_factory=list,
        description="Completed tasks whose *upstream* spec changed. Output retained "
        "but flagged; re-running is an explicit decision.",
    )

    @model_validator(mode="after")
    def _revision_increments(self) -> Self:
        if self.revision != self.parent_revision + 1:
            raise ValueError("revisions must increment by exactly one")
        return self


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


class TokenUsage(BaseModel):
    """Token accounting, shaped to the *real* Claude usage record.

    Verified against ``~/.claude/projects/*.jsonl`` on 2026-08-17 (CLI 2.1.234).
    A representative turn reported::

        input_tokens: 2, cache_creation_input_tokens: 47052,
        cache_read_input_tokens: 0, output_tokens: 901,
        output_tokens_details.thinking_tokens: 611,
        cache_creation: {ephemeral_1h_input_tokens: 47052,
                         ephemeral_5m_input_tokens: 0}

    Two consequences the naive shape gets wrong:

    * Summing ``input_tokens`` alone under-counts that turn by ~23,000x.
      Nearly all input arrives as cache-creation tokens.
    * Cache writes are split by TTL and are priced differently (1h writes cost
      more than 5m writes), so one ``cache_write_tokens`` field cannot produce
      a correct cost. They are kept separate here.
    """

    model_config = ConfigDict(extra="forbid")

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    thinking_tokens: int = Field(
        default=0, ge=0, description="Subset of output_tokens. Billed as output."
    )
    cache_read_tokens: int = Field(default=0, ge=0)
    cache_write_5m_tokens: int = Field(default=0, ge=0)
    cache_write_1h_tokens: int = Field(default=0, ge=0)
    server_tool_use: dict[str, int] = Field(
        default_factory=dict,
        description="Bounded server-side tool call counts reported by the provider.",
    )

    @model_validator(mode="after")
    def _thinking_within_output(self) -> Self:
        if self.thinking_tokens > self.output_tokens:
            raise ValueError("thinking_tokens cannot exceed output_tokens")
        return self

    @field_validator("server_tool_use", mode="before")
    @classmethod
    def _server_tool_counts_are_bounded(cls, value: Any) -> dict[str, int]:
        if not isinstance(value, dict) or len(value) > 16:
            raise ValueError("server_tool_use must contain at most 16 counters")
        counts: dict[str, int] = {}
        for name, count in value.items():
            if (
                not isinstance(name, str)
                or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name) is None
                or type(count) is not int
                or count < 0
            ):
                raise ValueError("server_tool_use must contain named non-negative integer counters")
            counts[name] = count
        return counts

    @property
    def total_input_tokens(self) -> int:
        """Every token that entered the model, however it was billed."""
        return (
            self.input_tokens
            + self.cache_read_tokens
            + self.cache_write_5m_tokens
            + self.cache_write_1h_tokens
        )

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.output_tokens


class PriceSnapshot(BaseModel):
    """Per-million-token prices as fetched at dispatch time.

    Never populated from training data — Phase 3 fetches these from the
    OpenRouter models API and caches with a TTL. ``fetched_at`` and ``source``
    exist so a stale-price bug is diagnosable after the fact.
    """

    model_config = ConfigDict(extra="forbid")

    source: str = Field(description="e.g. 'openrouter/models', 'config:overrides'")
    fetched_at: datetime
    model: str
    input_per_mtok: float = Field(ge=0)
    output_per_mtok: float = Field(ge=0)
    cache_read_per_mtok: float | None = Field(default=None, ge=0)
    cache_write_5m_per_mtok: float | None = Field(default=None, ge=0)
    cache_write_1h_per_mtok: float | None = Field(default=None, ge=0)
    context_window: int | None = Field(default=None, gt=0)

    def cost_usd(self, usage: TokenUsage) -> float:
        """Cost of ``usage`` under this snapshot.

        Missing cache prices fall back to the input price, which over-estimates
        reads and under-estimates writes. Over-estimating spend is the safe
        direction for a budget governor, so unknown cache pricing never causes
        an under-count of the read path.
        """
        read_rate = (
            self.cache_read_per_mtok
            if self.cache_read_per_mtok is not None
            else self.input_per_mtok
        )
        write5_rate = (
            self.cache_write_5m_per_mtok
            if self.cache_write_5m_per_mtok is not None
            else self.input_per_mtok
        )
        write1h_rate = (
            self.cache_write_1h_per_mtok
            if self.cache_write_1h_per_mtok is not None
            else write5_rate
        )
        million = 1_000_000
        return (
            usage.input_tokens * self.input_per_mtok
            + usage.cache_read_tokens * read_rate
            + usage.cache_write_5m_tokens * write5_rate
            + usage.cache_write_1h_tokens * write1h_rate
            + usage.output_tokens * self.output_per_mtok
        ) / million


class CostEstimate(BaseModel):
    """Dollars *and* window quota. Both are scarce; they are not interchangeable.

    ``amount_usd`` is the provider's complete reported charge when available,
    including server-side tool calls. The individual tool counts remain on the
    accompanying :class:`TokenUsage`; OpenRouter does not report a reliable
    per-tool cost breakdown, so inventing one would make a budget less honest.
    """

    model_config = ConfigDict(extra="forbid")

    billing_mode: BillingMode
    amount_usd: float = Field(default=0.0, ge=0)
    window_tokens: int = Field(
        default=0,
        ge=0,
        description="Tokens charged against the 5-hour subscription window. "
        "Zero for metered calls.",
    )
    quota_pool: str | None = Field(
        default=None,
        max_length=32,
        description="Subscription quota consumed (for example claude or codex).",
    )
    pricing: PriceSnapshot | None = None
    is_estimate: bool = Field(
        default=True,
        description="False only if the provider returned an authoritative cost.",
    )

    @model_validator(mode="after")
    def _modes_are_coherent(self) -> Self:
        if self.billing_mode is BillingMode.METERED and self.window_tokens:
            raise ValueError("metered calls do not consume the subscription window")
        if self.billing_mode is BillingMode.METERED and self.quota_pool is not None:
            raise ValueError("metered calls do not consume a subscription quota pool")
        return self


class RoutingDecision(BaseModel):
    """Everything `sleipnir explain <task-id>` needs. Written once per attempt."""

    model_config = ConfigDict(extra="forbid")

    tier_requested: Tier
    tier_final: Tier
    model: str
    adapter: Adapter
    downshifted: bool = False
    escalated: bool = False
    downshift_reason: str | None = Field(default=None, max_length=400)
    candidates_considered: list[str] = Field(default_factory=list, max_length=20)
    rationale: str = Field(default="", max_length=1_000)

    @model_validator(mode="after")
    def _downshift_is_explained(self) -> Self:
        if self.downshifted and not self.downshift_reason:
            raise ValueError("a downshift must record why it happened")
        if self.downshifted and self.escalated:
            raise ValueError("an attempt cannot be both downshifted and escalated")
        return self


class CheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    check_type: str
    passed: bool
    detail: str = Field(default="", max_length=1_000)
    duration_s: float = Field(default=0.0, ge=0)


class ProducedArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(description="Matches an ExpectedOutput.name, or '' if unexpected.")
    path: str
    bytes: int = Field(ge=0)
    sha256: str | None = None


class AttemptStarted(BaseModel):
    """Written *before* dispatch, flushed immediately.

    This record is what makes crash recovery possible: an attempt with a start
    and no finish is precisely a task that was in flight when the process died.
    """

    model_config = ConfigDict(extra="forbid")

    record_type: Literal["attempt_started"] = "attempt_started"
    schema_version: Literal[1] = SCHEMA_VERSION
    run_id: str
    task_id: TaskId
    attempt: int = Field(ge=1)
    spec_hash: str
    plan_revision: int = Field(ge=0)
    routing: RoutingDecision
    pid: int | None = None
    started_at: datetime


class AttemptFinished(BaseModel):
    """Terminal record for one attempt. Append-only, never mutated."""

    model_config = ConfigDict(extra="forbid")

    record_type: Literal["attempt_finished"] = "attempt_finished"
    schema_version: Literal[1] = SCHEMA_VERSION
    run_id: str
    task_id: TaskId
    attempt: int = Field(ge=1)
    spec_hash: str
    plan_revision: int = Field(ge=0)

    routing: RoutingDecision
    status: AttemptStatus
    failure_kind: FailureKind | None = None

    started_at: datetime
    ended_at: datetime
    wall_time_s: float = Field(ge=0)

    usage: TokenUsage = Field(default_factory=TokenUsage)
    cost: CostEstimate

    artifacts: list[ProducedArtifact] = Field(default_factory=list)
    missing_outputs: list[str] = Field(
        default_factory=list, description="Required ExpectedOutput names not produced."
    )
    checks: list[CheckResult] = Field(default_factory=list)

    summary: str = Field(
        default="",
        description="Bounded digest. The ONLY free text that may reach the manifest.",
    )
    summary_truncated: bool = False
    exit_code: int | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None

    #: 200 tokens at the conservative 3.6 chars/token estimate.
    SUMMARY_MAX_CHARS: ClassVar[int] = 720

    @field_validator("summary")
    @classmethod
    def _cap_summary(cls, value: str) -> str:
        if len(value) > AttemptFinished.SUMMARY_MAX_CHARS:
            raise ValueError(
                f"summary is {len(value)} chars; the cap is "
                f"{AttemptFinished.SUMMARY_MAX_CHARS} (~200 tokens). Truncate at the "
                "write site and set summary_truncated=True."
            )
        return value

    @model_validator(mode="after")
    def _outcome_is_coherent(self) -> Self:
        if self.status is AttemptStatus.SUCCEEDED:
            if self.failure_kind is not None:
                raise ValueError("a succeeded attempt must not carry a failure_kind")
            if self.missing_outputs:
                raise ValueError(
                    "a succeeded attempt cannot be missing required outputs; "
                    "use status=partial"
                )
        elif self.failure_kind is None:
            raise ValueError(f"status {self.status} requires a failure_kind")

        if self.status is AttemptStatus.PARTIAL and not self.artifacts:
            raise ValueError(
                "a partial attempt produced nothing; that is status=failed"
            )
        if self.ended_at < self.started_at:
            raise ValueError("ended_at precedes started_at")
        return self

    @property
    def is_terminal_success(self) -> bool:
        return self.status is AttemptStatus.SUCCEEDED


ResultRecord = Annotated[
    AttemptStarted | AttemptFinished,
    Field(discriminator="record_type"),
]


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------


class BudgetSnapshot(BaseModel):
    """Governor's view of the current 5-hour window. Recomputed, never stored."""

    model_config = ConfigDict(extra="forbid")

    window_start: datetime
    window_end: datetime
    observed_at: datetime

    window_tokens_used: int = Field(default=0, ge=0)
    window_tokens_limit: int | None = Field(
        default=None,
        gt=0,
        description="None when the plan limit is unknown. Governor then reports "
        "burn rate but cannot compute headroom — it must not guess a limit.",
    )
    metered_spend_usd: float = Field(default=0.0, ge=0)
    metered_budget_usd: float | None = Field(default=None, ge=0)

    projected_plan_cost_usd: float = Field(default=0.0, ge=0)
    projected_plan_window_tokens: int = Field(default=0, ge=0)
    parse_warnings: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Usage-record shapes the parser did not recognize. Surfaced "
        "rather than swallowed — a silently wrong budget is worse than none.",
    )

    @property
    def window_headroom_tokens(self) -> int | None:
        if self.window_tokens_limit is None:
            return None
        return max(0, self.window_tokens_limit - self.window_tokens_used)

    @property
    def burn_rate_tokens_per_hour(self) -> float:
        elapsed = (self.observed_at - self.window_start).total_seconds()
        if elapsed <= 0:
            return 0.0
        return self.window_tokens_used / (elapsed / 3600.0)

    @property
    def will_exhaust_window(self) -> bool:
        headroom = self.window_headroom_tokens
        if headroom is None:
            return False
        return self.projected_plan_window_tokens > headroom

    @property
    def will_exhaust_budget(self) -> bool:
        if self.metered_budget_usd is None:
            return False
        return (
            self.metered_spend_usd + self.projected_plan_cost_usd
            > self.metered_budget_usd
        )


# ---------------------------------------------------------------------------
# Manifest — the only thing the orchestrator sees
# ---------------------------------------------------------------------------


class ManifestCaps(BaseModel):
    """Every bound that makes the manifest O(1) in task count.

    Change these and you change the orchestrator's context cost per cycle.
    Manifest.estimate_tokens() is asserted against hard_token_ceiling in tests.
    """

    model_config = ConfigDict(extra="forbid")

    goal_chars: int = 600
    max_groups: int = 10
    max_frontier: int = 12
    frontier_desc_chars: int = 140
    max_evidence: int = 16
    evidence_summary_chars: int = 240
    max_alerts: int = 5
    alert_chars: int = 160
    hard_token_ceiling: int = 4_000


DEFAULT_CAPS = ManifestCaps()


class GroupRollup(BaseModel):
    """Aggregate for one group. This is what replaces per-task detail for the
    completed bulk of the plan — counts are O(1) regardless of group size."""

    model_config = ConfigDict(extra="forbid")

    group: GroupId
    total: int = Field(ge=0)
    done: int = Field(default=0, ge=0)
    running: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    partial: int = Field(default=0, ge=0)
    pending: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0)


class FrontierEntry(BaseModel):
    """A task the orchestrator can actually act on this cycle."""

    model_config = ConfigDict(extra="forbid")

    id: TaskId
    description: str
    tier: Tier
    status: TaskStatus
    attempts: int = Field(default=0, ge=0)
    blocked_by: list[TaskId] = Field(default_factory=list, max_length=8)
    last_failure: FailureKind | None = None
    no_downshift: bool = False


class EvidenceEntry(BaseModel):
    """A completed dependency of a frontier task: its bounded summary plus
    *paths* to its full output. Paths, never content — content would reintroduce
    the quadratic growth this whole design exists to prevent."""

    model_config = ConfigDict(extra="forbid")

    id: TaskId
    status: TaskStatus
    summary: str
    artifact_paths: list[str] = Field(default_factory=list, max_length=6)
    truncated: bool = False


class ManifestBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_ends_at: datetime
    window_tokens_used: int = Field(ge=0)
    window_headroom_tokens: int | None = None
    burn_rate_tokens_per_hour: float = Field(ge=0)
    metered_spend_usd: float = Field(ge=0)
    projected_plan_cost_usd: float = Field(ge=0)
    downshift_active: bool = False


class ManifestTotals(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tasks: int = Field(ge=0)
    done: int = Field(default=0, ge=0)
    running: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    partial: int = Field(default=0, ge=0)
    stale: int = Field(default=0, ge=0)
    remaining: int = Field(default=0, ge=0)
    attempts_logged: int = Field(default=0, ge=0)


class Manifest(BaseModel):
    """The orchestrator's entire view of the world on re-invocation.

    Deliberately absent: completed task bodies, subagent transcripts, artifact
    contents, per-task history. Those live on disk and are reachable by path.
    The orchestrator asks for them explicitly or not at all.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = SCHEMA_VERSION
    plan_id: str
    plan_revision: int = Field(ge=0)
    generated_at: datetime
    goal: str
    totals: ManifestTotals
    budget: ManifestBudget
    groups: list[GroupRollup] = Field(default_factory=list)
    frontier: list[FrontierEntry] = Field(default_factory=list)
    evidence: list[EvidenceEntry] = Field(default_factory=list)
    alerts: list[str] = Field(default_factory=list)
    truncation_note: str | None = Field(
        default=None,
        description="Set when caps elided content, so the orchestrator knows its "
        "view is partial and can request a drill-down instead of assuming.",
    )
    caps: ManifestCaps = Field(default_factory=ManifestCaps)

    @model_validator(mode="after")
    def _within_caps(self) -> Self:
        caps = self.caps
        if len(self.goal) > caps.goal_chars:
            raise ValueError("goal exceeds cap; truncate before constructing")
        if len(self.groups) > caps.max_groups:
            raise ValueError("group rollups exceed cap")
        if len(self.frontier) > caps.max_frontier:
            raise ValueError("frontier exceeds cap")
        if len(self.evidence) > caps.max_evidence:
            raise ValueError("evidence exceeds cap")
        if len(self.alerts) > caps.max_alerts:
            raise ValueError("alerts exceed cap")
        for entry in self.frontier:
            if len(entry.description) > caps.frontier_desc_chars:
                raise ValueError(f"frontier {entry.id} description exceeds cap")
        for item in self.evidence:
            if len(item.summary) > caps.evidence_summary_chars:
                raise ValueError(f"evidence {item.id} summary exceeds cap")
        for alert in self.alerts:
            if len(alert) > caps.alert_chars:
                raise ValueError("alert exceeds cap")
        return self

    def render(self) -> str:
        """Exact bytes handed to the orchestrator. Size math measures this."""
        return json.dumps(
            self.model_dump(mode="json", exclude={"caps"}),
            indent=None,
            separators=(",", ":"),
            default=str,
        )

    def estimate_tokens(self) -> int:
        return estimate_tokens(self.render())


__all__ = [
    "SCHEMA_VERSION",
    "CHARS_PER_TOKEN",
    "DEFAULT_CAPS",
    "DOWNSHIFT_LADDER",
    "NON_RETRYABLE",
    "SATISFIED_STATUSES",
    "Adapter",
    "AcceptanceCheck",
    "ArtifactRef",
    "AttemptFinished",
    "AttemptStarted",
    "AttemptStatus",
    "BillingMode",
    "BudgetSnapshot",
    "CheckResult",
    "CommandCheck",
    "CostEstimate",
    "EscalationStep",
    "EvidenceEntry",
    "ExpectedOutput",
    "FailureKind",
    "FileExistsCheck",
    "FrontierEntry",
    "GroupRollup",
    "InputContract",
    "JsonSchemaCheck",
    "LlmJudgeCheck",
    "Manifest",
    "ManifestBudget",
    "ManifestCaps",
    "ManifestTotals",
    "OutputContract",
    "OutputKind",
    "Plan",
    "PlanDefaults",
    "PlanRevision",
    "PriceSnapshot",
    "ProducedArtifact",
    "ResultRecord",
    "RetryPolicy",
    "RevisionChange",
    "RevisionOp",
    "RoutingDecision",
    "Task",
    "TaskId",
    "TaskStatus",
    "Tier",
    "TokenUsage",
    "estimate_tokens",
]
