"""Command line interface.

Two top-level modes:

    sleipnir chat              the direct harness — talk to claude or codex
                               with host capabilities attached (/help inside)
    sleipnir project plan "<prompt>"   decompose into plan.json
    sleipnir project run       execute the DAG within deps, concurrency, budget

The bare command is the chat console, the way bare `claude` is a session.
Project commands also remain at top level as aliases during migration, so
existing scripts keep working.

Within project mode, `run` and `resume` are the same operation: status is a
fold of the append-only log, so re-running simply finds the completed work
already done — recovery is the normal path, not a special mode.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import getpass
import hashlib
import math
import os
import shlex
import shutil
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sleipnir.adapters import ClaudeAdapter, CodexAdapter, OpenRouterAdapter
from sleipnir.adapters.base import BaseAdapter, DispatchOutcome
from sleipnir.artifacts import (
    AttemptWorkspace,
    WorkspaceCollisionError,
    contained_regular_file,
)
from sleipnir.budget import BudgetGovernor, render_decisions
from sleipnir.config import ConfigError, SleipnirConfig
from sleipnir.executor import (
    ConcurrentExecutionError,
    Executor,
    ExecutorConfig,
    cost_from_outcome,
)
from sleipnir.pricing import (
    DEFAULT_MODELS_URL,
    CatalogSnapshot,
    CatalogUnavailableError,
    ModelCatalog,
)
from sleipnir.gate import escalation_changes, evaluate_gate
from sleipnir.projection import build_manifest, fold_results
from sleipnir.router import RoutingError, TierRouter
from sleipnir.runlog import ResultLog, RunLock, RunLockError, run_is_active
from sleipnir.schema import (
    Adapter,
    AttemptFinished,
    AttemptStatus,
    FailureKind,
    Plan,
    ProducedArtifact,
    RoutingDecision,
    Task,
    TaskStatus,
    Tier,
)
from sleipnir.tui import render_dashboard

PLAN_FILENAME = "plan.json"
RESULTS_FILENAME = "results.jsonl"

_STATUS_MARK = {
    TaskStatus.DONE: "+",
    TaskStatus.STALE: "~",
    TaskStatus.RUNNING: ">",
    TaskStatus.READY: ".",
    TaskStatus.BLOCKED: " ",
    TaskStatus.PARTIAL: "/",
    TaskStatus.FAILED: "x",
    TaskStatus.SKIPPED: "-",
    TaskStatus.SUPERSEDED: "s",
    TaskStatus.CANCELLED: "c",
}


class CliError(RuntimeError):
    """Anything the user can fix. Printed without a traceback."""


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be finite and greater than zero")
    return parsed


def nonnegative_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError("must be finite and non-negative")
    return parsed


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


def build_adapters(config: SleipnirConfig) -> dict[Adapter, BaseAdapter]:
    """One adapter instance per backend kind, carrying its billing mode."""
    adapters: dict[Adapter, BaseAdapter] = {}
    for backend in config.backends.values():
        if backend.adapter in adapters:
            continue
        match backend.adapter:
            case Adapter.CLAUDE:
                adapters[Adapter.CLAUDE] = ClaudeAdapter(billing_mode=backend.billing)
            case Adapter.CODEX:
                adapters[Adapter.CODEX] = CodexAdapter(billing_mode=backend.billing)
            case Adapter.OPENROUTER:
                adapters[Adapter.OPENROUTER] = OpenRouterAdapter()
    return adapters


def load_config(args: argparse.Namespace) -> SleipnirConfig:
    path = Path(args.config) if args.config else SleipnirConfig.discover(Path.cwd())
    if path is None:
        raise CliError(
            "no sleipnir.toml found. Copy sleipnir.example.toml to sleipnir.toml "
            "and edit it, or pass --config."
        )
    try:
        return SleipnirConfig.load(path)
    except ConfigError as exc:
        raise CliError(str(exc)) from exc


async def load_catalog(config: SleipnirConfig, *, required: bool) -> CatalogSnapshot | None:
    catalog = ModelCatalog(
        url=config.catalog_url or DEFAULT_MODELS_URL,
        ttl_s=config.catalog_ttl_s,
        **({"cache_path": config.catalog_cache_path} if config.catalog_cache_path else {}),
    )
    try:
        return await catalog.load()
    except CatalogUnavailableError as exc:
        if required:
            raise CliError(
                f"{exc}\n\nSleipnir will not guess model prices. Run once with network "
                "access to populate the cache, or point catalog_url at a mirror."
            ) from exc
        return None


def load_plan(run_root: Path) -> Plan:
    path = run_root / PLAN_FILENAME
    if not path.exists():
        raise CliError(f"no plan at {path}. Run `sleipnir plan \"<prompt>\"` first.")
    return Plan.model_validate_json(path.read_text(encoding="utf-8"))


def result_log(run_root: Path) -> ResultLog:
    return ResultLog(run_root / RESULTS_FILENAME)


def revision_staleness(run_root: Path) -> dict[str, int]:
    from sleipnir.revisions import read_staleness

    return read_staleness(run_root / "revisions.jsonl")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


async def cmd_plan(args: argparse.Namespace) -> int:
    from sleipnir.planner import PlanningError, build_planner_task, generate_plan

    config = load_config(args)
    catalog = await load_catalog(config, required=True)
    router = TierRouter(config, catalog)
    run_root = Path(args.run_root)
    run_root.mkdir(parents=True, exist_ok=True)

    try:
        with RunLock(run_root):
            target = run_root / PLAN_FILENAME
            if target.exists() and not args.force:
                raise CliError(f"{target} already exists; pass --force to overwrite it")

            planner_task = build_planner_task(args.prompt)
            planner_attempts = run_root / "artifacts" / f"task-{planner_task.id}"
            used_attempts: list[int] = []
            if planner_attempts.is_dir():
                for path in planner_attempts.glob("attempt-*"):
                    try:
                        used_attempts.append(int(path.name.removeprefix("attempt-")))
                    except ValueError:
                        continue
            planner_attempt = max(used_attempts, default=0) + 1
            try:
                routing = router.resolve(planner_task, attempt=1, tier=planner_task.tier)
            except RoutingError as exc:
                raise CliError(str(exc)) from exc

            print(f"planning with {routing.model} via {routing.adapter.value} ...", file=sys.stderr)
            try:
                plan, _ = await generate_plan(
                    args.prompt,
                    adapters=build_adapters(config),
                    routing=routing,
                    run_root=run_root,
                    attempt=planner_attempt,
                )
            except PlanningError as exc:
                raise CliError(str(exc)) from exc

            temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
            with temporary.open("x", encoding="utf-8") as handle:
                handle.write(plan.model_dump_json(indent=2))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            print(f"wrote {target} — {len(plan.tasks)} tasks")
            for task in plan.tasks:
                deps = f" <- {', '.join(task.depends_on)}" if task.depends_on else ""
                print(f"  {task.id:<20} {task.tier.value:<11}{deps}")
            return 0
    except RunLockError as exc:
        raise CliError(str(exc)) from exc


async def cmd_run(args: argparse.Namespace) -> int:
    config = load_config(args)
    run_root = Path(args.run_root)
    plan = load_plan(run_root)
    log = result_log(run_root)

    catalog = await load_catalog(config, required=True)
    router = TierRouter(config, catalog)
    for warning in catalog.warnings:
        print(f"! catalogue: {warning}", file=sys.stderr)

    orphans = log.open_attempts()
    if orphans:
        print(
            f"recovering {len(orphans)} interrupted attempt(s): "
            + ", ".join(f"{tid}#{attempt}" for tid, attempt in sorted(orphans)),
            file=sys.stderr,
        )

    governor: BudgetGovernor | None = None
    if not args.no_budget:
        governor = BudgetGovernor(config, router, cache_read_weight=args.cache_read_weight)
        states = fold_results(plan, log.read(), staled_at=revision_staleness(run_root))
        governor.plan_tiers(plan, states)
        if governor.decisions:
            print(f"budget downshifts ({len(governor.decisions)}):", file=sys.stderr)
            print(render_decisions(governor.decisions), file=sys.stderr)

    executor = Executor(
        plan,
        adapters=build_adapters(config),
        router=router,
        log=log,
        config=ExecutorConfig(
            run_root=run_root,
            concurrency=args.concurrency or config.concurrency,
            dry_run=args.dry_run,
        ),
        governor=governor,
        staled_at=revision_staleness(run_root),
    )

    if args.explain:
        print("\n=== routing ===")
        for task in plan.tasks:
            tier = governor.tier_for(task)[0] if governor else task.tier
            print(router.explain(task, tier=tier).render())
            print()

    if args.dry_run:
        report = await executor.run()
        print("=== dry run: nothing dispatched, nothing spent ===")
        for preview in report.previews:
            print(preview.render())
        print(f"\n{len(report.previews)} task(s) would be dispatched")
        return 0

    try:
        report = await executor.run()
    except asyncio.CancelledError:
        print("\ninterrupted; every in-flight attempt was recorded", file=sys.stderr)
        return 130
    except RoutingError as exc:
        raise CliError(str(exc)) from exc
    except ConcurrentExecutionError as exc:
        raise CliError(str(exc)) from exc

    print(report.render())
    return 0 if report.failed == 0 else 1


async def cmd_status(args: argparse.Namespace) -> int:
    config = load_config(args)
    run_root = Path(args.run_root)
    plan = load_plan(run_root)
    log = result_log(run_root)
    records = log.read()
    staled_at = revision_staleness(run_root)
    states = fold_results(plan, records, staled_at=staled_at)

    catalog = await load_catalog(config, required=False)
    snapshot = None
    if catalog is not None:
        governor = BudgetGovernor(
            config, TierRouter(config, catalog), cache_read_weight=args.cache_read_weight
        )
        metered = sum(
            record.cost.amount_usd
            for record in records
            if isinstance(record, AttemptFinished)
            and record.cost.billing_mode.value == "metered"
        )
        snapshot = governor.snapshot(plan, states, metered_spent_usd=metered)

    print(f"plan {plan.plan_id}  revision {plan.revision}  {len(plan.tasks)} tasks")
    print(f"goal: {plan.goal[:120]}")
    print()
    for task_id in plan.topological_order():
        state = states[task_id]
        task = plan.by_id[task_id]
        mark = _STATUS_MARK.get(state.status, "?")
        extra = f"  attempts={state.attempts}" if state.attempts else ""
        blocked = f"  blocked_by={','.join(state.blocked_by)}" if state.blocked_by else ""
        print(
            f" [{mark}] {task_id:<20} {state.status.value:<11} {task.tier.value:<11}"
            f"${state.cost_usd:>8.4f}{extra}{blocked}"
        )

    print()
    if snapshot is None:
        print("budget: unavailable (no model catalogue — run once with network access)")
        return 0

    headroom = snapshot.window_headroom_tokens
    print(f"window   : {snapshot.window_start:%H:%M} -> {snapshot.window_end:%H:%M} UTC")
    print(f"used     : {snapshot.window_tokens_used:,} tokens")
    print(f"burn rate: {snapshot.burn_rate_tokens_per_hour:,.0f} tokens/hour")
    print(
        "headroom : "
        + (f"{headroom:,} tokens" if headroom is not None else "unknown (set window_tokens_limit)")
    )
    print(f"projected: {snapshot.projected_plan_window_tokens:,} window tokens for the rest")
    print(f"metered  : ${snapshot.metered_spend_usd:.4f} spent, "
          f"${snapshot.projected_plan_cost_usd:.4f} projected")
    for warning in snapshot.parse_warnings:
        print(f"! {warning}")

    manifest = build_manifest(
        plan, records, snapshot, generated_at=datetime.now(UTC), staled_at=staled_at
    )
    print(f"\nmanifest: {manifest.estimate_tokens():,} tokens "
          f"({len(manifest.frontier)} on the frontier)")
    return 0


async def cmd_explain(args: argparse.Namespace) -> int:
    config = load_config(args)
    run_root = Path(args.run_root)
    plan = load_plan(run_root)
    if args.task_id not in plan.by_id:
        raise CliError(f"no task {args.task_id!r} in {run_root / PLAN_FILENAME}")
    task = plan.by_id[args.task_id]
    log = result_log(run_root)
    records = [
        record
        for record in log.read()
        if isinstance(record, AttemptFinished) and record.task_id == task.id
    ]

    catalog = await load_catalog(config, required=False)
    if catalog is not None:
        print(TierRouter(config, catalog).explain(task).render())
    else:
        print(f"task {task.id}\n  tier declared : {task.tier.value}"
              "\n  (no catalogue available, so live routing cannot be shown)")

    print("\ncontract:")
    print(f"  depends on : {', '.join(task.depends_on) or '(nothing)'}")
    print(f"  reads      : summaries={task.inputs.summaries or '[]'} "
          f"artifacts={[a.path for a in task.inputs.artifacts] or '[]'}")
    print(f"  produces   : {[o.path for o in task.outputs.outputs]}")
    print(f"  checked by : {[c.type for c in task.acceptance] or '(nothing)'}")
    print(f"  downshift  : {'FORBIDDEN' if task.no_downshift else 'allowed'}")

    if not records:
        print("\nno attempts yet")
        return 0

    print("\nattempts:")
    for record in records:
        workspace = AttemptWorkspace(run_root, task.id, record.attempt)
        print(f"  #{record.attempt} {record.status.value} "
              f"({record.failure_kind.value if record.failure_kind else 'clean'}) "
              f"{record.routing.model} via {record.routing.adapter.value} "
              f"{record.wall_time_s:.1f}s ${record.cost.amount_usd:.4f}")
        if record.routing.downshift_reason:
            print(f"      downshifted: {record.routing.downshift_reason}")
        print(f"      rationale : {record.routing.rationale}")
        print(f"      artifacts : {workspace.dir}")
        for artifact in record.artifacts:
            print(f"        {artifact.path}  ({artifact.bytes}B)")
        if record.missing_outputs:
            print(f"      MISSING   : {', '.join(record.missing_outputs)}")
        for check in record.checks:
            print(f"      check {check.check_type}: "
                  f"{'pass' if check.passed else 'FAIL'} {check.detail[:120]}")
        print(f"      summary   : {record.summary[:200]}")
    return 0


async def cmd_tui(args: argparse.Namespace) -> int:
    """Render a static or live dashboard; optionally own and execute the run."""
    config = load_config(args)
    run_root = Path(args.run_root)
    plan = load_plan(run_root)
    log = result_log(run_root)
    # Read-only monitor modes are log-derived and must stay instant/offline.
    # Only the owning execution mode needs live catalogue routing/projections.
    catalog = await load_catalog(config, required=True) if args.execute else None
    governor: BudgetGovernor | None = None
    executor: Executor | None = None
    control_events: list[str] = []

    if catalog is not None:
        router = TierRouter(config, catalog)
        governor = BudgetGovernor(config, router, cache_read_weight=args.cache_read_weight)
        states = fold_results(plan, log.read(), staled_at=revision_staleness(run_root))
        governor.plan_tiers(plan, states)
        if args.execute:
            executor = Executor(
                plan,
                adapters=build_adapters(config),
                router=router,
                log=log,
                config=ExecutorConfig(
                    run_root=run_root,
                    concurrency=args.concurrency or config.concurrency,
                ),
                governor=governor,
                staled_at=revision_staleness(run_root),
            )

    execution: asyncio.Task[Any] | None = None
    orchestrating = bool(args.orchestrate)
    if orchestrating:
        args._event_sink = control_events.append
        execution = asyncio.create_task(cmd_orchestrate(args), name="sleipnir-orchestrator")
    elif executor is not None:
        execution = asyncio.create_task(executor.run(), name="sleipnir-executor")

    interactive = sys.stdout.isatty()
    full_screen = interactive and (args.watch or execution is not None)
    last_render_key: tuple[Any, ...] | None = None
    if full_screen:
        print("\x1b[?1049h\x1b[?25l", end="", flush=True)
    try:
        while True:
            # A watched orchestrator may atomically replace plan.json after a
            # revision. The dashboard must not remain pinned to the old DAG.
            if orchestrating or (execution is None and args.watch):
                plan = load_plan(run_root)
            records = log.read()
            states = fold_results(
                plan, records, staled_at=revision_staleness(run_root)
            )
            snapshot = None
            if governor is not None:
                metered = sum(
                    record.cost.amount_usd
                    for record in records
                    if isinstance(record, AttemptFinished)
                    and record.cost.billing_mode.value == "metered"
                )
                snapshot = governor.snapshot(plan, states, metered_spent_usd=metered)
            active = (execution is not None and not execution.done()) or run_is_active(run_root)
            activity = control_events[-1] if control_events else None
            frame = render_dashboard(
                plan,
                records,
                snapshot,
                active=active,
                staled_at=revision_staleness(run_root),
                proposed_revisions=len(list((run_root / "proposals").glob("*.json")))
                if (run_root / "proposals").is_dir()
                else 0,
                activity=activity,
            )
            render_key = (plan.revision, len(records), activity, active)
            if full_screen or render_key != last_render_key:
                if full_screen:
                    print("\x1b[H\x1b[2J", end="")
                print(frame, flush=True)
                last_render_key = render_key

            if execution is not None and execution.done():
                result = await execution
                if orchestrating:
                    return int(result)
                return 0 if result.failed == 0 else 1
            if not args.watch and execution is None:
                return 0
            await asyncio.sleep(args.refresh)
    except asyncio.CancelledError:
        if execution is not None and not execution.done():
            execution.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await execution
        raise
    finally:
        if full_screen:
            print("\x1b[?25h\x1b[?1049l", end="", flush=True)


def _orchestration_event(
    args: argparse.Namespace, message: str, *, error: bool = False
) -> None:
    sink = getattr(args, "_event_sink", None)
    if sink is not None:
        sink(("ERROR: " if error else "") + message)
        return
    print(message, file=sys.stderr if error else sys.stdout)


def _record_control_result(
    *,
    log: ResultLog,
    run_root: Path,
    control_task: Task,
    attempt: int,
    plan_revision: int,
    routing: RoutingDecision,
    run_id: str,
    started_at: datetime,
    ended_at: datetime,
    outcome: DispatchOutcome,
    decision_path: Path | None,
    summary: str,
    succeeded: bool,
) -> None:
    """Put sparse-brain spend on the same durable accounting stream."""
    artifacts: list[ProducedArtifact] = []
    if decision_path is not None and contained_regular_file(decision_path, run_root):
        decision_bytes = decision_path.read_bytes()
        artifacts.append(ProducedArtifact(
            name="decision",
            path=str(decision_path.relative_to(run_root)),
            bytes=len(decision_bytes),
            sha256=hashlib.sha256(decision_bytes).hexdigest(),
        ))
    bounded = summary[: AttemptFinished.SUMMARY_MAX_CHARS]
    workspace = decision_path.parent if decision_path is not None else None
    log.append(AttemptFinished(
        run_id=run_id,
        task_id=control_task.id,
        attempt=attempt,
        spec_hash=control_task.spec_hash(),
        plan_revision=plan_revision,
        routing=routing,
        status=AttemptStatus.SUCCEEDED if succeeded else AttemptStatus.FAILED,
        failure_kind=None if succeeded else FailureKind.ACCEPTANCE_FAILED,
        started_at=started_at,
        ended_at=ended_at,
        wall_time_s=(ended_at - started_at).total_seconds(),
        usage=outcome.usage,
        cost=cost_from_outcome(outcome, routing),
        artifacts=artifacts,
        missing_outputs=[] if succeeded or artifacts else ["decision"],
        checks=[],
        summary=bounded,
        summary_truncated=len(summary) > len(bounded),
        exit_code=outcome.exit_code,
        stdout_path=(
            str((workspace / "stdout.log").relative_to(run_root)) if workspace else None
        ),
        stderr_path=(
            str((workspace / "stderr.log").relative_to(run_root)) if workspace else None
        ),
    ))


async def cmd_orchestrate(args: argparse.Namespace) -> int:
    """Execute autonomously and invoke the scarce brain only at an impasse."""
    from sleipnir.orchestrator import ControlAction, ControlError, build_control_task, run_control_cycle
    from sleipnir.revisions import RevisionError, apply_revision, persist_revision

    config = load_config(args)
    run_root = Path(args.run_root)
    catalog = await load_catalog(config, required=True)
    router = TierRouter(config, catalog)
    adapters = build_adapters(config)
    log = result_log(run_root)

    try:
        lock = RunLock(run_root)
        lock.__enter__()
    except RunLockError as exc:
        raise CliError(str(exc)) from exc
    try:
        plan = load_plan(run_root)
        for cycle in range(1, args.max_cycles + 1):
            governor = BudgetGovernor(config, router, cache_read_weight=args.cache_read_weight)
            staled_at = revision_staleness(run_root)
            states = fold_results(plan, log.read(), staled_at=staled_at)
            governor.plan_tiers(plan, states)
            executor = Executor(
                plan,
                adapters=adapters,
                router=router,
                log=log,
                config=ExecutorConfig(
                    run_root=run_root,
                    concurrency=args.concurrency or config.concurrency,
                    acquire_lock=False,
                ),
                governor=governor,
                staled_at=staled_at,
            )
            report = await executor.run()
            states = report.final_states
            if all(
                state.status is TaskStatus.DONE
                for state in states.values()
            ):
                _orchestration_event(
                    args,
                    f"orchestration complete after {cycle} cycle(s): {report.render()}",
                )
                return 0

            # The phase gate. Workers have stopped; before paying for a
            # reason-tier spawn, see whether the failure is one the harness can
            # answer itself by re-running the failed modules with a better
            # agent. Escalation is routing-only, so it cannot change what the
            # work means — and it walks a finite ladder, so it cannot loop.
            verdict = evaluate_gate(plan, states)
            _orchestration_event(args, f"phase gate, cycle {cycle}:\n{verdict.render()}")
            if verdict.failed_groups and not args.no_auto_escalate:
                escalations = escalation_changes(plan, verdict, states)
                if escalations:
                    reason = (
                        f"gate escalation: {len(verdict.failed_groups)} failed module(s), "
                        f"retrying {len(escalations)} task(s) one tier stronger"
                    )
                    try:
                        plan, audit = apply_revision(
                            plan, escalations, reason=reason, records=log.read()
                        )
                    except RevisionError as exc:  # pragma: no cover - defensive
                        raise CliError(f"gate escalation was not applicable: {exc}") from exc
                    persist_revision(
                        run_root / PLAN_FILENAME,
                        run_root / "revisions.jsonl",
                        plan,
                        audit,
                    )
                    _orchestration_event(args, f"{reason} (revision {audit.revision})")
                    continue  # rebuild the failed modules without waking the brain

            records = log.read()
            metered = sum(
                record.cost.amount_usd
                for record in records
                if isinstance(record, AttemptFinished)
                and record.cost.billing_mode.value == "metered"
            )
            snapshot = governor.snapshot(plan, states, metered_spent_usd=metered)
            manifest = build_manifest(
                plan,
                records,
                snapshot,
                generated_at=datetime.now(UTC),
                downshift_active=bool(governor.decisions),
                staled_at=staled_at,
            )
            control_task = build_control_task(manifest, plan)
            allowed, why = governor.should_dispatch(control_task)
            if not allowed:
                raise CliError(f"control brain blocked by budget governor: {why}")

            control_root = run_root / "artifacts" / f"task-{control_task.id}"
            used: list[int] = []
            if control_root.is_dir():
                for path in control_root.glob("attempt-*"):
                    try:
                        used.append(int(path.name.removeprefix("attempt-")))
                    except ValueError:
                        continue
            attempt = max(used, default=0) + 1
            routing = router.resolve(control_task, attempt=attempt, tier=Tier.REASON)
            if routing.adapter is not Adapter.CLAUDE and not args.allow_non_claude_brain:
                raise CliError(
                    f"reason-tier control resolved to {routing.adapter.value}, not claude; "
                    "put a Claude backend first for [tiers.reason] or pass "
                    "--allow-non-claude-brain explicitly"
                )
            control_run_id = f"control-{datetime.now(UTC):%Y%m%dT%H%M%S}"
            control_started = datetime.now(UTC)
            try:
                decision, control_outcome, decision_path = await run_control_cycle(
                    manifest,
                    plan=plan,
                    adapters=adapters,
                    routing=routing,
                    run_root=run_root,
                    attempt=attempt,
                    env=os.environ,
                    run_id=control_run_id,
                )
            except ControlError as exc:
                if exc.outcome is not None:
                    _record_control_result(
                        log=log,
                        run_root=run_root,
                        control_task=control_task,
                        attempt=attempt,
                        plan_revision=plan.revision,
                        routing=routing,
                        run_id=control_run_id,
                        started_at=control_started,
                        ended_at=datetime.now(UTC),
                        outcome=exc.outcome,
                        decision_path=exc.output,
                        summary=str(exc),
                        succeeded=False,
                    )
                raise CliError(str(exc)) from exc
            control_ended = datetime.now(UTC)
            _record_control_result(
                log=log,
                run_root=run_root,
                control_task=control_task,
                attempt=attempt,
                plan_revision=plan.revision,
                routing=routing,
                run_id=control_run_id,
                started_at=control_started,
                ended_at=control_ended,
                outcome=control_outcome,
                decision_path=decision_path,
                summary=decision.reason,
                succeeded=True,
            )
            _orchestration_event(
                args, f"brain cycle {cycle}: {decision.action.value} — {decision.reason}"
            )

            if decision.action is ControlAction.STOP:
                return 1
            if decision.action is ControlAction.CONTINUE:
                _orchestration_event(
                    args,
                    "unchanged terminal plan cannot progress now; resume later",
                    error=True,
                )
                return 1
            semantic = any(change.op.value != "retarget_task" for change in decision.changes)
            if semantic and not args.auto_apply_semantic_revisions:
                proposals = run_root / "proposals"
                proposals.mkdir(parents=True, exist_ok=True)
                proposal = proposals / f"revision-{plan.revision + 1}-{datetime.now(UTC):%Y%m%dT%H%M%S}.json"
                with proposal.open("x", encoding="utf-8") as handle:
                    handle.write(decision.model_dump_json(indent=2))
                    handle.flush()
                    os.fsync(handle.fileno())
                _orchestration_event(
                    args,
                    f"semantic revision requires operator review: {proposal}\n"
                    f"apply with: sleipnir --run-root {run_root} apply-revision {proposal}",
                    error=True,
                )
                return 1
            try:
                plan, audit = apply_revision(
                    plan,
                    decision.changes,
                    reason=decision.reason,
                    records=records,
                )
            except RevisionError as exc:
                raise CliError(f"brain proposed an invalid revision: {exc}") from exc
            persist_revision(
                run_root / PLAN_FILENAME,
                run_root / "revisions.jsonl",
                plan,
                audit,
            )
            _orchestration_event(
                args,
                f"applied revision {audit.revision}: "
                f"superseded={audit.superseded or '[]'} stale={audit.staled or '[]'}"
            )
        raise CliError(f"orchestration stopped after the {args.max_cycles}-cycle safety cap")
    finally:
        lock.__exit__(None, None, None)


async def cmd_apply_revision(args: argparse.Namespace) -> int:
    """Apply one operator-reviewed control proposal under the run lock."""
    from sleipnir.orchestrator import ControlAction, ControlDecision
    from sleipnir.revisions import RevisionError, apply_revision, persist_revision

    run_root = Path(args.run_root)
    proposal_path = Path(args.proposal)
    proposal_mark_error: OSError | None = None
    try:
        decision = ControlDecision.model_validate_json(
            proposal_path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        raise CliError(f"invalid revision proposal {proposal_path}: {exc}") from exc
    if decision.action is not ControlAction.REVISE:
        raise CliError("apply-revision requires a proposal whose action is 'revise'")
    try:
        with RunLock(run_root):
            plan = load_plan(run_root)
            try:
                revised, audit = apply_revision(
                    plan,
                    decision.changes,
                    reason=decision.reason,
                    records=result_log(run_root).read(),
                )
            except RevisionError as exc:
                raise CliError(f"proposal is not valid for the current plan: {exc}") from exc
            persist_revision(
                run_root / PLAN_FILENAME,
                run_root / "revisions.jsonl",
                revised,
                audit,
            )
            # Pending proposals drive the TUI's review badge.  Preserve the
            # reviewed input as an audit artifact, but remove it from that
            # pending set after the plan is durably replaced.
            proposals_dir = (run_root / "proposals").resolve()
            if proposal_path.parent.resolve() == proposals_dir:
                try:
                    proposal_path.replace(proposal_path.with_suffix(".json.applied"))
                except OSError as exc:
                    proposal_mark_error = exc
    except RunLockError as exc:
        raise CliError(str(exc)) from exc
    print(
        f"applied reviewed revision {audit.revision}: "
        f"superseded={audit.superseded or '[]'} stale={audit.staled or '[]'}"
    )
    if proposal_mark_error is not None:
        print(
            f"warning: revision applied but proposal could not be marked applied: "
            f"{proposal_mark_error}",
            file=sys.stderr,
        )
    return 0


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


async def cmd_console(args: argparse.Namespace) -> int:
    from sleipnir.chat import PROVIDERS
    from sleipnir.console import ConsoleState, run_console

    state = ConsoleState()
    run_dir = Path(getattr(args, "run_root", ".")).resolve()
    state.run_dir = run_dir if run_dir.exists() else None
    if getattr(args, "ask_first", False):
        state.permission_mode = "acceptEdits"
    provider = getattr(args, "provider", "claude") or "claude"
    if provider not in PROVIDERS:
        raise CliError(f"unknown provider {provider!r}; choose one of {', '.join(PROVIDERS)}")
    state.provider = provider
    state.model = getattr(args, "model", "sonnet") or None
    return await run_console(state, splash=not getattr(args, "no_splash", False))


async def cmd_doctor(args: argparse.Namespace) -> int:
    from sleipnir.capabilities import browser, computer

    probe = computer.probe()
    rows = [
        ("session", probe.session_type),
        ("input injection (ydotool)", "yes" if probe.input_injection else "NO"),
        ("/dev/uinput writable", "yes" if probe.uinput_writable else "NO"),
        ("input daemon running", "yes" if probe.daemon_running else "not yet (starts on demand)"),
        ("screenshot tool", probe.screenshot_tool or "NONE"),
        ("browser control", "yes" if browser.available() else "NO"),
    ]
    for label, value in rows:
        print(f"  {label:<28} {value}")
    for note in probe.notes:
        print(f"  ! {note}")
    if not browser.available():
        print("  ! playwright is not installed — run `sleipnir setup`")
    ready = probe.ready and browser.available()
    print("\nhost control:", "ready" if ready else "incomplete — run `sleipnir setup`")
    return 0 if ready else 1


# The privileged steps, kept as data so `setup` can print exactly what it will
# run before it runs anything. Nobody should have to read the source to find
# out what a tool is about to do with sudo.
_UDEV_RULE = 'KERNEL=="uinput", GROUP="input", MODE="0660", OPTIONS+="static_node=uinput"'
_UDEV_PATH = "/etc/udev/rules.d/60-sleipnir-uinput.rules"


def _setup_steps() -> list[tuple[str, str, bool]]:
    """(description, shell command, needs_root) for this host."""
    if shutil.which("dnf"):
        install = "dnf install -y ydotool"
    elif shutil.which("apt-get"):
        install = "apt-get install -y ydotool"
    elif shutil.which("pacman"):
        install = "pacman -S --needed --noconfirm ydotool"
    else:
        install = ""
    steps: list[tuple[str, str, bool]] = []
    if install and not shutil.which("ydotool"):
        steps.append(("install ydotool (kernel-level input injection)", install, True))
    if not os.access("/dev/uinput", os.W_OK):
        steps.append(
            (
                "grant this user /dev/uinput via a udev rule",
                f"printf '%s\\n' '{_UDEV_RULE}' > {_UDEV_PATH} && "
                f"udevadm control --reload-rules && udevadm trigger",
                True,
            )
        )
        steps.append(
            (
                "add this user to the `input` group",
                # Quoted: $USER is environment-supplied and this string is
                # about to be handed to a root shell.
                f"usermod -aG input {shlex.quote(os.environ.get('USER') or getpass.getuser())}",
                True,
            )
        )
    try:
        import playwright  # noqa: F401
    except ImportError:
        steps.append(
            ("install the browser-control library", f"{sys.executable} -m pip install playwright", False)
        )
        steps.append(("download the Chromium build it drives", f"{sys.executable} -m playwright install chromium", False))
    return steps


async def cmd_setup(args: argparse.Namespace) -> int:
    """Do the one-time privileged install so no user has to hand-run sudo.

    Every root step is printed in full first.  A tool that asks for your
    password should show you the command it intends to run with it.
    """
    steps = _setup_steps()
    if not steps:
        print("host control is already set up; nothing to do.")
        return 0

    print("Sleipnir needs these one-time steps for host control:\n")
    for description, command, needs_root in steps:
        marker = "sudo" if needs_root else "    "
        print(f"  {marker}  {description}\n        $ {command}\n")

    if not args.yes:
        answer = input("run these now? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("nothing was run.")
            return 1

    for description, command, needs_root in steps:
        full = f"sudo sh -c {shlex.quote(command)}" if needs_root else command
        print(f"→ {description}")
        result = subprocess.run(full, shell=True, check=False)  # noqa: S602 - printed above
        if result.returncode != 0:
            print(f"error: step failed ({description}); stopping here.", file=sys.stderr)
            return 2

    print("\ndone. Log out and back in so the `input` group applies, then run `sleipnir doctor`.")
    return 0


async def cmd_computer(args: argparse.Namespace) -> int:
    from sleipnir.capabilities import computer

    action, rest = args.action, args.args
    try:
        if action == "screenshot":
            print(computer.screenshot(rest[0] if rest else "screen.png"))
        elif action == "type":
            computer.type_text(" ".join(rest))
        elif action == "key":
            # Accept both `ctrl shift t` and `ctrl+shift+t`.
            combo = [part for chunk in rest for part in chunk.split("+") if part]
            computer.key(*combo)
        elif action == "click":
            computer.click(rest[0] if rest else "left")
        elif action == "move":
            computer.move_mouse(int(rest[0]), int(rest[1]))
        elif action == "scroll":
            computer.scroll(int(rest[0]) if rest else -3)
    except (computer.CapabilityError, IndexError, ValueError) as error:
        raise CliError(str(error) or f"bad arguments for `computer {action}`") from error
    return 0


async def cmd_browser(args: argparse.Namespace) -> int:
    from sleipnir.capabilities.browser import Browser

    action, rest = args.action, args.args
    async with Browser(headless=args.headless) as web:
        if action == "open":
            if not rest:
                raise CliError("`browser open` needs a URL")
            await web.goto(rest[0])
            print(f"opened {rest[0]}")
        elif action == "text":
            print(await web.text(rest[0] if rest else "body"))
        elif action == "click":
            await web.click(rest[0])
        elif action == "fill":
            await web.fill(rest[0], rest[1])
        elif action == "screenshot":
            print(await web.screenshot(rest[0] if rest else "page.png"))
        elif action == "close":
            await web.shutdown()
            print("browser closed")
    return 0


async def cmd_secret(args: argparse.Namespace) -> int:
    """Ask the operator for a credential and type it straight into the target.

    The value is never returned to the caller, so an agent that runs this
    command learns only that a credential was supplied — which is the entire
    point of routing sign-ins through Sleipnir instead of the conversation.
    """
    from sleipnir.capabilities import handoff, secrets

    # A tool subprocess has no controlling terminal, so it cannot prompt. When
    # this command *is* run from a terminal — an operator testing it by hand —
    # prompting directly is still the shortest path and avoids requiring a
    # console to be open.
    if sys.stdin.isatty():
        print(f"Sleipnir needs a credential: {args.label}", file=sys.stderr)
        print("It is typed into the focused window and never stored.", file=sys.stderr)
        secret = secrets.capture(args.label)
        secrets.type_into_focused_window(secret, submit=args.submit)
        print("credential supplied")
        return 0

    request = handoff.request_secret(args.label, submit=args.submit)
    print(f"waiting for the Sleipnir console to supply: {args.label}", file=sys.stderr)
    try:
        status = handoff.await_answer(request)
    except TimeoutError as exc:
        raise CliError(str(exc)) from exc
    if status != "supplied":
        raise CliError(f"credential was not supplied ({status})")
    print("credential supplied")
    return 0


def _register_project_commands(subparsers: argparse._ActionsContainer) -> None:
    """Register every orchestration subcommand on one subparsers action.

    Called twice — once at the root, once under `project` — so `sleipnir run`
    keeps working as an alias while the canonical home becomes
    `sleipnir project run`. The global options are repeated on the nested
    parser with SUPPRESS defaults so `sleipnir project --run-root X plan`
    parses without clobbering values given at the root.
    """
    plan_parser = subparsers.add_parser("plan", help="decompose a prompt into plan.json")
    plan_parser.add_argument("prompt")
    plan_parser.add_argument("--force", action="store_true", help="overwrite an existing plan")
    plan_parser.set_defaults(func=cmd_plan)

    for name, help_text in (
        ("run", "execute the DAG"),
        ("resume", "continue a partial run (identical to run)"),
    ):
        run_parser = subparsers.add_parser(name, help=help_text)
        run_parser.add_argument("--dry-run", action="store_true",
                                help="print what would be dispatched, spend nothing")
        run_parser.add_argument("--concurrency", type=positive_int, help="override the config cap")
        run_parser.add_argument("--explain", action="store_true",
                                help="print why each task got its tier and model")
        run_parser.add_argument("--no-budget", action="store_true",
                                help="disable the budget governor entirely")
        run_parser.set_defaults(func=cmd_run)

    status_parser = subparsers.add_parser("status", help="DAG state, spend, headroom")
    status_parser.set_defaults(func=cmd_status)

    explain_parser = subparsers.add_parser("explain", help="routing rationale and artifacts")
    explain_parser.add_argument("task_id")
    explain_parser.set_defaults(func=cmd_explain)

    tui_parser = subparsers.add_parser("tui", help="live DAG, routing, and budget dashboard")
    tui_parser.add_argument("--watch", action="store_true",
                            help="refresh until interrupted (implied by execution modes)")
    tui_mode = tui_parser.add_mutually_exclusive_group()
    tui_mode.add_argument("--execute", "--run", action="store_true",
                          help="execute/resume workers while displaying them")
    tui_mode.add_argument("--orchestrate", action="store_true",
                          help="run workers plus sparse brain control behind the dashboard")
    tui_parser.add_argument("--concurrency", type=positive_int, help="override the config cap")
    tui_parser.add_argument("--refresh", type=positive_float, default=1.0,
                            help="seconds between frames (default: 1.0)")
    tui_parser.add_argument("--max-cycles", type=positive_int, default=8,
                            help="maximum brain/revision cycles (default: 8)")
    tui_parser.add_argument(
        "--auto-apply-semantic-revisions",
        action="store_true",
        help="allow brain-proposed semantic changes without human review",
    )
    tui_parser.add_argument(
        "--allow-non-claude-brain",
        action="store_true",
        help="permit control to route through a non-Claude adapter",
    )
    tui_parser.add_argument(
        "--no-auto-escalate",
        action="store_true",
        help="wake the brain on a failed module instead of retrying it one tier stronger",
    )
    tui_parser.set_defaults(func=cmd_tui)

    orchestrate_parser = subparsers.add_parser(
        "orchestrate", help="run workers and consult the bounded-context brain at impasses"
    )
    orchestrate_parser.add_argument("--concurrency", type=positive_int,
                                    help="override the config cap")
    orchestrate_parser.add_argument("--max-cycles", type=positive_int, default=8,
                                    help="maximum brain/revision cycles (default: 8)")
    orchestrate_parser.add_argument(
        "--auto-apply-semantic-revisions",
        action="store_true",
        help="allow brain-proposed task/edge semantic changes without human review",
    )
    orchestrate_parser.add_argument(
        "--allow-non-claude-brain",
        action="store_true",
        help="permit the control brain to route through a non-Claude adapter",
    )
    orchestrate_parser.add_argument(
        "--no-auto-escalate",
        action="store_true",
        help="wake the brain on a failed module instead of first retrying it "
             "one tier stronger (routing-only, so it cannot change task meaning)",
    )
    orchestrate_parser.set_defaults(func=cmd_orchestrate)

    revision_parser = subparsers.add_parser(
        "apply-revision", help="apply an operator-reviewed orchestration proposal"
    )
    revision_parser.add_argument("proposal", help="path to a saved proposal JSON file")
    revision_parser.set_defaults(func=cmd_apply_revision)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sleipnir",
        description="Budget-aware agentic harness and orchestrator.",
    )
    parser.add_argument("--config", help="path to sleipnir.toml (default: discover in cwd)")
    parser.add_argument("--run-root", default=".", help="run directory (default: .)")
    parser.add_argument(
        "--cache-read-weight",
        type=nonnegative_float,
        default=1.0,
        help="weight of a cache-read token against the window (default 1.0, "
             "which deliberately over-estimates; see DESIGN.md)",
    )
    # Not required: bare `sleipnir` opens the chat console, which is the door.
    subparsers = parser.add_subparsers(dest="command", required=False)

    console_parser = subparsers.add_parser(
        "chat", aliases=["console"], help="interactive console (claude or codex)"
    )
    console_parser.add_argument(
        "--provider", choices=["claude", "codex"], default="claude",
        help="which agent CLI receives your messages (switchable mid-session with /use)",
    )
    console_parser.add_argument(
        "--no-splash", action="store_true", help="skip the boot animation"
    )
    console_parser.add_argument(
        "--ask-first",
        action="store_true",
        help="confirm each tool use instead of granting full host control",
    )
    console_parser.add_argument(
        "--model",
        default="sonnet",
        help="model alias for the initial provider (default: sonnet for claude; "
             "/model switches later, 'default' defers to the account choice)",
    )
    console_parser.set_defaults(func=cmd_console)

    setup_parser = subparsers.add_parser(
        "setup", help="install and check host-control prerequisites"
    )
    setup_parser.add_argument(
        "--yes", action="store_true", help="do not ask before running privileged steps"
    )
    setup_parser.set_defaults(func=cmd_setup)

    doctor_parser = subparsers.add_parser("doctor", help="report host capability status")
    doctor_parser.set_defaults(func=cmd_doctor)

    computer_parser = subparsers.add_parser("computer", help="control keyboard, mouse and screen")
    computer_parser.add_argument(
        "action", choices=["screenshot", "type", "key", "click", "move", "scroll"]
    )
    computer_parser.add_argument("args", nargs="*")
    computer_parser.set_defaults(func=cmd_computer)

    browser_parser = subparsers.add_parser("browser", help="drive a real browser")
    browser_parser.add_argument(
        "action", choices=["open", "text", "click", "fill", "screenshot", "close"]
    )
    browser_parser.add_argument("args", nargs="*")
    browser_parser.add_argument("--headless", action="store_true")
    browser_parser.set_defaults(func=cmd_browser)

    secret_parser = subparsers.add_parser(
        "secret", help="ask the operator for a credential and inject it without storing it"
    )
    secret_parser.add_argument("action", choices=["prompt"])
    secret_parser.add_argument("label")
    secret_parser.add_argument(
        "--submit", action="store_true", help="press enter after typing the value"
    )
    secret_parser.set_defaults(func=cmd_secret)

    # The canonical namespace for orchestration...
    project_parser = subparsers.add_parser(
        "project", help="plan and orchestrate a multi-task project run"
    )
    project_parser.add_argument("--config", default=argparse.SUPPRESS)
    project_parser.add_argument("--run-root", default=argparse.SUPPRESS)
    project_parser.add_argument("--cache-read-weight", type=nonnegative_float,
                                default=argparse.SUPPRESS)
    project_subparsers = project_parser.add_subparsers(dest="project_command", required=True)
    _register_project_commands(project_subparsers)

    # ...with the legacy top-level names kept as aliases during migration.
    _register_project_commands(subparsers)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "func", None) is None:
        # Bare `sleipnir` is the chat console, the way bare `claude` is a session.
        args.func = cmd_console
        args.provider = "claude"
        args.no_splash = False
    try:
        return asyncio.run(args.func(args))
    except (CliError, WorkspaceCollisionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
