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
    clip_summary,
)
from sleipnir.checks import assert_checks_supported, run_checks
from sleipnir.context import resolve_inputs
from sleipnir.process import ProcessRunner
from sleipnir.projection import TaskState, fold_results
from sleipnir.runlog import ResultLog
from sleipnir.schema import (
    SATISFIED_STATUSES,
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


class Router(Protocol):
    """Tier -> concrete model. Implemented for real in Phase 3."""

    def resolve(self, task: Task, *, attempt: int, tier: Tier) -> RoutingDecision: ...


@dataclass(slots=True)
class StaticRouter:
    """Phase 2 placeholder: a fixed tier -> (adapter, model) table from config.

    Phase 3 replaces this with live OpenRouter data and downshift logic. It
    exists so the executor can be finished and tested now without hardcoding
    model names anywhere in the executor itself.
    """

    assignments: Mapping[Tier, tuple[Adapter, str]]

    def resolve(self, task: Task, *, attempt: int, tier: Tier) -> RoutingDecision:
        if tier not in self.assignments:
            raise KeyError(f"no model configured for tier {tier.value!r}")
        adapter, model = self.assignments[tier]
        return RoutingDecision(
            tier_requested=task.tier,
            tier_final=tier,
            model=model,
            adapter=adapter,
            escalated=tier is not task.tier,
            rationale=f"static assignment for tier {tier.value!r} (attempt {attempt})",
        )


@dataclass(slots=True)
class ExecutorConfig:
    run_root: Path
    concurrency: int = 3
    grace_s: float = 5.0
    env: Mapping[str, str] | None = None
    dry_run: bool = False

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
    previews: list[DispatchPreview] = field(default_factory=list)
    final_states: dict[str, TaskState] = field(default_factory=dict)

    def render(self) -> str:
        return (
            f"dispatched={self.dispatched} ok={self.succeeded} partial={self.partial} "
            f"failed={self.failed} cancelled={self.cancelled} "
            f"metered=${self.cost_usd:.4f} notional=${self.notional_usd:.4f} "
            f"window_tokens={self.window_tokens}"
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
    ) -> None:
        assert_checks_supported(plan.tasks)
        self.plan = plan
        self.adapters = adapters
        self.router = router
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

    # -- state ---------------------------------------------------------------

    def _states(self) -> dict[str, TaskState]:
        return fold_results(self.plan, self.log.read())

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
        ready = [
            task
            for task in self.plan.tasks
            if task.id not in skip
            and states[task.id].status is TaskStatus.READY
            and all(states[dep].status in SATISFIED_STATUSES for dep in task.depends_on)
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
            if states[task_id].status in (TaskStatus.DONE, TaskStatus.STALE):
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
            workspace.prepare()
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

    async def _attempt(self, task: Task, attempt: int) -> None:
        routing = self.router.resolve(task, attempt=attempt, tier=task.retry.tier_for_attempt(task.tier, attempt))
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
        cost = self._cost(outcome)

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
    def _cost(outcome: DispatchOutcome) -> CostEstimate:
        """Compose the two-axis cost record.

        For subscription dispatches ``amount_usd`` is the provider's *notional*
        cost — what the call would have cost if metered — not out-of-pocket
        spend. The governor filters by ``billing_mode`` before summing, so
        keeping the figure is strictly more informative than zeroing it.
        """
        metered = outcome.billing_mode is BillingMode.METERED
        return CostEstimate(
            billing_mode=outcome.billing_mode,
            amount_usd=float(outcome.reported_cost_usd or 0.0),
            window_tokens=0 if metered else outcome.usage.total_tokens,
            pricing=None,
            is_estimate=outcome.reported_cost_usd is None,
        )

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


__all__ = [
    "DRY_RUN_SUMMARY",
    "Executor",
    "ExecutorConfig",
    "Router",
    "RunReport",
    "StaticRouter",
]
