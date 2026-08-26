"""Concurrency-capped DAG execution.

The executor owns everything the adapters deliberately do not: readiness,
attempt numbering, the concurrency cap, cancellation, acceptance checks, cost
composition, and writing the append-only log.

It does *not* own routing (Phase 3) or budget (Phase 4). Both enter through
narrow seams — the :class:`Router` protocol and, later, a governor consulted in
:meth:`Executor._launch` — so neither phase has to reopen this module's core.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from sleipnir.adapters.base import (
    BaseAdapter,
    DispatchOutcome,
    DispatchPreview,
    DispatchRequest,
)
from sleipnir.artifacts import (
    INPUT_MANIFEST_FILENAME,
    AttemptWorkspace,
    WorkspaceCollisionError,
    clip_summary,
)
from sleipnir.checks import assert_checks_supported, run_checks
from sleipnir.context import resolve_inputs
from sleipnir.process import ProcessRunner
from sleipnir.projection import TaskState, fold_results
from sleipnir.runlog import ResultLog, RunLock, RunLockError
from sleipnir.schema import (
    Adapter,
    AttemptFinished,
    AttemptStarted,
    AttemptStatus,
    BillingMode,
    CheckResult,
    CostEstimate,
    FailureKind,
    Plan,
    ProducedArtifact,
    RoutingDecision,
    Task,
    TaskStatus,
    Tier,
)

#: Stand-in used when previewing a task whose dependencies have not run, so a
#: dry-run prompt is the right shape and roughly the right size.
DRY_RUN_SUMMARY = "<summary of this dependency, available at run time>"


class ConcurrentExecutionError(RuntimeError):
    """An unfinished attempt still belongs to a live executor process."""


def _pid_is_alive(pid: int) -> bool:
    """Probe process existence without sending a signal that changes state."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class Router(Protocol):
    """Tier -> concrete model. Implemented by TierRouter.

    ``downshift_reason`` is how the budget governor explains itself: it decides
    the tier, the router resolves the model, and the reason travels with the
    decision into the result record so every downshift is auditable.
    """

    def resolve(
        self,
        task: Task,
        *,
        attempt: int,
        tier: Tier,
        downshift_reason: str | None = None,
    ) -> RoutingDecision: ...


@dataclass(slots=True)
class StaticRouter:
    """Phase 2 placeholder: a fixed tier -> (adapter, model) table from config.

    Phase 3 replaces this with live OpenRouter data and downshift logic. It
    exists so the executor can be finished and tested now without hardcoding
    model names anywhere in the executor itself.
    """

    assignments: Mapping[Tier, tuple[Adapter, str]]

    def resolve(
        self,
        task: Task,
        *,
        attempt: int,
        tier: Tier,
        downshift_reason: str | None = None,
    ) -> RoutingDecision:
        if tier not in self.assignments:
            raise KeyError(f"no model configured for tier {tier.value!r}")
        adapter, model = self.assignments[tier]
        return RoutingDecision(
            tier_requested=task.tier,
            tier_final=tier,
            model=model,
            adapter=adapter,
            downshifted=bool(downshift_reason),
            downshift_reason=downshift_reason,
            escalated=tier is not task.tier and not downshift_reason,
            rationale=f"static assignment for tier {tier.value!r} (attempt {attempt})",
        )


class Governor(Protocol):
    """Budget control. Implemented by BudgetGovernor (Phase 4)."""

    def tier_for(self, task: Task) -> tuple[Tier, str | None]: ...

    def should_dispatch(self, task: Task, tier: Tier | None = None) -> tuple[bool, str]: ...

    def settle_dispatch(self, task: Task, cost: CostEstimate) -> None: ...


@dataclass(slots=True)
class ExecutorConfig:
    run_root: Path
    concurrency: int = 3
    grace_s: float = 5.0
    env: Mapping[str, str] | None = None
    dry_run: bool = False
    acquire_lock: bool = True

    def __post_init__(self) -> None:
        if self.concurrency < 1:
            raise ValueError("concurrency must be at least 1")
        if self.grace_s < 0:
            raise ValueError("grace_s cannot be negative")

    def resolved_env(self) -> Mapping[str, str]:
        return self.env if self.env is not None else os.environ


