"""Parser for Claude Code's own usage records.

This module reads ``~/.claude/projects/*.jsonl`` — transcripts written by a tool
we do not control, in a shape that has already changed once. It is therefore
written to be lenient about structure and loud about surprises: an unrecognised
field produces a warning that reaches ``BudgetSnapshot.parse_warnings``, never a
silently dropped number.

Every rule below comes from measuring 2,760 real usage records on 2026-08-18,
not from the shape the records ought to have:

* **Sum all four input channels.** ``input_tokens`` totalled 35,198 against
  513,304,884 tokens of real input. Summing it alone under-counts by ~14,600x.
* **Never also sum ``iterations[]``.** Present on 2,751 of 2,760 records, always
  a single entry repeating the top-level counts. Adding both doubles every turn.
* **Deduplicate on ``requestId``.** 1,438 of 2,754 ids were repeats — 52%.
  Records recur across resumed sessions, so blind summing roughly doubles the
  budget.
* **Keep records that have no ``requestId``.** Three did. Dropping them
  under-counts; collapsing them together under-counts worse.
* **Skip ``<synthetic>`` records.** Nine were CLI-generated messages rather than
  API calls. Costing them invents spend that never happened.
* **Cache reads were 96.4% of all input.** Whether the 5-hour window meters them
  at full weight is still unresolved, so ``window_tokens`` defaults to 1:1 —
  over-estimating, which downshifts too eagerly instead of overrunning. A
  price-weighted sum of the same corpus is 5.96x smaller, so this is not a
  rounding decision.

Fields the Phase 1 schema had no home for, captured here because they cost real
money: ``server_tool_use`` (web search and fetch are billed per request, listed
at $0.01 in the model catalogue) and ``speed`` (``-fast`` model variants are
priced 2-6x their standard counterparts).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from sleipnir.schema import TokenUsage

#: Model name the CLI uses for messages it generated itself. Never an API call.
SYNTHETIC_MODEL = "<synthetic>"

#: Usage keys this parser understands. Anything else is surfaced as a warning,
#: because a new billing channel that we silently ignore is a wrong budget.
KNOWN_USAGE_KEYS = frozenset(
    {
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
        "cache_creation",
        "output_tokens_details",
        "server_tool_use",
        "service_tier",
        "inference_geo",
        "iterations",
        "speed",
    }
)

#: Warnings are capped so a systematically changed shape cannot produce one
#: warning per record across thousands of them.
MAX_WARNINGS = 25

#: Each warning is also capped in length. Warning text quotes field names taken
#: verbatim from a file we do not control, and only the *count* of warnings ever
#: reaches the manifest — but bounding it at the source keeps an absurd
#: transcript from producing an absurd string anywhere downstream.
MAX_WARNING_CHARS = 300


@dataclass(frozen=True, slots=True)
class UsageRecord:
    """One deduplicated API turn."""

    request_id: str | None
    timestamp: datetime | None
    model: str
    usage: TokenUsage
    is_sidechain: bool = False
    session_id: str | None = None
    web_search_requests: int = 0
    web_fetch_requests: int = 0
    speed: str = "standard"
    service_tier: str = "standard"

    @property
    def total_input_tokens(self) -> int:
        """All four input channels. The single most-missed sum in this format."""
        u = self.usage
        return (
            u.input_tokens
            + u.cache_read_tokens
            + u.cache_write_1h_tokens
            + u.cache_write_5m_tokens
        )


@dataclass(slots=True)
class UsageScan:
    """Everything a scan found, plus everything it could not make sense of."""

    records: list[UsageRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    duplicates_dropped: int = 0
    skipped_synthetic: int = 0
    files_scanned: int = 0
    lines_scanned: int = 0

    def totals(self) -> TokenUsage:
        """Channel-wise sum over every retained record."""
        return TokenUsage(
            input_tokens=sum(r.usage.input_tokens for r in self.records),
            output_tokens=sum(r.usage.output_tokens for r in self.records),
            thinking_tokens=sum(r.usage.thinking_tokens for r in self.records),
            cache_read_tokens=sum(r.usage.cache_read_tokens for r in self.records),
            cache_write_5m_tokens=sum(
                r.usage.cache_write_5m_tokens for r in self.records
            ),
            cache_write_1h_tokens=sum(
                r.usage.cache_write_1h_tokens for r in self.records
            ),
        )

    def window_tokens(
        self,
        *,
        cache_read_weight: float = 1.0,
        cache_write_weight: float = 1.0,
        output_weight: float = 1.0,
    ) -> int:
        """Tokens charged against the 5-hour window.

        Defaults are 1:1 across every channel. That over-estimates consumption —
        cache reads are priced at roughly a tenth of input — but over-estimating
        makes the governor downshift too eagerly rather than blow the window,
        which is the safe direction while the true metering is unknown.

        Do not change the defaults on reasoning alone. On the measured corpus a
        1:1 sum is 516,136,404 and a price-weighted sum is 86,580,933; guessing
        between them is a 5.96x error on the resource that actually binds.
        """
        t = self.totals()
        return int(
            t.input_tokens
            + t.cache_read_tokens * cache_read_weight
            + (t.cache_write_1h_tokens + t.cache_write_5m_tokens) * cache_write_weight
            + t.output_tokens * output_weight
        )

    def web_tool_requests(self) -> tuple[int, int]:
        """(web_search, web_fetch). Billed per request, not per token."""
        return (
            sum(r.web_search_requests for r in self.records),
            sum(r.web_fetch_requests for r in self.records),
        )


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _parse_timestamp(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_usage_line(
    obj: Any, *, warn: Any = None
) -> UsageRecord | None:
    """Turn one decoded transcript line into a record, or ``None`` to skip it.

    ``None`` covers three very different cases, all of them normal: the line has
    no usage block (most lines — 7,973 lines held only 2,760 usage records), the
    model is ``<synthetic>``, or the numbers failed schema validation. Only the
    last produces a warning.
    """
    if not isinstance(obj, Mapping):
        return None
    message = obj.get("message")
    if not isinstance(message, Mapping):
        return None
    raw = message.get("usage")
    if not isinstance(raw, Mapping):
        return None

    model = message.get("model")
    if not isinstance(model, str):
        model = "unknown"
    if model == SYNTHETIC_MODEL:
        return None

    if warn is not None:
        for key in raw:
            if key not in KNOWN_USAGE_KEYS:
                warn(f"unrecognised usage field {key!r} on model {model!r}")

    cache_creation = raw.get("cache_creation")
    if isinstance(cache_creation, Mapping):
        write_1h = _int(cache_creation.get("ephemeral_1h_input_tokens"))
        write_5m = _int(cache_creation.get("ephemeral_5m_input_tokens"))
    else:
        # Older shape: one undifferentiated cache-creation number. Attribute it
        # to the 1h bucket, which is the more expensive of the two, so an
        # unknown split over-estimates rather than under-estimates cost.
        write_1h = _int(raw.get("cache_creation_input_tokens"))
        write_5m = 0

    details = raw.get("output_tokens_details")
    thinking = (
        _int(details.get("thinking_tokens")) if isinstance(details, Mapping) else 0
    )

    tools = raw.get("server_tool_use")
    tools = tools if isinstance(tools, Mapping) else {}

    try:
        usage = TokenUsage(
            input_tokens=_int(raw.get("input_tokens")),
            output_tokens=_int(raw.get("output_tokens")),
            thinking_tokens=thinking,
            cache_read_tokens=_int(raw.get("cache_read_input_tokens")),
            cache_write_5m_tokens=write_5m,
            cache_write_1h_tokens=write_1h,
        )
    except ValueError as exc:
        if warn is not None:
            warn(f"usage record rejected by schema on model {model!r}: {exc}")
        return None

    request_id = obj.get("requestId")
    session_id = obj.get("sessionId") or obj.get("session_id")
    speed = raw.get("speed")
    tier = raw.get("service_tier")

    return UsageRecord(
        request_id=request_id if isinstance(request_id, str) else None,
        timestamp=_parse_timestamp(obj.get("timestamp")),
        model=model,
        usage=usage,
        is_sidechain=obj.get("isSidechain") is True,
        session_id=session_id if isinstance(session_id, str) else None,
        web_search_requests=_int(tools.get("web_search_requests")),
        web_fetch_requests=_int(tools.get("web_fetch_requests")),
        speed=speed if isinstance(speed, str) else "standard",
        service_tier=tier if isinstance(tier, str) else "standard",
    )


def scan_transcripts(
    paths: Iterable[Path],
    *,
    since: datetime | None = None,
) -> UsageScan:
    """Scan several transcripts as one corpus.

    Deduplication spans files on purpose: a resumed session writes the same turn
    into a second transcript, so per-file dedup would still double-count it.
    """
    scan = UsageScan()
    seen: set[str] = set()
    for path in paths:
        _scan_into(Path(path), scan, seen, since)
    return scan


def scan_transcript(path: Path, *, since: datetime | None = None) -> UsageScan:
    """Scan a single transcript."""
    return scan_transcripts([path], since=since)


def default_transcript_paths(root: Path | None = None) -> list[Path]:
    """Every transcript under ``~/.claude/projects``. Missing root is not fatal."""
    base = Path(root) if root is not None else Path.home() / ".claude" / "projects"
    if not base.is_dir():
        return []
    return sorted(base.glob("*/*.jsonl"))


def _scan_into(
    path: Path,
    scan: UsageScan,
    seen: set[str],
    since: datetime | None,
) -> None:
    def warn(message: str) -> None:
        if len(scan.warnings) < MAX_WARNINGS:
            scan.warnings.append(f"{path.name}: {message}"[:MAX_WARNING_CHARS])

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        warn(f"unreadable ({exc.__class__.__name__})")
        return

    scan.files_scanned += 1
    lines = text.split("\n")
    last_index = len(lines) - 1
    while last_index >= 0 and not lines[last_index].strip():
        last_index -= 1

    for index, line in enumerate(lines):
        if not line.strip():
            continue
        scan.lines_scanned += 1
        try:
            obj = json.loads(line)
        except ValueError:
            # A torn *final* line is an ordinary consequence of a crash
            # mid-write. A torn line anywhere else means real damage — but
            # unlike results.jsonl these transcripts are not ours to trust or
            # repair, so both are reported and neither aborts the scan.
            if index == last_index:
                warn("discarded unparseable final line (crash mid-write)")
            else:
                warn(f"unparseable line {index + 1} (not the final line)")
            continue

        message = obj.get("message") if isinstance(obj, Mapping) else None
        if (
            isinstance(message, Mapping)
            and isinstance(message.get("usage"), Mapping)
            and message.get("model") == SYNTHETIC_MODEL
        ):
            scan.skipped_synthetic += 1
            continue

        record = parse_usage_line(obj, warn=warn)
        if record is None:
            continue

        if since is not None and record.timestamp is not None:
            if record.timestamp < since:
                continue

        if record.request_id is not None:
            if record.request_id in seen:
                scan.duplicates_dropped += 1
                continue
            seen.add(record.request_id)

        scan.records.append(record)


def scan_default(
    *, since: datetime | None = None, root: Path | None = None
) -> UsageScan:
    """Convenience: scan every transcript Claude Code has written."""
    paths: Sequence[Path] = default_transcript_paths(root)
    return scan_transcripts(paths, since=since)
