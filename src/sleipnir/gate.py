"""The phase gate: what the brain is allowed to know when it wakes up.

The intended shape of a run is: the brain fans work out into module loops, goes
quiet, and the workers build without supervision.  When they stop making
progress the brain wakes, decides, and goes quiet again.

The dangerous version of that is the obvious one — wake the brain and let it
read the verification reports.  Its context then grows with the number of
modules, and the run's cost goes from linear to quadratic in exactly the way the
whole project exists to prevent.  So the gate computes a *verdict* instead:
per-group counts and the ids of what failed.  Constant size, no matter how many
tasks or how much they wrote.

Nothing here is stored.  A verdict is a pure function of ``plan.json`` and the
folded result log, so a crash mid-gate loses nothing and recovery is an ordinary
read — the same discipline as task status.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sleipnir.projection import TaskState
from sleipnir.schema import (
    DOWNSHIFT_LADDER,
    GroupId,
    Plan,
    RevisionChange,
    RevisionOp,
    Task,
    TaskId,
    TaskStatus,
)

#: Statuses that mean "this task will not run again without intervention".
#: All of them stop a group passing.
_TERMINAL_FAILURE = frozenset(
    {TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.SKIPPED}
)

#: The subset that escalation may act on. A task is only worth retrying with a
#: better agent if it actually ran and lost. SKIPPED means a dependency failed
#: and this task never got a turn; CANCELLED means the operator or the budget
#: stopped the run. Escalating either spends money re-routing work whose
#: failure had nothing to do with the model that was chosen — and it would
#: escalate a whole downstream subtree on one upstream failure.
_ESCALATABLE = frozenset({TaskStatus.FAILED})

#: Statuses that are revision work queues, not outcomes. A group holding these
#: has not passed and has not failed — it has work the executor still owes it.
_PENDING_REVISION = frozenset({TaskStatus.STALE, TaskStatus.SUPERSEDED})


class GroupState(StrEnum):
    PASSED = "passed"  # every task done
    FAILED = "failed"  # at least one task terminally failed
    WORKING = "working"  # still has runnable or running tasks
    STUCK = "stuck"  # nothing runnable, nothing failed — blocked on a dependency
    EMPTY = "empty"


@dataclass(frozen=True)
class GroupVerdict:
    """One module's result. Counts only — never a summary, never a path."""

    group: GroupId
    state: GroupState
    total: int
    done: int
    failed: int
    running: int
    ready: int
    blocked: int
    pending_revision: int
    #: Only tasks that actually ran and failed — never ones skipped because a
    #: dependency failed. This is what escalation acts on.
    failed_task_ids: tuple[TaskId, ...] = ()

    @property
    def passed(self) -> bool:
        return self.state is GroupState.PASSED


@dataclass(frozen=True)
class GateVerdict:
    """The whole phase, as the brain is allowed to see it.

    ``quiescent`` is the question that decides whether to wake the brain at all:
    it is true only when no task is running and none could start.  Waking on
    anything less means paying a reason-tier spawn to be told "still working".
    """

    groups: tuple[GroupVerdict, ...]
    quiescent: bool

    @property
    def failed_groups(self) -> tuple[GroupVerdict, ...]:
        return tuple(group for group in self.groups if group.state is GroupState.FAILED)

    @property
    def passed_groups(self) -> tuple[GroupVerdict, ...]:
        return tuple(group for group in self.groups if group.passed)

    @property
    def complete(self) -> bool:
        """Every group passed. The phase may be merged and the next one begun."""
        return bool(self.groups) and all(group.passed for group in self.groups)

    @property
    def needs_brain(self) -> bool:
        """Workers have stopped and something is wrong.

        A quiescent, complete run does not need the brain either — there is
        nothing left to decide, and a spawn to confirm success is a spawn
        wasted.
        """
        return self.quiescent and not self.complete

    def render(self) -> str:
        """One line per group. This is what a human reads at a gate."""
        if not self.groups:
            return "no groups in plan"
        width = max(len(group.group) for group in self.groups)
        lines = []
        for group in self.groups:
            detail = f"{group.done}/{group.total} done"
            if group.failed:
                detail += f", {group.failed} failed ({', '.join(group.failed_task_ids[:3])})"
            if group.pending_revision:
                detail += f", {group.pending_revision} awaiting rerun"
            lines.append(f"  {group.group:<{width}}  {group.state.value:<8} {detail}")
        return "\n".join(lines)


