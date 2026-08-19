"""Validated, auditable plan revision application.

The orchestrator may propose changes, but it never supplies their blast radius.
This module applies the operations to a copy, validates the complete DAG, then
computes which completed work became superseded or stale.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from sleipnir.projection import fold_results
from sleipnir.schema import (
    AttemptFinished,
    AttemptStarted,
    Plan,
    PlanRevision,
    RevisionChange,
    RevisionOp,
    TaskStatus,
)


class RevisionError(RuntimeError):
    """A proposed revision is inconsistent with the current plan."""


def apply_revision(
    plan: Plan,
    changes: Sequence[RevisionChange],
    *,
    reason: str,
    records: list[AttemptStarted | AttemptFinished] | None = None,
    created_at: datetime | None = None,
) -> tuple[Plan, PlanRevision]:
    if not changes:
        raise RevisionError("a revision must contain at least one change")
    tasks = {task.id: task for task in plan.tasks}
    original_order = [task.id for task in plan.tasks]

    for change in changes:
        current = tasks.get(change.task_id)
        match change.op:
            case RevisionOp.ADD_TASK:
                if current is not None:
                    raise RevisionError(f"task {change.task_id!r} already exists")
                if change.task is None:
                    raise RevisionError("add_task is missing its validated task payload")
                tasks[change.task_id] = change.task
                original_order.append(change.task_id)
            case RevisionOp.REMOVE_TASK:
                if current is None:
                    raise RevisionError(f"task {change.task_id!r} does not exist")
                del tasks[change.task_id]
                original_order.remove(change.task_id)
            case RevisionOp.RETARGET_TASK | RevisionOp.RESPEC_TASK:
                if current is None:
                    raise RevisionError(f"task {change.task_id!r} does not exist")
                if change.task is None:
                    raise RevisionError(f"{change.op.value} is missing its task payload")
                same_meaning = current.spec_hash() == change.task.spec_hash()
                if change.op is RevisionOp.RETARGET_TASK and not same_meaning:
                    raise RevisionError("retarget_task may change routing fields only")
                if change.op is RevisionOp.RESPEC_TASK and same_meaning:
                    raise RevisionError("respec_task must change a semantic field")
                tasks[change.task_id] = change.task
            case RevisionOp.ADD_EDGE | RevisionOp.REMOVE_EDGE:
                if current is None:
                    raise RevisionError(f"task {change.task_id!r} does not exist")
                dependency = change.dependency_id
                if dependency is None:
                    raise RevisionError(f"{change.op.value} is missing dependency_id")
                deps = list(current.depends_on)
                if change.op is RevisionOp.ADD_EDGE:
                    if dependency in deps:
                        raise RevisionError(f"edge {dependency!r} -> {change.task_id!r} exists")
                    deps.append(dependency)
                else:
                    if dependency not in deps:
                        raise RevisionError(f"edge {dependency!r} -> {change.task_id!r} does not exist")
                    deps.remove(dependency)
                tasks[change.task_id] = type(current).model_validate(
                    current.model_dump(mode="python") | {"depends_on": deps}
                )

    try:
        revised = Plan.model_validate(
            plan.model_dump(mode="python")
            | {"revision": plan.revision + 1, "tasks": [tasks[tid] for tid in original_order]}
        )
    except Exception as exc:
        raise RevisionError(f"revised plan is invalid: {exc}") from exc

    old_hashes = plan.spec_hashes()
    new_hashes = revised.spec_hashes()
    semantic = {
        task_id
        for task_id in old_hashes.keys() | new_hashes.keys()
        if old_hashes.get(task_id) != new_hashes.get(task_id)
    }
    states = fold_results(plan, records or [])
    completed = {
        task_id for task_id, state in states.items()
        if state.status in (TaskStatus.DONE, TaskStatus.STALE)
    }
    superseded = sorted(semantic & completed)
    staled: set[str] = set()
    for task_id in semantic & set(plan.by_id):
        staled.update(plan.descendants(task_id) & completed)
    staled.difference_update(superseded)

    audit = PlanRevision(
        revision=revised.revision,
        parent_revision=plan.revision,
        created_at=created_at or datetime.now(UTC),
        reason=reason,
        changes=list(changes),
        superseded=superseded,
        staled=sorted(staled),
    )
    return revised, audit


def persist_revision(plan_path: Path, revision_path: Path, plan: Plan, audit: PlanRevision) -> None:
    """Append the audit first, then atomically replace the derived plan view."""
    revision_path.parent.mkdir(parents=True, exist_ok=True)
    if revision_path.is_symlink():
        raise RevisionError(f"refusing to append through symlinked revision log: {revision_path}")
    with revision_path.open("a", encoding="utf-8") as handle:
        handle.write(audit.model_dump_json() + "\n")
        handle.flush()
        os.fsync(handle.fileno())

    temporary = plan_path.with_name(
        f".{plan_path.name}.revision-{plan.revision}-{uuid.uuid4().hex}.tmp"
    )
    with temporary.open("x", encoding="utf-8") as handle:
        handle.write(plan.model_dump_json(indent=2))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, plan_path)


def read_staleness(revision_path: Path) -> dict[str, int]:
    """Latest revision that made each completed descendant stale."""
    if not revision_path.exists():
        return {}
    if revision_path.is_symlink():
        raise RevisionError(f"refusing to read through symlinked revision log: {revision_path}")
    lines = revision_path.read_text(encoding="utf-8", errors="replace").splitlines()
    staled: dict[str, int] = {}
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            revision = PlanRevision.model_validate(json.loads(line))
        except Exception as exc:
            if index == len(lines) - 1:
                continue
            raise RevisionError(
                f"{revision_path}:{index + 1} is malformed before the final line"
            ) from exc
        for task_id in revision.staled:
            staled[task_id] = max(staled.get(task_id, 0), revision.revision)
    return staled


__all__ = ["RevisionError", "apply_revision", "persist_revision", "read_staleness"]