@dataclass(slots=True)
class RunReport:
    dispatched: int = 0
    succeeded: int = 0
    partial: int = 0
    failed: int = 0
    cancelled: int = 0
    cost_usd: float = 0.0
    #: Notional value of subscription-backed work: what it would have cost if
    #: metered. Reported separately because a run that spends $0 out of pocket
    #: while burning the window is not a free run, and a report line reading
    #: "cost=$0.0000" after real work is actively misleading.
    notional_usd: float = 0.0
    window_tokens: int = 0
    codex_tokens: int = 0
    server_tool_use: dict[str, int] = field(default_factory=dict)
    previews: list[DispatchPreview] = field(default_factory=list)
    final_states: dict[str, TaskState] = field(default_factory=dict)

    def render(self) -> str:
        tools = " ".join(
            f"{name}={count}" for name, count in sorted(self.server_tool_use.items())
        )
        return (
            f"dispatched={self.dispatched} ok={self.succeeded} partial={self.partial} "
            f"failed={self.failed} cancelled={self.cancelled} "
            f"metered=${self.cost_usd:.4f} notional=${self.notional_usd:.4f} "
            f"window_tokens={self.window_tokens}"
            f" codex_tokens={self.codex_tokens}"
            + (f" server_tools={tools}" if tools else "")
        )


def cost_from_outcome(
    outcome: DispatchOutcome, routing: RoutingDecision
) -> CostEstimate:
    """Compose the shared dollar/quota axes for worker and control calls."""
    metered = outcome.billing_mode is BillingMode.METERED
    codex_subscription = not metered and routing.adapter is Adapter.CODEX
    return CostEstimate(
        billing_mode=outcome.billing_mode,
        amount_usd=float(outcome.reported_cost_usd or 0.0),
        window_tokens=0 if metered or codex_subscription else outcome.usage.total_tokens,
        quota_pool=None if metered else routing.adapter.value,
        pricing=None,
        is_estimate=outcome.reported_cost_usd is None,
    )


