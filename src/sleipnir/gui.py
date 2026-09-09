"""Read-only desktop projection over Sleipnir's existing run truth.

The GUI is a client, never a second orchestrator.  This module reads
``plan.json`` plus the append-only logs and produces the bounded JSON shape
consumed by the native shell.  It does not inspect artifact bodies and it does
not persist derived task status.
"""

from __future__ import annotations

import argparse
import json
import platform as host_platform
from collections import Counter
from datetime import UTC, datetime, timedelta
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from sleipnir.projection import build_manifest, fold_results
from sleipnir.revisions import read_staleness
from sleipnir.runlog import ResultLog, run_is_active
from sleipnir.schema import (
    Adapter,
    AttemptFinished,
    AttemptStarted,
    BillingMode,
    BudgetSnapshot,
    Plan,
    TaskStatus,
)

Record = AttemptStarted | AttemptFinished


def _package_version() -> str:
    try:
        return version("sleipnir")
    except PackageNotFoundError:  # pragma: no cover - editable install normally exists
        return "0.1.0"


def _iso(stamp: datetime) -> str:
    return stamp.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _latest_records(records: list[Record]) -> dict[str, Record]:
    latest: dict[str, Record] = {}
    for record in records:
        previous = latest.get(record.task_id)
        if previous is None or record.attempt >= previous.attempt:
            latest[record.task_id] = record
    return latest


def _budget_snapshot(records: list[Record], now: datetime) -> BudgetSnapshot:
    finished = [record for record in records if isinstance(record, AttemptFinished)]
    return BudgetSnapshot(
        window_start=now - timedelta(hours=1),
        window_end=now + timedelta(hours=4),
        observed_at=now,
        window_tokens_used=sum(record.cost.window_tokens for record in finished),
        metered_spend_usd=sum(
            record.cost.amount_usd
            for record in finished
            if record.cost.billing_mode is BillingMode.METERED
        ),
    )


def _run_state(
    statuses: Counter[TaskStatus], total: int, *, active: bool, reviews: list[dict[str, Any]]
) -> str:
    if active or statuses[TaskStatus.RUNNING]:
        return "running"
    if reviews:
        return "review"
    completed = statuses[TaskStatus.DONE] + statuses[TaskStatus.SKIPPED]
    if total and completed == total:
        return "complete"
    if statuses[TaskStatus.FAILED] or statuses[TaskStatus.PARTIAL]:
        return "blocked"
    return "planning"


def _provider(adapter: Adapter) -> str:
    if adapter is Adapter.OPENAI:
        return "compatible"
    return adapter.value


def _reviews(run_root: Path) -> list[dict[str, Any]]:
    proposals = run_root / "proposals"
    if not proposals.is_dir():
        return []
    reviews: list[dict[str, Any]] = []
    for path in sorted(proposals.glob("*.json"))[:20]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        changes = payload.get("changes") if isinstance(payload, dict) else None
        changes = changes if isinstance(changes, list) else []
        task_ids = [str(change.get("task_id")) for change in changes if isinstance(change, dict)]
        reason = str(payload.get("reason") or "A semantic run change needs operator review")
        reviews.append(
            {
                "id": path.stem,
                "taskId": task_ids[0] if task_ids else "sleipnir-control",
                "title": f"Revision {path.stem.removeprefix('revision-')}",
                "summary": reason[:720],
                "files": [],
                "checks": [
                    {"label": f"{len(changes)} proposed plan change(s)", "status": "passed"},
                    {"label": "Operator approval", "status": "pending"},
                ],
                "risk": "medium",
            }
        )
    return reviews


def _capabilities() -> list[dict[str, Any]]:
    return [
        {"id": "computer", "label": "Desktop control", "detail": "Pointer, keyboard, screen capture, and shell actions in the audited operator lane.", "state": "ready", "audited": True},
        {"id": "browser", "label": "Browser", "detail": "Persistent Playwright session for authenticated web work.", "state": "ready", "audited": True},
        {"id": "clipboard", "label": "Clipboard", "detail": "Native clipboard handoff without copying payloads into the run log.", "state": "ready", "audited": True},
        {"id": "credentials", "label": "Credentials", "detail": "Official CLI sessions and operator-provided environment variables.", "state": "ready", "audited": True},
        {"id": "ios", "label": "iOS lane", "detail": "Build and simulator support; device signing remains operator-scoped.", "state": "limited", "audited": True},
        {"id": "party", "label": "Encrypted party", "detail": "Authenticated cross-machine collaboration and delegation.", "state": "limited", "audited": True},
    ]


