"""Dependency-free terminal dashboard for a Sleipnir run.

Rendering is deliberately a pure function of the plan and append-only log.
The TUI never becomes another state store, and it never reads artifact content
or subagent summaries.  That keeps it safe to attach to a live executor and
makes a static screen useful in logs and CI too.
"""

from __future__ import annotations

import shutil
from collections import Counter
from datetime import UTC, datetime

from sleipnir.projection import fold_results
from sleipnir.schema import (
    AttemptFinished,
    AttemptStarted,
    BudgetSnapshot,
    Plan,
    TaskStatus,
)

_GLYPH = {
    TaskStatus.DONE: "✓",
    TaskStatus.STALE: "~",
    TaskStatus.RUNNING: "▶",
    TaskStatus.READY: "·",
    TaskStatus.BLOCKED: "○",
    TaskStatus.PARTIAL: "◐",
    TaskStatus.FAILED: "×",
    TaskStatus.SKIPPED: "−",
    TaskStatus.SUPERSEDED: "s",
    TaskStatus.CANCELLED: "!",
}


def _clip(value: str, width: int) -> str:
    # Plans, model ids, and control reasons are untrusted display data. Never
    # let ANSI escapes/newlines turn a dashboard into terminal code execution.
    value = "".join(character if character.isprintable() else " " for character in value)
    if width <= 0:
        return ""
    return value if len(value) <= width else value[: max(0, width - 1)] + "…"


def _bar(done: int, total: int, width: int) -> str:
    filled = 0 if not total else round(width * done / total)
    return "█" * filled + "░" * (width - filled)


def _money(value: float | None) -> str:
    return "—" if value is None else f"${value:.4f}"


def _latest_routes(
    records: list[AttemptStarted | AttemptFinished],
) -> dict[str, AttemptStarted | AttemptFinished]:
    latest: dict[str, AttemptStarted | AttemptFinished] = {}
    for record in records:
        previous = latest.get(record.task_id)
        if previous is None or record.attempt >= previous.attempt:
            latest[record.task_id] = record
    return latest


def render_dashboard(
    plan: Plan,
    records: list[AttemptStarted | AttemptFinished],
    snapshot: BudgetSnapshot | None = None,
    *,
    width: int | None = None,
    height: int | None = None,
    active: bool = False,
    now: datetime | None = None,
    staled_at: dict[str, int] | None = None,
    proposed_revisions: int = 0,
    activity: str | None = None,
) -> str:
    """Render one complete dashboard frame without terminal side effects."""
    terminal = shutil.get_terminal_size((100, 30))
    width = max(64, min(width or terminal.columns, 140))
    height = max(18, height or terminal.lines)
    now = now or datetime.now(UTC)
    states = fold_results(plan, records, staled_at=staled_at)
    counts = Counter(state.status for state in states.values())
    total = len(plan.tasks)
    done = (
        counts[TaskStatus.DONE]
        + counts[TaskStatus.SKIPPED]
        + counts[TaskStatus.SUPERSEDED]
    )
    spend = sum(
        record.cost.amount_usd
        for record in records
        if isinstance(record, AttemptFinished)
        and record.cost.billing_mode.value == "metered"
    )
    notional = sum(
        record.cost.amount_usd
        for record in records
        if isinstance(record, AttemptFinished)
        and record.cost.billing_mode.value == "subscription"
    )
    claude_window = sum(
        record.cost.window_tokens
        for record in records
        if isinstance(record, AttemptFinished)
    )
    codex_tokens = sum(
        record.usage.total_tokens
        for record in records
        if isinstance(record, AttemptFinished)
        and record.cost.quota_pool == "codex"
    )
    server_tools: Counter[str] = Counter()
    for record in records:
        if isinstance(record, AttemptFinished):
            server_tools.update(record.usage.server_tool_use)
    routes = _latest_routes(records)

    if active:
        state_label = "EXECUTING"
    elif proposed_revisions:
        state_label = "REVIEW"
    elif total and done == total:
        state_label = "COMPLETE"
    elif counts[TaskStatus.FAILED] or counts[TaskStatus.PARTIAL]:
        state_label = "ATTENTION"
    else:
        state_label = "MONITOR"
    title = f" SLEIPNIR  {state_label} "
    lines = [title + "─" * max(0, width - len(title))]
    lines.append(
        _clip(f"{plan.plan_id}  rev {plan.revision}  {plan.goal}", width)
    )
    bar_width = max(10, width - 34)
    lines.append(
        f"{_bar(done, total, bar_width)}  {done:>3}/{total:<3} "
        f"run {counts[TaskStatus.RUNNING]}  ready {counts[TaskStatus.READY]}  "
        f"fail {counts[TaskStatus.FAILED]}"
    )

    if snapshot is None:
        budget = (
            f"metered {_money(spend)}  notional {_money(notional)}  "
            f"claude {claude_window:,} tok  codex {codex_tokens:,} tok"
        )
    else:
        limit = snapshot.window_tokens_limit
        used = snapshot.window_tokens_used
        window = f"{used:,}" if limit is None else f"{used:,}/{limit:,}"
        budget = (
            f"metered {_money(spend)}  notional {_money(notional)}  "
            f"claude {window} tok  codex {codex_tokens:,} tok  "
            f"projected {_money(snapshot.projected_plan_cost_usd)}"
        )
    if proposed_revisions:
        budget += f"  REVIEW {proposed_revisions} PROPOSAL(S)"
    if server_tools:
        budget += "  tools " + ", ".join(
            f"{name}={count}" for name, count in sorted(server_tools.items())
        )
    lines.extend([_clip(budget, width), "─" * width])
    if activity:
        lines.extend([_clip(f"control: {activity}", width), "─" * width])

    id_width = min(24, max(12, max((len(task.id) for task in plan.tasks), default=12)))
    model_width = max(12, min(28, width - id_width - 37))
    lines.append(
        f" {'':1} {'TASK':<{id_width}} {'STATE':<10} {'TIER':<10} "
        f"{'ATT':>3}  {'ROUTE':<{model_width}} COST"
    )

    fixed_lines = 9 + (2 if activity else 0)
    task_capacity = max(5, height - fixed_lines)
    ordered = plan.topological_order()
    if len(ordered) > task_capacity:
        urgent = [
            task_id for task_id in ordered
            if states[task_id].status in (
                TaskStatus.RUNNING, TaskStatus.FAILED, TaskStatus.PARTIAL, TaskStatus.READY
            )
        ]
        remaining = [task_id for task_id in ordered if task_id not in urgent]
        ordered = (urgent + remaining)[:task_capacity]

    for task_id in ordered:
        task = plan.by_id[task_id]
        state = states[task_id]
        record = routes.get(task_id)
        route = "—"
        if record is not None:
            route = f"{record.routing.adapter.value}/{record.routing.model}"
        lines.append(
            f" {_GLYPH.get(state.status, '?')} "
            f"{_clip(task_id, id_width):<{id_width}} "
            f"{state.status.value:<10} {task.tier.value:<10} "
            f"{state.attempts:>3}  {_clip(route, model_width):<{model_width}} "
            f"{_money(state.cost_usd)}"
        )
    hidden = total - len(ordered)
    if hidden > 0:
        lines.append(f"   … {hidden} lower-priority task(s) hidden at this terminal height")

    lines.append("─" * width)
    lines.append(
        _clip(
            f"updated {now:%H:%M:%S} UTC  |  "
            "sleipnir tui --watch to follow  |  Ctrl-C exits safely",
            width,
        )
    )
    return "\n".join(lines)


__all__ = ["render_dashboard"]