class Executor:
    def __init__(
        self,
        plan: Plan,
        *,
        adapters: Mapping[Adapter, BaseAdapter],
        router: Router,
        log: ResultLog,
        config: ExecutorConfig,
        runner: ProcessRunner | None = None,
        run_id: str | None = None,
        governor: Governor | None = None,
        staled_at: Mapping[str, int] | None = None,
    ) -> None:
        assert_checks_supported(plan.tasks)
        self.plan = plan
        self.adapters = adapters
        self.router = router
        self.governor = governor
        self.log = log
        self.config = config
        self.runner = runner or ProcessRunner()
        # The random suffix matters: two executors started in the same second
        # would otherwise share a run_id, and adapters derive provider-side
        # session identifiers from it.
        self.run_id = run_id or (
            f"run-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
        )
        self._report = RunReport()
        self.staled_at = dict(staled_at or {})

    # -- state ---------------------------------------------------------------

    def _states(self) -> dict[str, TaskState]:
        return fold_results(self.plan, self.log.read(), staled_at=self.staled_at)

    def _summaries(self, states: Mapping[str, TaskState]) -> dict[str, str]:
        return {tid: state.summary for tid, state in states.items() if state.summary}

    def _artifact_dir_for(self, task_id: str) -> Path | None:
        """Directory of the latest *successful* attempt for ``task_id``.

        Later attempts do not overwrite earlier ones, so 'latest successful' is
        a real choice rather than a lookup — a task that failed twice and then
        succeeded must hand downstream consumers the third attempt.
        """
        best: int | None = None
        for record in self.log.read():
            if (
                isinstance(record, AttemptFinished)
                and record.task_id == task_id
                and record.status in (AttemptStatus.SUCCEEDED, AttemptStatus.PARTIAL)
            ):
                best = record.attempt if best is None else max(best, record.attempt)
        if best is None:
            return None
        return AttemptWorkspace(self.config.run_root, task_id, best).dir

    def _ready(self, states: Mapping[str, TaskState], skip: set[str]) -> list[Task]:
        # STALE and SUPERSEDED are revision work queues, not terminal states.
        # Require dependencies to be freshly DONE so a stale descendant cannot
        # race ahead using another stale descendant's pre-revision artifact.
        ready = [
            task
            for task in self.plan.tasks
            if task.id not in skip
            and states[task.id].status
            in (TaskStatus.READY, TaskStatus.STALE, TaskStatus.SUPERSEDED)
            and all(states[dep].status is TaskStatus.DONE for dep in task.depends_on)
        ]
        ready.sort(key=lambda task: (-task.priority, task.id))
        return ready

    # -- dry run -------------------------------------------------------------

    def dry_run(self) -> list[DispatchPreview]:
        """Everything the run would dispatch, spending nothing.

        Walks the DAG in topological order treating each task as if it had
        succeeded, so the whole plan is previewed rather than only the first
        wave. No directories are created and no records are written.
        """
        previews: list[DispatchPreview] = []
        states = self._states()
        for task_id in self.plan.topological_order():
            task = self.plan.by_id[task_id]
            if states[task_id].status is TaskStatus.DONE:
                continue
            attempt = states[task_id].attempts + 1
            routing = self.router.resolve(task, attempt=attempt, tier=task.tier)
            adapter = self._adapter_for(routing)
            request = self._request(task, attempt, routing, dry_run=True)
            preview = adapter.preview(request)
            if states[task_id].attempts:
                preview.notes.append(f"retry: {states[task_id].attempts} prior attempt(s)")
            previews.append(preview)
        self._report.previews = previews
        return previews

    def _adapter_for(self, routing: RoutingDecision) -> BaseAdapter:
        adapter = self.adapters.get(routing.adapter)
        if adapter is None:
            raise KeyError(f"no adapter registered for {routing.adapter.value!r}")
        return adapter

    def _request(
        self, task: Task, attempt: int, routing: RoutingDecision, *, dry_run: bool
    ) -> DispatchRequest:
        workspace = AttemptWorkspace(self.config.run_root, task.id, attempt)
        states = self._states()
        summaries = self._summaries(states)
        if dry_run:
            summaries = {
                dep: summaries.get(dep, DRY_RUN_SUMMARY)
                for task_ in self.plan.tasks
                for dep in task_.inputs.summaries
            }

        resolved = resolve_inputs(
            task,
            goal=self.plan.goal,
            run_root=self.config.run_root,
            summaries=summaries,
            artifact_dir_for=self._artifact_dir_for,
        )
        if not dry_run:
            workspace.prepare_fresh()
            workspace.write_json(INPUT_MANIFEST_FILENAME, resolved.manifest())

        return DispatchRequest(
            task=task,
            attempt=attempt,
            tier_final=routing.tier_final,
            model=routing.model,
            prompt=resolved.prompt,
            workspace=workspace,
            timeout_s=float(task.timeout_s),
            env=self.config.resolved_env(),
            grace_s=self.config.grace_s,
            run_id=self.run_id,
        )

    # -- run -----------------------------------------------------------------

    async def run(self) -> RunReport:
        if self.config.dry_run:
            self.dry_run()
            self._report.final_states = self._states()
            return self._report

        if not self.config.acquire_lock:
            return await self._run_locked()
        try:
            with RunLock(self.config.run_root):
                return await self._run_locked()
        except RunLockError as exc:
            raise ConcurrentExecutionError(str(exc)) from exc

    async def _run_locked(self) -> RunReport:
        """Execute while holding exclusive ownership of the run directory."""
        plan_path = self.config.run_root / "plan.json"
        if plan_path.exists():
            try:
                current = Plan.model_validate_json(plan_path.read_text(encoding="utf-8"))
            except Exception as exc:
                raise ConcurrentExecutionError(
                    f"plan became unreadable before execution lock was acquired: {exc}"
                ) from exc
            if current != self.plan:
                raise ConcurrentExecutionError(
                    "plan changed between CLI load and executor lock; rerun against the new revision"
                )
        self._recover_open_attempts()

        running: dict[str, asyncio.Task[None]] = {}
        launched: set[str] = set()
        try:
            while True:
                states = self._states()
                for task in self._ready(states, skip=set(running) | launched):
                    if len(running) >= self.config.concurrency:
                        break
                    attempt = states[task.id].attempts + 1
                    running[task.id] = asyncio.create_task(
                        self._attempt(task, attempt), name=f"{task.id}#{attempt}"
                    )
                    launched.add(task.id)

                if not running:
                    break

                done, _ = await asyncio.wait(
                    running.values(), return_when=asyncio.FIRST_COMPLETED
                )
                for finished in done:
                    task_id = finished.get_name().split("#")[0]
                    running.pop(task_id, None)
                    launched.discard(task_id)
                    if finished.cancelled():
                        continue
                    if (error := finished.exception()) is not None:
                        raise error
        except asyncio.CancelledError:
            await self._cancel_all(running)
            raise
        finally:
            self._report.final_states = self._states()
        return self._report

    def _recover_open_attempts(self) -> None:
        """Close attempts whose executor died before writing a terminal record.

        The start record was fsynced before dispatch, so its absence of a
        matching finish is the durable crash marker. Recording INTERRUPTED
        turns the normal projection back to READY (when retry policy permits)
        and ensures the retry uses a fresh attempt workspace.

        Usage is unknowable after an abrupt process death. The recovery record
        therefore preserves the adapter's billing axis and marks a zero amount
        as estimated; real subscription utilisation is reconciled separately
        by the budget governor's provider meter.
        """
        open_attempts = self.log.open_attempts()
        live = [started for started in open_attempts.values() if _pid_is_alive(started.pid)]
        if live:
            owners = ", ".join(
                f"{started.task_id}#{started.attempt} (pid {started.pid})"
                for started in live
            )
            raise ConcurrentExecutionError(
                f"refusing to recover attempt(s) still owned by a live executor: {owners}"
            )

        now = datetime.now(UTC)
        for started in open_attempts.values():
            task = self.plan.by_id.get(started.task_id)
            if task is None:
                # A log for a different plan is corruption, not something this
                # executor can safely invent a task contract for.
                raise ValueError(
                    f"open attempt {started.task_id!r} is not present in plan {self.plan.plan_id!r}"
                )
            adapter = self._adapter_for(started.routing)
            self.log.append(
                AttemptFinished(
                    run_id=started.run_id,
                    task_id=started.task_id,
                    attempt=started.attempt,
                    spec_hash=started.spec_hash,
                    plan_revision=started.plan_revision,
                    routing=started.routing,
                    status=AttemptStatus.FAILED,
                    failure_kind=FailureKind.INTERRUPTED,
                    started_at=started.started_at,
                    ended_at=now,
                    wall_time_s=max(0.0, (now - started.started_at).total_seconds()),
                    cost=CostEstimate(
                        billing_mode=adapter.billing_mode,
                        is_estimate=True,
                    ),
                    summary=(
                        "executor stopped before this attempt wrote a terminal record; "
                        "usage and cost are unavailable"
                    ),
                )
            )
    async def _cancel_all(self, running: Mapping[str, asyncio.Task[None]]) -> None:
        """Cancel in-flight attempts and wait for each to record its own end.

        Each attempt writes its `cancelled` record synchronously inside its own
        handler, so after this returns the log has no attempt that started
        without finishing — `resume` sees a clean picture rather than phantom
        orphans.

        The shield-and-retry is load-bearing. We are already inside a
        CancelledError, so a plain await re-raises before the children ever get
        scheduled and their records are never written. Shielding lets the
        gather survive; the first await consumes the pending cancellation and
        the second actually waits. Bounded so a wedged child cannot hang exit.
        """
        for task in running.values():
            task.cancel()
        if not running:
            return

        gathered = asyncio.gather(*running.values(), return_exceptions=True)
        for _ in range(10):
            if gathered.done():
                break
            try:
                await asyncio.shield(gathered)
            except asyncio.CancelledError:
                continue  # our own cancellation, re-delivered; the children live on
            except Exception:
                break
        if not gathered.done():
            gathered.cancel()
        with contextlib.suppress(BaseException):
            await asyncio.shield(gathered)

    def _tier_for(self, task: Task, attempt: int) -> tuple[Tier, str | None]:
        """Which tier this attempt runs at, and why if it moved.

        Retry escalation outranks a budget downshift. The task already failed at
        the cheaper tier; sending it back there to save money buys a second
        failure at the same price as the first.
        """
        escalated = task.retry.tier_for_attempt(task.tier, attempt)
        if escalated is not task.tier:
            return escalated, None
        if self.governor is not None:
            return self.governor.tier_for(task)
        return task.tier, None

    async def _attempt(self, task: Task, attempt: int) -> None:
        tier, downshift_reason = self._tier_for(task, attempt)

        if self.governor is not None:
            allowed, why = self.governor.should_dispatch(task, tier)
            if not allowed:
                self._deny(task, attempt, tier, why)
                return

        routing = self.router.resolve(
            task, attempt=attempt, tier=tier, downshift_reason=downshift_reason
        )
        adapter = self._adapter_for(routing)
        request = self._request(task, attempt, routing, dry_run=False)
        started_at = datetime.now(UTC)

        # Written and fsynced BEFORE dispatch: if the process dies mid-call, the
        # log must already show that money was committed.
        self.log.append(
            AttemptStarted(
                run_id=self.run_id,
                task_id=task.id,
                attempt=attempt,
                spec_hash=task.spec_hash(),
                plan_revision=self.plan.revision,
                routing=routing,
                pid=os.getpid(),
                started_at=started_at,
            )
        )
        self._report.dispatched += 1

        try:
            outcome = await adapter.dispatch(request)
        except asyncio.CancelledError:
            self._record(
                task,
                attempt,
                routing,
                DispatchOutcome(
                    status=AttemptStatus.CANCELLED,
                    failure_kind=FailureKind.CANCELLED,
                    stderr_tail="cancelled by operator",
                ),
                checks=[],
                request=request,
                started_at=started_at,
            )
            raise
        except Exception as exc:
            outcome = DispatchOutcome(
                status=AttemptStatus.FAILED,
                failure_kind=FailureKind.ADAPTER_ERROR,
                stderr_tail=f"{type(exc).__name__}: {exc}",
            )
            self._record(task, attempt, routing, outcome, [], request, started_at)
            return

        checks: list[CheckResult] = []
        if outcome.status is not AttemptStatus.FAILED:
            checks = await run_checks(
                task, request.workspace, runner=self.runner, env=self.config.resolved_env()
            )
        self._record(task, attempt, routing, outcome, checks, request, started_at)

    def _deny(self, task: Task, attempt: int, tier: Tier, why: str) -> None:
        """Record a dispatch the governor refused.

        A denial is written to the log as a terminal attempt, not skipped in
        silence: `status` must be able to say the plan stopped because the
        window ran out, and BUDGET_DENIED is non-retryable so the scheduler
        will not immediately try again.
        """
        now = datetime.now(UTC)
        routing = RoutingDecision(
            tier_requested=task.tier,
            tier_final=tier,
            model="<none>",
            adapter=Adapter.OPENROUTER,
            rationale=f"not dispatched: {why}"[:1_000],
        )
        self.log.append(
            AttemptFinished(
                run_id=self.run_id,
                task_id=task.id,
                attempt=attempt,
                spec_hash=task.spec_hash(),
                plan_revision=self.plan.revision,
                routing=routing,
                status=AttemptStatus.FAILED,
                failure_kind=FailureKind.BUDGET_DENIED,
                started_at=now,
                ended_at=now,
                wall_time_s=0.0,
                cost=CostEstimate(billing_mode=BillingMode.METERED),
                summary=f"budget governor refused this dispatch: {why}"[:700],
            )
        )
        self._report.failed += 1

    # -- record composition --------------------------------------------------

    def _record(
        self,
        task: Task,
        attempt: int,
        routing: RoutingDecision,
        outcome: DispatchOutcome,
        checks: Sequence[CheckResult],
        request: DispatchRequest,
        started_at: datetime,
    ) -> None:
        workspace = request.workspace
        produced, missing = workspace.collect_outputs(task.outputs)
        status, failure = self._resolve_status(outcome, produced, missing, checks)
        ended_at = datetime.now(UTC)
        # Fallback chain, most to least authoritative. stderr_tail is last but
        # must be included: when an adapter fails before the model ever runs,
        # it is the ONLY diagnostic that exists, and a record whose summary is
        # empty tells the orchestrator nothing about why the task died.
        summary, truncated = clip_summary(
            workspace.read_summary()
            or outcome.summary_text
            or outcome.response_text
            or outcome.stderr_tail
        )
        cost = self._cost(outcome, routing)

        record = AttemptFinished(
            run_id=self.run_id,
            task_id=task.id,
            attempt=attempt,
            spec_hash=task.spec_hash(),
            plan_revision=self.plan.revision,
            routing=routing,
            status=status,
            failure_kind=failure,
            started_at=started_at,
            ended_at=ended_at,
            wall_time_s=max(0.0, (ended_at - started_at).total_seconds()),
            usage=outcome.usage,
            cost=cost,
            artifacts=produced,
            missing_outputs=missing,
            checks=list(checks),
            summary=summary,
            summary_truncated=truncated,
            exit_code=outcome.exit_code,
            stdout_path=workspace.rel("stdout.log"),
            stderr_path=workspace.rel("stderr.log"),
        )
        self.log.append(record)
        if self.governor is not None:
            self.governor.settle_dispatch(task, cost)
        self._tally(record)

    @staticmethod
    def _resolve_status(
        outcome: DispatchOutcome,
        produced: Sequence[ProducedArtifact],
        missing: Sequence[str],
        checks: Sequence[CheckResult],
    ) -> tuple[AttemptStatus, FailureKind | None]:
        """Combine what the provider said with what actually landed on disk.

        The provider's own verdict is necessary but not sufficient: a model can
        exit 0 having produced nothing, and can be truncated having produced
        everything that matters.
        """
        if outcome.status in (AttemptStatus.FAILED, AttemptStatus.CANCELLED):
            return outcome.status, outcome.failure_kind or FailureKind.PROVIDER_ERROR

        named = [artifact for artifact in produced if artifact.name]
        if missing:
            if not named:
                return AttemptStatus.FAILED, outcome.failure_kind or FailureKind.ACCEPTANCE_FAILED
            return AttemptStatus.PARTIAL, outcome.failure_kind or FailureKind.ACCEPTANCE_FAILED

        if any(not check.passed for check in checks):
            # Everything promised exists but is wrong. Distinct from partial:
            # there is nothing to resume, so the default policy escalates.
            return AttemptStatus.FAILED, FailureKind.ACCEPTANCE_FAILED

        if outcome.status is AttemptStatus.PARTIAL:
            return AttemptStatus.PARTIAL, outcome.failure_kind or FailureKind.TRUNCATED
        return AttemptStatus.SUCCEEDED, None

    @staticmethod
    def _cost(outcome: DispatchOutcome, routing: RoutingDecision) -> CostEstimate:
        """Compose the two-axis cost record.

        For subscription dispatches ``amount_usd`` is the provider's *notional*
        cost — what the call would have cost if metered — not out-of-pocket
        spend. The governor filters by ``billing_mode`` before summing, so
        keeping the figure is strictly more informative than zeroing it.
        """
        return cost_from_outcome(outcome, routing)

    def _tally(self, record: AttemptFinished) -> None:
        match record.status:
            case AttemptStatus.SUCCEEDED:
                self._report.succeeded += 1
            case AttemptStatus.PARTIAL:
                self._report.partial += 1
            case AttemptStatus.CANCELLED:
                self._report.cancelled += 1
            case AttemptStatus.FAILED:
                self._report.failed += 1
        if record.cost.billing_mode is BillingMode.METERED:
            self._report.cost_usd += record.cost.amount_usd
        else:
            self._report.notional_usd += record.cost.amount_usd
        self._report.window_tokens += record.cost.window_tokens
        if record.cost.quota_pool == Adapter.CODEX.value:
            self._report.codex_tokens += record.usage.total_tokens
        for name, count in record.usage.server_tool_use.items():
            self._report.server_tool_use[name] = self._report.server_tool_use.get(name, 0) + count


__all__ = [
    "ConcurrentExecutionError",
    "DRY_RUN_SUMMARY",
    "Executor",
    "ExecutorConfig",
    "Router",
    "RunReport",
    "cost_from_outcome",
    "StaticRouter",
]