def build_dashboard_snapshot(
    plan: Plan,
    records: list[Record],
    *,
    run_root: Path,
    now: datetime | None = None,
    active: bool | None = None,
    staled_at: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Project a run without ever opening a worker artifact."""
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    staled_at = staled_at or {}
    states = fold_results(plan, records, staled_at=staled_at)
    latest = _latest_records(records)
    statuses = Counter(state.status for state in states.values())
    reviews = _reviews(run_root)
    is_active = run_is_active(run_root) if active is None else active
    budget = _budget_snapshot(records, now)
    manifest = build_manifest(plan, records, budget, generated_at=now, staled_at=staled_at)
    total = len(plan.tasks)
    completed = statuses[TaskStatus.DONE] + statuses[TaskStatus.SKIPPED]

    tasks: list[dict[str, Any]] = []
    for task_id in plan.topological_order():
        task = plan.by_id[task_id]
        state = states[task_id]
        record = latest.get(task_id)
        checks = [getattr(check, "type", type(check).__name__) for check in task.acceptance]
        if not checks:
            checks = [f"output · {output.name}" for output in task.outputs.outputs]
        tasks.append(
            {
                "id": task.id,
                "title": task.description,
                "state": state.status.value,
                "tier": task.tier.value,
                "model": (
                    f"{record.routing.adapter.value}/{record.routing.model}" if record else None
                ),
                "group": task.group,
                "progress": 100 if state.status is TaskStatus.DONE else (50 if state.status is TaskStatus.RUNNING else 0),
                "dependsOn": list(task.depends_on),
                "attempt": state.open_attempt or state.attempts,
                "maxAttempts": task.retry.max_attempts,
                "summary": state.summary or (f"Blocked by {', '.join(state.blocked_by)}" if state.blocked_by else "Awaiting dispatch."),
                "checks": checks,
            }
        )

    routes: list[dict[str, Any]] = []
    for task_id in plan.topological_order():
        record = latest.get(task_id)
        if record is None:
            continue
        routes.append(
            {
                "taskId": task_id,
                "tier": record.routing.tier_final.value,
                "provider": _provider(record.routing.adapter),
                "model": record.routing.model,
                "costLabel": (
                    f"${record.cost.amount_usd:.4f}"
                    if isinstance(record, AttemptFinished)
                    and record.cost.billing_mode is BillingMode.METERED
                    else "subscription"
                ),
                "latencyLabel": "active" if states[task_id].status is TaskStatus.RUNNING else "complete",
                "rationale": record.routing.rationale or "Configured route.",
                "status": "selected" if states[task_id].status is TaskStatus.RUNNING else "available",
            }
        )

    timeline: list[dict[str, Any]] = []
    for index, record in enumerate(reversed(records[-60:])):
        if isinstance(record, AttemptStarted):
            title, detail, tone, stamp = (
                "Dispatch started",
                f"{record.task_id} · {record.routing.tier_final.value} · {record.routing.adapter.value}",
                "live",
                record.started_at,
            )
            kind = "dispatch_started"
        else:
            succeeded = record.status.value == "succeeded"
            title = "Task completed" if succeeded else "Task needs attention"
            detail = f"{record.task_id} · attempt {record.attempt} · {record.status.value}"
            tone = "success" if succeeded else "warning"
            stamp = record.ended_at
            kind = "task_completed" if succeeded else "recovery"
        timeline.append(
            {"id": f"record-{len(records) - index}", "at": _iso(stamp), "kind": kind, "title": title, "detail": detail, "taskId": record.task_id, "tone": tone}
        )

    finished = [record for record in records if isinstance(record, AttemptFinished)]
    codex_tokens = sum(
        record.usage.total_tokens for record in finished if record.cost.quota_pool == "codex"
    )
    notional = sum(
        record.cost.amount_usd
        for record in finished
        if record.cost.billing_mode is BillingMode.SUBSCRIPTION
    )
    state = _run_state(statuses, total, active=is_active, reviews=reviews)
    return {
        "source": "core",
        "generatedAt": _iso(now),
        "runtime": {
            "connected": True,
            "label": "Local core connected",
            "version": _package_version(),
            "platform": f"{host_platform.system()} · {host_platform.machine()}",
        },
        "run": {
            "id": plan.plan_id,
            "name": plan.goal[:72],
            "goal": plan.goal,
            "state": state,
            "revision": plan.revision,
            "progress": round(completed * 100 / total) if total else 0,
            "manifestTokens": manifest.estimate_tokens(),
            "startedAt": _iso(plan.created_at),
            "workspace": str(run_root.resolve()),
        },
        "tasks": tasks,
        "routes": routes,
        "budgets": [
            {"id": "claude-window", "label": "Claude window", "kind": "tokens", "used": budget.window_tokens_used, "limit": None, "unit": "tokens", "resetsAt": _iso(budget.window_end)},
            {"id": "codex-window", "label": "Codex window", "kind": "tokens", "used": codex_tokens, "limit": None, "unit": "tokens", "resetsAt": None},
            {"id": "metered", "label": "Metered spend", "kind": "metered", "used": budget.metered_spend_usd, "limit": None, "unit": "USD", "resetsAt": None},
            {"id": "notional", "label": "Notional value", "kind": "notional", "used": notional, "limit": None, "unit": "USD", "resetsAt": None},
        ],
        "timeline": timeline,
        "reviews": reviews,
        "capabilities": _capabilities(),
        "audit": [],
        "messages": [],
        "voice": {
            "phase": "off",
            "heard": "",
            "level": 0,
            "privacyLabel": "Microphone is off",
            "settings": {
                "wakeName": "Sleipnir",
                "localWake": True,
                "startAtLogin": False,
                "pushToTalkShortcut": "Space",
                "transcription": "local",
                "responseModel": "openrouter/auto",
                "escalation": "automatic",
                "voiceProvider": "system",
                "voiceId": "system-natural",
                "accent": "neutral",
                "interruptible": True,
            },
        },
    }


def load_dashboard(run_root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    run_root = run_root.resolve()
    plan_path = run_root / "plan.json"
    if not plan_path.is_file():
        raise FileNotFoundError(f"no Sleipnir plan at {plan_path}")
    plan = Plan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    records = ResultLog(run_root / "results.jsonl").read()
    staled_at = read_staleness(run_root / "revisions.jsonl")
    return build_dashboard_snapshot(
        plan, records, run_root=run_root, now=now, staled_at=staled_at
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m sleipnir.gui")
    subparsers = parser.add_subparsers(dest="command", required=True)
    snapshot = subparsers.add_parser("snapshot", help="print the desktop dashboard JSON")
    snapshot.add_argument("--run-root", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "snapshot":
        print(json.dumps(load_dashboard(args.run_root), separators=(",", ":")))
        return 0
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["build_dashboard_snapshot", "load_dashboard", "main"]
