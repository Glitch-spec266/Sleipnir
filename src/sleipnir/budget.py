"""Budget governor: what the 5-hour window has cost, and what the plan will.

Two things make this component subtle, and both were established by reading the
real records rather than assuming their shape (see DESIGN.md):

* ``input_tokens`` is a small fraction of real input. Most of it arrives as
  cache-creation tokens. Summing the obvious field under-counts by orders of
  magnitude.
* The same logical turn appears more than once — across ``iterations[]``, and
  again whenever a session is resumed or replayed. Blind summation over-counts.
  Records are deduplicated by ``requestId``.

The governor is the single authority on window accounting. It derives
consumption from ``~/.claude/projects`` — the actual meter — rather than from
Sleipnir's own result records, which only observe the dispatches Sleipnir
itself made and would miss everything else the user does in the same window.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sleipnir.config import SleipnirConfig
from sleipnir.projection import TaskState
from sleipnir.router import TierRouter, required_context_tokens
from sleipnir.schema import (
    CHARS_PER_TOKEN,
    DOWNSHIFT_LADDER,
    BudgetSnapshot,
    Plan,
    Task,
    TaskStatus,
    Tier,
    TokenUsage,
)

DEFAULT_PROJECTS_DIR = Path.home() / ".claude" / "projects"
WINDOW_HOURS = 5

#: Fallback output estimate per dispatch when nothing better is known. Only
#: used for projection, never for accounting actual spend.
ASSUMED_OUTPUT_TOKENS = 2_000

_MAX_WARNINGS = 10


@dataclass(slots=True)
class UsageRecord:
    """One deduplicated, priced-elsewhere assistant turn."""

    timestamp: datetime
    usage: TokenUsage
    model: str
    request_id: str
    is_sidechain: bool = False


@dataclass(slots=True)
class UsageScan:
    records: list[UsageRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    files_scanned: int = 0
    lines_seen: int = 0
    duplicates_dropped: int = 0


def window_tokens(usage: TokenUsage, *, cache_read_weight: float = 1.0) -> int:
    """Tokens charged against the 5-hour window.

    ``cache_read_weight`` exists because cache reads dominate observed
    consumption — 94% of it in the measured smoke run — while being priced at
    roughly a tenth of an input token. Weighting them 1:1 (the default)
    over-estimates consumption, which is the safe direction for a governor:
    it downshifts too eagerly rather than blowing the window. Lower it once you
    have established what your plan actually meters.
    """
    return int(
        usage.input_tokens
        + usage.output_tokens
        + usage.cache_write_5m_tokens
        + usage.cache_write_1h_tokens
        + usage.cache_read_tokens * cache_read_weight
    )


def parse_usage_line(payload: dict[str, Any]) -> UsageRecord | None:
    """Extract one usage record, or None if this line does not carry usage.

    Tolerant by construction: the format is a moving target owned by someone
    else, and a parser that raises on an unfamiliar line makes the budget
    unavailable exactly when a CLI upgrade lands.
    """
    if payload.get("type") != "assistant":
        return None
    message = payload.get("message")
    if not isinstance(message, dict):
        return None
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None

    stamp = payload.get("timestamp")
    if not isinstance(stamp, str):
        return None
    try:
        timestamp = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)

    details = usage.get("output_tokens_details") or {}
    creation = usage.get("cache_creation") or {}
    output_tokens = _int(usage.get("output_tokens"))

    # NOTE: `iterations` is deliberately ignored. It repeats the same counts
    # the top level already reports; summing both doubles every turn.
    parsed = TokenUsage(
        input_tokens=_int(usage.get("input_tokens")),
        output_tokens=output_tokens,
        thinking_tokens=min(_int(details.get("thinking_tokens")), output_tokens),
        cache_read_tokens=_int(usage.get("cache_read_input_tokens")),
        cache_write_5m_tokens=_int(creation.get("ephemeral_5m_input_tokens")),
        cache_write_1h_tokens=_int(creation.get("ephemeral_1h_input_tokens")),
    )

    # When the TTL breakdown is absent, fall back to the flat total so the
    # tokens are counted at all. Attributing them to the cheaper 5m bucket
    # would under-state cost; 1h is the conservative choice.
    flat_creation = _int(usage.get("cache_creation_input_tokens"))
    if flat_creation and not (parsed.cache_write_5m_tokens or parsed.cache_write_1h_tokens):
        parsed.cache_write_1h_tokens = flat_creation

    request_id = (
        payload.get("requestId")
        or payload.get("request_id")
        or message.get("id")
        or f"{stamp}:{payload.get('uuid')}"
    )
    return UsageRecord(
        timestamp=timestamp,
        usage=parsed,
        model=str(message.get("model") or "unknown"),
        request_id=str(request_id),
        is_sidechain=bool(payload.get("isSidechain")),
    )


def scan_usage(
    projects_dir: Path = DEFAULT_PROJECTS_DIR, *, since: datetime | None = None
) -> UsageScan:
    """Read every project transcript and return deduplicated usage records."""
    scan = UsageScan()
    if not projects_dir.exists():
        scan.warnings.append(f"{projects_dir} does not exist; window usage is unknown")
        return scan

    seen: set[str] = set()
    for path in sorted(projects_dir.rglob("*.jsonl")):
        scan.files_scanned += 1
        try:
            handle = path.open("r", encoding="utf-8", errors="replace")
        except OSError as exc:
            _warn(scan, f"{path.name}: unreadable ({exc})")
            continue
        with handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                scan.lines_seen += 1
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    _warn(scan, f"{path.name}: unparseable line")
                    continue
                if not isinstance(payload, dict):
                    continue
                record = parse_usage_line(payload)
                if record is None:
                    continue
                if since is not None and record.timestamp < since:
                    continue
                # Records recur across resumed sessions and replays; without
                # this the same turn is billed every time it appears.
                if record.request_id in seen:
                    scan.duplicates_dropped += 1
                    continue
                seen.add(record.request_id)
                scan.records.append(record)

    scan.records.sort(key=lambda record: record.timestamp)
    return scan


def _warn(scan: UsageScan, message: str) -> None:
    if len(scan.warnings) < _MAX_WARNINGS:
        scan.warnings.append(message)


def _int(value: Any) -> int:
    return int(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0


def current_window(
    timestamps: Sequence[datetime], now: datetime, *, hours: int = WINDOW_HOURS
) -> tuple[datetime, datetime]:
    """The active 5-hour block.

    Windows are anchored to first use and expire ``hours`` later — they are not
    a rolling lookback. A block therefore starts at the first turn that follows
    a gap of at least ``hours``. With no activity in range, the window is
    treated as starting now, which reports full headroom rather than inventing
    consumption.
    """
    span = timedelta(hours=hours)
    start: datetime | None = None
    for stamp in timestamps:
        if start is None or stamp >= start + span:
            start = stamp
    if start is None or now >= start + span:
        return now, now + span
    return start, start + span


@dataclass(slots=True)
class DownshiftDecision:
    task_id: str
    from_tier: Tier
    to_tier: Tier
    reason: str

    def render(self) -> str:
        return (
            f"  {self.task_id:<16} {self.from_tier.value} -> {self.to_tier.value}"
            f"   ({self.reason})"
        )


@dataclass(slots=True)
class Projection:
    window_tokens: int = 0
    metered_usd: float = 0.0
    per_task: dict[str, int] = field(default_factory=dict)


class BudgetGovernor:
    """Estimates consumption and downshifts eligible tasks to stay inside it."""

    def __init__(
        self,
        config: SleipnirConfig,
        router: TierRouter,
        *,
        projects_dir: Path = DEFAULT_PROJECTS_DIR,
        cache_read_weight: float = 1.0,
        now: datetime | None = None,
    ) -> None:
        self.config = config
        self.router = router
        self.projects_dir = projects_dir
        self.cache_read_weight = cache_read_weight
        self._now = now
        self.decisions: list[DownshiftDecision] = []
        self._plan_tiers: dict[str, Tier] = {}
        self._snapshot_cache: tuple[BudgetSnapshot, datetime] | None = None
        #: Tasks the router could not resolve. Their cost is omitted from the
        #: projection, so the projection is a floor — recorded here rather than
        #: silently folded in as zero.
        self.unroutable: set[str] = set()

    def now(self) -> datetime:
        return self._now or datetime.now(UTC)

    # -- observation ----------------------------------------------------------

    def snapshot(
        self,
        plan: Plan | None = None,
        states: dict[str, TaskState] | None = None,
        *,
        metered_spent_usd: float = 0.0,
    ) -> BudgetSnapshot:
        now = self.now()
        scan = scan_usage(self.projects_dir)
        start, end = current_window([r.timestamp for r in scan.records], now)
        in_window = [record for record in scan.records if start <= record.timestamp <= end]
        used = sum(
            window_tokens(record.usage, cache_read_weight=self.cache_read_weight)
            for record in in_window
        )

        projection = (
            self.project(plan, states) if plan is not None else Projection()
        )
        return BudgetSnapshot(
            window_start=start,
            window_end=end,
            observed_at=now,
            window_tokens_used=used,
            window_tokens_limit=self.config.window_tokens_limit,
            metered_spend_usd=metered_spent_usd,
            metered_budget_usd=self.config.metered_budget_usd,
            projected_plan_cost_usd=round(projection.metered_usd, 6),
            projected_plan_window_tokens=projection.window_tokens,
            parse_warnings=scan.warnings[:10],
        )

    # -- projection -----------------------------------------------------------

    def project(
        self,
        plan: Plan,
        states: dict[str, TaskState] | None = None,
        *,
        tiers: dict[str, Tier] | None = None,
    ) -> Projection:
        """Cost of everything still to run, at the tiers currently assigned."""
        projection = Projection()
        for task in plan.tasks:
            if states is not None and states[task.id].status in (
                TaskStatus.DONE,
                TaskStatus.STALE,
                TaskStatus.SKIPPED,
                TaskStatus.CANCELLED,
            ):
                continue
            tier = (tiers or self._plan_tiers).get(task.id, task.tier)
            tokens, usd = self.estimate_task(task, tier)
            projection.per_task[task.id] = tokens
            projection.window_tokens += tokens
            projection.metered_usd += usd
        return projection

    def estimate_task(self, task: Task, tier: Tier) -> tuple[int, float]:
        """(window tokens, metered dollars) one attempt of ``task`` would cost.

        Fixed dispatch overhead is included, and it dominates for small tasks:
        a `claude -p` spawn carries ~30k cache-creation tokens before it reads a
        word of the prompt, so a trivial task routed there is not cheap.
        """
        try:
            policy = self.config.policy(tier)
            decision = self.router.resolve(task, attempt=1, tier=tier)
        except Exception:
            # An unroutable tier is the router's problem to report, not a
            # reason to abandon the whole projection — but the projection is
            # then a floor, not an estimate, so say which task was skipped.
            self.unroutable.add(task.id)
            return 0, 0.0

        backend = self._backend_for(decision.model, decision)
        overhead = backend.dispatch_overhead_tokens if backend else 0
        input_tokens = required_context_tokens(task, policy) + overhead
        output_tokens = ASSUMED_OUTPUT_TOKENS

        info = self.router.catalog.get(decision.model)
        if backend is not None and backend.billing.value == "metered" and info is not None:
            usd = (
                input_tokens * info.input_per_mtok + output_tokens * info.output_per_mtok
            ) / 1_000_000 + info.request_cost_usd
            return 0, usd
        return input_tokens + output_tokens, 0.0

    def _backend_for(self, model: str, decision) -> Any:
        for backend in self.config.backends.values():
            if backend.adapter is decision.adapter:
                return backend
        return None

    # -- control --------------------------------------------------------------

    def plan_tiers(self, plan: Plan, states: dict[str, TaskState] | None = None) -> dict[str, Tier]:
        """Assign a tier to every remaining task, downshifting until it fits.

        Downshifts the most expensive eligible tasks first, one ladder rung at a
        time, recomputing after each. Tasks marked ``no_downshift`` are never
        touched — if the plan still does not fit, that is reported rather than
        quietly overridden.
        """
        self.decisions.clear()
        tiers = {task.id: task.tier for task in plan.tasks}
        self._plan_tiers = tiers

        snapshot = self.snapshot(plan, states)
        budget = self._allowance(snapshot)
        if budget is None:
            return tiers

        for _ in range(len(plan.tasks) * len(DOWNSHIFT_LADDER)):
            projection = self.project(plan, states, tiers=tiers)
            if projection.window_tokens <= budget:
                break
            victim = self._next_victim(plan, states, tiers, projection)
            if victim is None:
                break
            task, target = victim
            reason = (
                f"projected {projection.window_tokens:,} window tokens exceeds the "
                f"{budget:,} allowance"
            )
            self.decisions.append(
                DownshiftDecision(task.id, tiers[task.id], target, reason)
            )
            tiers[task.id] = target

        self._plan_tiers = tiers
        return tiers

    def _allowance(self, snapshot: BudgetSnapshot) -> int | None:
        headroom = snapshot.window_headroom_tokens
        if headroom is None:
            return None
        return int(headroom * (1.0 - self.config.reserve_fraction))

    def _next_victim(
        self,
        plan: Plan,
        states: dict[str, TaskState] | None,
        tiers: dict[str, Tier],
        projection: Projection,
    ) -> tuple[Task, Tier] | None:
        """The costliest task that can still move one rung down the ladder."""
        best: tuple[int, Task, Tier] | None = None
        for task in plan.tasks:
            if task.no_downshift or task.id not in projection.per_task:
                continue
            current = tiers[task.id]
            if current not in DOWNSHIFT_LADDER:
                continue  # longctx: moving it is a correctness failure, not a saving
            index = DOWNSHIFT_LADDER.index(current)
            if index + 1 >= len(DOWNSHIFT_LADDER):
                continue
            cost = projection.per_task[task.id]
            if best is None or cost > best[0]:
                best = (cost, task, DOWNSHIFT_LADDER[index + 1])
        return (best[1], best[2]) if best else None

    def should_dispatch(self, task: Task) -> tuple[bool, str]:
        """Refuse only when the window is provably gone.

        Denial is a blunt instrument — the plan stops and BUDGET_DENIED is
        non-retryable — so it fires only on a *known* limit with no headroom
        left. An unknown limit never denies: the governor must not stop a run
        on a number it could not verify.
        """
        snapshot = self._recent_snapshot()
        headroom = snapshot.window_headroom_tokens
        if headroom is not None and headroom <= 0:
            return False, (
                f"the 5-hour window is exhausted ({snapshot.window_tokens_used:,} of "
                f"{snapshot.window_tokens_limit:,} tokens used; it resets at "
                f"{snapshot.window_end.isoformat(timespec='minutes')})"
            )
        if snapshot.metered_budget_usd is not None and (
            snapshot.metered_spend_usd >= snapshot.metered_budget_usd
        ):
            return False, (
                f"metered budget of ${snapshot.metered_budget_usd:.2f} is spent "
                f"(${snapshot.metered_spend_usd:.2f})"
            )
        return True, ""

    def _recent_snapshot(self, max_age_s: float = 30.0) -> BudgetSnapshot:
        """Cached briefly: should_dispatch runs per task, and a full rescan of
        every transcript on every dispatch would cost more than it saves."""
        now = self.now()
        if self._snapshot_cache is not None:
            cached, taken = self._snapshot_cache
            if (now - taken).total_seconds() < max_age_s:
                return cached
        snapshot = self.snapshot()
        self._snapshot_cache = (snapshot, now)
        return snapshot

    def tier_for(self, task: Task) -> tuple[Tier, str | None]:
        """The tier to dispatch ``task`` at, plus why if it moved."""
        tier = self._plan_tiers.get(task.id, task.tier)
        if tier is task.tier:
            return tier, None
        for decision in self.decisions:
            if decision.task_id == task.id:
                return tier, decision.reason
        return tier, "budget governor reassigned this task's tier"


def render_decisions(decisions: Iterable[DownshiftDecision]) -> str:
    decisions = list(decisions)
    if not decisions:
        return "  (no downshifts)"
    return "\n".join(decision.render() for decision in decisions)


__all__ = [
    "ASSUMED_OUTPUT_TOKENS",
    "DEFAULT_PROJECTS_DIR",
    "WINDOW_HOURS",
    "BudgetGovernor",
    "DownshiftDecision",
    "Projection",
    "UsageRecord",
    "UsageScan",
    "current_window",
    "parse_usage_line",
    "render_decisions",
    "scan_usage",
    "window_tokens",
]