def evaluate_gate(plan: Plan, states: dict[TaskId, TaskState]) -> GateVerdict:
    """Fold the run into a constant-size verdict.

    Deliberately tolerant of a task id missing from ``states``: a plan revision
    can add a task that has never been dispatched, and a gate that raised there
    would turn a normal mid-run edit into a crash.
    """
    verdicts: list[GroupVerdict] = []
    any_active = False

    for group_id in plan.groups:
        tasks = [task for task in plan.tasks if task.group == group_id]
        done = failed = running = ready = blocked = pending = 0
        failed_ids: list[TaskId] = []
        for task in tasks:
            state = states.get(task.id)
            status = state.status if state is not None else TaskStatus.BLOCKED
            if status is TaskStatus.DONE:
                done += 1
            elif status in _TERMINAL_FAILURE:
                failed += 1
                if status in _ESCALATABLE:
                    failed_ids.append(task.id)
            elif status is TaskStatus.RUNNING:
                running += 1
            elif status in (TaskStatus.READY, TaskStatus.PARTIAL):
                # PARTIAL with retries left is runnable; the projection has
                # already decided that, so treat it as work still in flight.
                ready += 1
            elif status in _PENDING_REVISION:
                pending += 1
            else:
                blocked += 1

        if running or ready or pending:
            any_active = True

        total = len(tasks)
        if not total:
            state_value = GroupState.EMPTY
        elif failed:
            state_value = GroupState.FAILED
        elif done == total:
            state_value = GroupState.PASSED
        elif running or ready or pending:
            state_value = GroupState.WORKING
        else:
            state_value = GroupState.STUCK

        verdicts.append(
            GroupVerdict(
                group=group_id,
                state=state_value,
                total=total,
                done=done,
                failed=failed,
                running=running,
                ready=ready,
                blocked=blocked,
                pending_revision=pending,
                failed_task_ids=tuple(failed_ids),
            )
        )

    return GateVerdict(groups=tuple(verdicts), quiescent=not any_active)


def stronger_tier(task: Task):
    """The next more capable tier, or ``None`` if already at the top.

    ``DOWNSHIFT_LADDER`` runs most-capable first, so "stronger" is a step
    towards index zero — escalation is the governor's ladder read upwards.
    It is capped there rather than wrapping: a task that failed at the reason
    tier does not get retried at the reason tier again just because the list
    ran out.

    ``no_downshift`` blocks escalation too, despite the name. The flag marks a
    task whose tier was chosen deliberately; moving it in *either* direction
    overrides that choice.
    """
    if task.no_downshift:
        return None
    try:
        index = DOWNSHIFT_LADDER.index(task.tier)
    except ValueError:
        return None
    return None if index == 0 else DOWNSHIFT_LADDER[index - 1]


#: `RetryPolicy.max_attempts` is capped at 6 by the schema. A task that has
#: burned all six has been tried at every tier the ladder offers; the gate stops
#: and lets the brain decide rather than inventing a seventh.
_MAX_ATTEMPTS = 6


def escalation_changes(
    plan: Plan,
    verdict: GateVerdict,
    states: dict[TaskId, TaskState],
    *,
    detail: str = "gate escalation after group failure",
) -> list[RevisionChange]:
    """Re-run failed modules with a stronger model, and change nothing else.

    Every change is a ``retarget_task`` carrying the *same* task with two
    routing fields moved: the tier raised, and one more attempt granted.

    Both are needed, and the second is easy to miss. A failed task is failed
    precisely because ``state.attempts >= task.retry.max_attempts``; raising
    only the tier produces a better-routed task that the executor will never
    dispatch, so the escalation silently does nothing. Granting exactly one
    attempt — not resetting the counter — keeps the ladder finite.

    Neither field is in ``Task.spec_hash``, which is what makes this safe: the
    group's completed work is not invalidated, and a routing-preserving
    retarget is the one revision class allowed to auto-apply, so a failed
    module can be retried with a better agent without stopping for a human.
    """
    changes: list[RevisionChange] = []
    for group in verdict.failed_groups:
        for task_id in group.failed_task_ids:
            task = plan.by_id.get(task_id)
            if task is None:
                continue
            target = stronger_tier(task)
            if target is None:
                # Already at the top, or pinned. There is no better agent to
                # give it; a second identical attempt would fail identically
                # and bill twice for the privilege.
                continue
            state = states.get(task_id)
            attempts = state.attempts if state is not None else 0
            allowance = max(task.retry.max_attempts, attempts) + 1
            if allowance > _MAX_ATTEMPTS:
                continue
            changes.append(
                RevisionChange(
                    op=RevisionOp.RETARGET_TASK,
                    task_id=task_id,
                    detail=f"{detail}: {task.tier.value} -> {target.value}, attempt {allowance}",
                    task=task.model_copy(
                        update={
                            "tier": target,
                            "retry": task.retry.model_copy(
                                update={"max_attempts": allowance}
                            ),
                        }
                    ),
                )
            )
    return changes


__all__ = [
    "GateVerdict",
    "GroupState",
    "GroupVerdict",
    "escalation_changes",
    "evaluate_gate",
    "stronger_tier",
]
