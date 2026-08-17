"""Pure derivation of run state from plan + results.

Deliberately I/O-free: no subprocess, no filesystem, no network. Everything
here is a fold over data already on disk, which is what makes it testable and
what makes crash recovery work — see DESIGN.md Q4.

This module is *not* the Phase 2 executor. It exists in Phase 1 because the
manifest's bounded-size claim is otherwise unfalsifiable: you cannot check that
a projection stays constant without a projection.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from sleipnir.schema import (
    DEFAULT_CAPS,
    SATISFIED_STATUSES,
    AttemptFinished,
    AttemptStarted,
    AttemptStatus,
    BudgetSnapshot,
    EvidenceEntry,
    FailureKind,
    FrontierEntry,
    GroupRollup,
    Manifest,
    ManifestBudget,
    ManifestCaps,
    ManifestTotals,
    Plan,
    Task,
    TaskStatus,
)

#: Statuses the orchestrator can act on. Everything else is either finished or
#: waiting on something that is itself on the frontier.
ACTIONABLE: tuple[TaskStatus, ...] = (
    TaskStatus.RUNNING,
    TaskStatus.FAILED,
    TaskStatus.PARTIAL,
    TaskStatus.READY,
    TaskStatus.STALE,
)

#: Frontier ordering: what most needs a decision comes first.
_STATUS_URGENCY: dict[TaskStatus, int] = {
    TaskStatus.FAILED: 0,
    TaskStatus.PARTIAL: 1,
    TaskStatus.RUNNING: 2,
    TaskStatus.READY: 3,
    TaskStatus.STALE: 4,
}


def _clip(text: str, limit: int) -> tuple[str, bool]:
    """Clip to ``limit`` characters, signalling whether anything was lost."""
    if len(text) <= limit:
        return text, False
    if limit <= 1:
        return text[:limit], True
    return text[: limit - 1] + "…", True


@dataclass(slots=True)
class TaskState:
    """Folded state for one task. Never persisted — always recomputed."""

    task_id: str
    status: TaskStatus
    attempts: int = 0
    open_attempt: int | None = None
    last_failure: FailureKind | None = None
    summary: str = ""
    artifact_paths: list[str] = field(default_factory=list)
    cost_usd: float = 0.0
    window_tokens: int = 0
    blocked_by: list[str] = field(default_factory=list)
    spec_mismatch: bool = False


def fold_results(
    plan: Plan,
    records: list[AttemptStarted | AttemptFinished],
    *,
    staled: set[str] | None = None,
) -> dict[str, TaskState]:
    """Recompute every task's status from the append-only result log.

    Records are grouped by ``(task_id, attempt)``; an attempt with a start and
    no finish was in flight when the process died. Because the fold is total —
    it reads the whole log every time — there is no derived state that can
    desync from the log, and a partially written trailing record can simply be
    discarded by the reader.
    """
    staled = staled or set()
    current_hashes = plan.spec_hashes()

    started: dict[str, dict[int, AttemptStarted]] = defaultdict(dict)
    finished: dict[str, dict[int, AttemptFinished]] = defaultdict(dict)
    for record in records:
        if isinstance(record, AttemptStarted):
            started[record.task_id][record.attempt] = record
        else:
            # Last write for a given (task, attempt) wins. Duplicates only occur
            # if a run was replayed; they are not summed, which is what keeps
            # cost accounting idempotent.
            finished[record.task_id][record.attempt] = record

    states: dict[str, TaskState] = {}
    for task in plan.tasks:
        states[task.id] = _fold_task(
            task,
            started.get(task.id, {}),
            finished.get(task.id, {}),
            current_hashes[task.id],
            task.id in staled,
        )

    _propagate_dependencies(plan, states)
    return states


def _fold_task(
    task: Task,
    started: dict[int, AttemptStarted],
    finished: dict[int, AttemptFinished],
    current_hash: str,
    is_staled: bool,
) -> TaskState:
    state = TaskState(task_id=task.id, status=TaskStatus.READY)
    state.attempts = len(finished)

    for record in finished.values():
        state.cost_usd += record.cost.amount_usd
        state.window_tokens += record.cost.window_tokens

    open_attempts = sorted(set(started) - set(finished))
    if open_attempts:
        state.open_attempt = open_attempts[-1]
        state.status = TaskStatus.RUNNING
        return state

    if not finished:
        state.status = TaskStatus.READY
        return state

    latest = finished[max(finished)]
    state.summary = latest.summary
    state.artifact_paths = [artifact.path for artifact in latest.artifacts]
    state.last_failure = latest.failure_kind

    if latest.spec_hash != current_hash:
        # The task's own meaning changed after this result was produced.
        state.spec_mismatch = True
        state.status = TaskStatus.SUPERSEDED
        return state

    match latest.status:
        case AttemptStatus.SUCCEEDED:
            state.status = TaskStatus.STALE if is_staled else TaskStatus.DONE
        case AttemptStatus.CANCELLED:
            state.status = TaskStatus.CANCELLED
        case AttemptStatus.PARTIAL | AttemptStatus.FAILED:
            retries_left = state.attempts < task.retry.max_attempts
            retryable = latest.failure_kind in task.retry.retry_on
            if retries_left and retryable:
                state.status = TaskStatus.READY
            else:
                state.status = (
                    TaskStatus.PARTIAL
                    if latest.status is AttemptStatus.PARTIAL
                    else TaskStatus.FAILED
                )
    return state


def _propagate_dependencies(plan: Plan, states: dict[str, TaskState]) -> None:
    """Mark tasks blocked by unsatisfied deps, in topological order."""
    for task_id in plan.topological_order():
        task = plan.by_id[task_id]
        state = states[task_id]
        if state.status not in (TaskStatus.READY,):
            continue
        blockers = [
            dep for dep in task.depends_on if states[dep].status not in SATISFIED_STATUSES
        ]
        if blockers:
            state.blocked_by = blockers
            dead = [
                dep
                for dep in blockers
                if states[dep].status
                in (TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.SKIPPED)
            ]
            state.status = TaskStatus.SKIPPED if dead else TaskStatus.BLOCKED


def build_manifest(
    plan: Plan,
    records: list[AttemptStarted | AttemptFinished],
    budget: BudgetSnapshot,
    *,
    generated_at: datetime,
    caps: ManifestCaps = DEFAULT_CAPS,
    staled: set[str] | None = None,
    downshift_active: bool = False,
) -> Manifest:
    """Project plan + results into the bounded orchestrator view.

    Every unbounded collection is capped here, and every cap that actually bit
    is reported in ``truncation_note`` — the orchestrator is told its view is
    partial rather than being allowed to infer completeness from silence.
    """
    states = fold_results(plan, records, staled=staled)
    elided: list[str] = []

    totals = _totals(states, records)
    groups = _group_rollups(plan, states, caps, elided)
    frontier = _frontier(plan, states, caps, elided)
    evidence = _evidence(plan, states, frontier, caps, elided)
    alerts = _alerts(plan, states, budget, caps, elided)

    goal, goal_clipped = _clip(plan.goal, caps.goal_chars)
    if goal_clipped:
        elided.append("goal truncated")

    return Manifest(
        plan_id=plan.plan_id,
        plan_revision=plan.revision,
        generated_at=generated_at,
        goal=goal,
        totals=totals,
        budget=ManifestBudget(
            window_ends_at=budget.window_end,
            window_tokens_used=budget.window_tokens_used,
            window_headroom_tokens=budget.window_headroom_tokens,
            burn_rate_tokens_per_hour=round(budget.burn_rate_tokens_per_hour, 1),
            metered_spend_usd=round(budget.metered_spend_usd, 4),
            projected_plan_cost_usd=round(budget.projected_plan_cost_usd, 4),
            downshift_active=downshift_active,
        ),
        groups=groups,
        frontier=frontier,
        evidence=evidence,
        alerts=alerts,
        truncation_note="; ".join(elided)[:400] or None,
        caps=caps,
    )


def _totals(
    states: dict[str, TaskState],
    records: list[AttemptStarted | AttemptFinished],
) -> ManifestTotals:
    counts: dict[TaskStatus, int] = defaultdict(int)
    for state in states.values():
        counts[state.status] += 1
    finished_count = sum(1 for r in records if isinstance(r, AttemptFinished))
    settled = (
        counts[TaskStatus.DONE]
        + counts[TaskStatus.FAILED]
        + counts[TaskStatus.SKIPPED]
        + counts[TaskStatus.CANCELLED]
    )
    return ManifestTotals(
        tasks=len(states),
        done=counts[TaskStatus.DONE],
        running=counts[TaskStatus.RUNNING],
        failed=counts[TaskStatus.FAILED],
        partial=counts[TaskStatus.PARTIAL],
        stale=counts[TaskStatus.STALE],
        remaining=len(states) - settled,
        attempts_logged=finished_count,
    )


def _group_rollups(
    plan: Plan,
    states: dict[str, TaskState],
    caps: ManifestCaps,
    elided: list[str],
) -> list[GroupRollup]:
    buckets: dict[str, list[TaskState]] = defaultdict(list)
    for task in plan.tasks:
        buckets[task.group].append(states[task.id])

    rollups = [_rollup(group, members) for group, members in buckets.items()]
    # Groups with live work first; the orchestrator cares about what is moving.
    rollups.sort(key=lambda r: (-(r.running + r.failed + r.partial), -r.pending, r.group))

    if len(rollups) > caps.max_groups:
        head = rollups[: caps.max_groups - 1]
        tail = rollups[caps.max_groups - 1 :]
        head.append(
            GroupRollup(
                group="other",
                total=sum(r.total for r in tail),
                done=sum(r.done for r in tail),
                running=sum(r.running for r in tail),
                failed=sum(r.failed for r in tail),
                partial=sum(r.partial for r in tail),
                pending=sum(r.pending for r in tail),
                cost_usd=round(sum(r.cost_usd for r in tail), 4),
            )
        )
        elided.append(f"{len(tail)} groups merged into 'other'")
        rollups = head
    return rollups


def _rollup(group: str, members: list[TaskState]) -> GroupRollup:
    counts: dict[TaskStatus, int] = defaultdict(int)
    for state in members:
        counts[state.status] += 1
    return GroupRollup(
        group=group,
        total=len(members),
        done=counts[TaskStatus.DONE] + counts[TaskStatus.STALE],
        running=counts[TaskStatus.RUNNING],
        failed=counts[TaskStatus.FAILED] + counts[TaskStatus.SKIPPED],
        partial=counts[TaskStatus.PARTIAL],
        pending=counts[TaskStatus.READY] + counts[TaskStatus.BLOCKED],
        cost_usd=round(sum(s.cost_usd for s in members), 4),
    )


def _frontier(
    plan: Plan,
    states: dict[str, TaskState],
    caps: ManifestCaps,
    elided: list[str],
) -> list[FrontierEntry]:
    candidates = [
        (plan.by_id[tid], state)
        for tid, state in states.items()
        if state.status in ACTIONABLE
    ]
    candidates.sort(
        key=lambda pair: (
            _STATUS_URGENCY.get(pair[1].status, 9),
            -pair[0].priority,
            pair[0].id,
        )
    )
    if len(candidates) > caps.max_frontier:
        elided.append(
            f"{len(candidates) - caps.max_frontier} actionable tasks beyond frontier cap"
        )
        candidates = candidates[: caps.max_frontier]

    entries: list[FrontierEntry] = []
    for task, state in candidates:
        description, _ = _clip(task.description, caps.frontier_desc_chars)
        entries.append(
            FrontierEntry(
                id=task.id,
                description=description,
                tier=task.tier,
                status=state.status,
                attempts=state.attempts,
                blocked_by=state.blocked_by[:8],
                last_failure=state.last_failure,
                no_downshift=task.no_downshift,
            )
        )
    return entries


def _evidence(
    plan: Plan,
    states: dict[str, TaskState],
    frontier: list[FrontierEntry],
    caps: ManifestCaps,
    elided: list[str],
) -> list[EvidenceEntry]:
    """Summaries of completed tasks the frontier actually depends on.

    This is the only place completed work re-enters the orchestrator's view, and
    it is bounded twice over: by the frontier cap (which bounds how many
    dependencies can be relevant) and by max_evidence.
    """
    wanted: list[str] = []
    seen: set[str] = set()
    for entry in frontier:
        for dep in plan.by_id[entry.id].depends_on:
            if dep in seen:
                continue
            if states[dep].status in SATISFIED_STATUSES or states[dep].summary:
                seen.add(dep)
                wanted.append(dep)

    if len(wanted) > caps.max_evidence:
        elided.append(f"{len(wanted) - caps.max_evidence} dependency summaries omitted")
        wanted = wanted[: caps.max_evidence]

    entries: list[EvidenceEntry] = []
    for dep in wanted:
        state = states[dep]
        summary, clipped = _clip(state.summary, caps.evidence_summary_chars)
        entries.append(
            EvidenceEntry(
                id=dep,
                status=state.status,
                summary=summary,
                artifact_paths=state.artifact_paths[:6],
                truncated=clipped,
            )
        )
    return entries


def _alerts(
    plan: Plan,
    states: dict[str, TaskState],
    budget: BudgetSnapshot,
    caps: ManifestCaps,
    elided: list[str],
) -> list[str]:
    alerts: list[str] = []
    if budget.will_exhaust_window:
        alerts.append(
            f"projected {budget.projected_plan_window_tokens} window tokens exceeds "
            f"headroom {budget.window_headroom_tokens}; downshift eligible tasks"
        )
    if budget.will_exhaust_budget:
        alerts.append(
            f"projected metered spend would exceed the ${budget.metered_budget_usd} cap"
        )
    if budget.parse_warnings:
        alerts.append(
            f"usage parser saw {len(budget.parse_warnings)} unrecognized record shapes; "
            "budget figures may be low"
        )
    failed = [tid for tid, s in states.items() if s.status is TaskStatus.FAILED]
    if failed:
        alerts.append(f"{len(failed)} task(s) failed terminally: {', '.join(failed[:5])}")
    superseded = [tid for tid, s in states.items() if s.spec_mismatch]
    if superseded:
        alerts.append(
            f"{len(superseded)} task(s) superseded by a plan revision and must re-run"
        )

    if len(alerts) > caps.max_alerts:
        elided.append(f"{len(alerts) - caps.max_alerts} alerts omitted")
        alerts = alerts[: caps.max_alerts]
    return [_clip(alert, caps.alert_chars)[0] for alert in alerts]


__all__ = ["TaskState", "build_manifest", "fold_results"]
