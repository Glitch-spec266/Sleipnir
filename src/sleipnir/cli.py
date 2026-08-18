"""Command line interface.

    sleipnir plan "<prompt>"   decompose into plan.json, then exit
    sleipnir run               execute the DAG within deps, concurrency, budget
    sleipnir status            DAG state, spend, headroom
    sleipnir resume            recover a partial run
    sleipnir explain <id>      routing rationale and artifact paths

`run` and `resume` are the same operation. Status is a fold of the append-only
log, so re-running simply finds the completed work already done — recovery is
the normal path, not a special mode.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sleipnir.adapters import ClaudeAdapter, CodexAdapter, OpenRouterAdapter
from sleipnir.adapters.base import BaseAdapter
from sleipnir.artifacts import AttemptWorkspace
from sleipnir.budget import BudgetGovernor, render_decisions
from sleipnir.config import ConfigError, SleipnirConfig
from sleipnir.executor import Executor, ExecutorConfig
from sleipnir.pricing import (
    DEFAULT_MODELS_URL,
    CatalogSnapshot,
    CatalogUnavailableError,
    ModelCatalog,
)
from sleipnir.projection import build_manifest, fold_results
from sleipnir.router import RoutingError, TierRouter
from sleipnir.runlog import ResultLog
from sleipnir.schema import Adapter, AttemptFinished, Plan, TaskStatus

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

    target = run_root / PLAN_FILENAME
    if target.exists() and not args.force:
        raise CliError(f"{target} already exists; pass --force to overwrite it")

    planner_task = build_planner_task(args.prompt)
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
        )
    except PlanningError as exc:
        raise CliError(str(exc)) from exc

    target.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    print(f"wrote {target} — {len(plan.tasks)} tasks")
    for task in plan.tasks:
        deps = f" <- {', '.join(task.depends_on)}" if task.depends_on else ""
        print(f"  {task.id:<20} {task.tier.value:<11}{deps}")
    return 0


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
        states = fold_results(plan, log.read())
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

    print(report.render())
    return 0 if report.failed == 0 else 1


async def cmd_status(args: argparse.Namespace) -> int:
    config = load_config(args)
    run_root = Path(args.run_root)
    plan = load_plan(run_root)
    log = result_log(run_root)
    records = log.read()
    states = fold_results(plan, records)

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
        plan, records, snapshot, generated_at=datetime.now(UTC)
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


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sleipnir",
        description="Budget-aware agentic orchestrator.",
    )
    parser.add_argument("--config", help="path to sleipnir.toml (default: discover in cwd)")
    parser.add_argument("--run-root", default=".", help="run directory (default: .)")
    parser.add_argument(
        "--cache-read-weight",
        type=float,
        default=1.0,
        help="weight of a cache-read token against the window (default 1.0, "
             "which deliberately over-estimates; see DESIGN.md)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

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
        run_parser.add_argument("--concurrency", type=int, help="override the config cap")
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

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(args.func(args))
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
