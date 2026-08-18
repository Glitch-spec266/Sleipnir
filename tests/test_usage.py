"""Phase 4 usage-record parser tests.

Every assertion here is grounded in a measurement over the 2,760 real usage
records in ``~/.claude/projects/*.jsonl`` taken on 2026-08-18, not in what the
record shape *ought* to be. The numbers that drove each test are named in the
docstrings, because the whole point of this parser is that the obvious
implementation is confidently and silently wrong.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from sleipnir.usage import (
    UsageScan,
    parse_usage_line,
    scan_transcript,
    scan_transcripts,
)

T0 = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)


def record(
    *,
    request_id: str | None = "req_1",
    model: str = "claude-opus-5",
    input_tokens: int = 2,
    cache_creation_1h: int = 9_245,
    cache_creation_5m: int = 0,
    cache_read: int = 12_965,
    output: int = 144,
    thinking: int | None = None,
    sidechain: bool = False,
    web_search: int = 0,
    web_fetch: int = 0,
    speed: str = "standard",
    with_iterations: bool = True,
    ts: str = "2026-08-18T12:00:00.000Z",
    **extra,
) -> dict:
    usage: dict = {
        "input_tokens": input_tokens,
        "cache_creation_input_tokens": cache_creation_1h + cache_creation_5m,
        "cache_read_input_tokens": cache_read,
        "output_tokens": output,
        "server_tool_use": {
            "web_search_requests": web_search,
            "web_fetch_requests": web_fetch,
        },
        "service_tier": "standard",
        "cache_creation": {
            "ephemeral_1h_input_tokens": cache_creation_1h,
            "ephemeral_5m_input_tokens": cache_creation_5m,
        },
        "inference_geo": "not_available",
        "speed": speed,
    }
    if thinking is not None:
        usage["output_tokens_details"] = {"thinking_tokens": thinking}
    if with_iterations:
        # Observed on 2,751 of 2,760 records: exactly one entry, repeating the
        # top-level counts. Summing both double-counts every single turn.
        usage["iterations"] = [
            {
                "input_tokens": input_tokens,
                "output_tokens": output,
                "cache_read_input_tokens": cache_read,
                "cache_creation_input_tokens": cache_creation_1h + cache_creation_5m,
                "type": "message",
            }
        ]
    out = {
        "type": "assistant",
        "isSidechain": sidechain,
        "timestamp": ts,
        "message": {"model": model, "usage": usage},
    }
    if request_id is not None:
        out["requestId"] = request_id
    out.update(extra)
    return out


def write(tmp_path, name, records):
    p = tmp_path / name
    p.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n",
        encoding="utf-8",
    )
    return p


# ---------------------------------------------------------------------------
# The four input channels
# ---------------------------------------------------------------------------


def test_all_four_input_channels_are_summed():
    """Measured: input_tokens totalled 35,198 against 513,304,884 raw input.

    Summing input_tokens alone under-counts by roughly 14,600x in the real
    corpus. It is the single most dangerous shortcut in this parser.
    """
    rec = parse_usage_line(record())
    assert rec is not None
    u = rec.usage
    assert u.input_tokens == 2
    assert u.cache_write_1h_tokens == 9_245
    assert u.cache_write_5m_tokens == 0
    assert u.cache_read_tokens == 12_965
    assert rec.total_input_tokens == 2 + 9_245 + 12_965


def test_cache_write_ttls_stay_separate():
    """1h and 5m writes are priced differently; one combined field cannot cost."""
    rec = parse_usage_line(record(cache_creation_1h=1_000, cache_creation_5m=250))
    assert rec.usage.cache_write_1h_tokens == 1_000
    assert rec.usage.cache_write_5m_tokens == 250


def test_iterations_are_never_added_to_the_totals():
    """Measured: 0 of 2,751 records had iterations disagreeing with the top level.

    They repeat the same counts, so summing both exactly doubles every turn.
    """
    with_iters = parse_usage_line(record(with_iterations=True))
    without = parse_usage_line(record(with_iterations=False))
    assert with_iters.total_input_tokens == without.total_input_tokens
    assert with_iters.usage.output_tokens == without.usage.output_tokens


def test_thinking_tokens_are_a_subset_of_output_not_an_addition():
    rec = parse_usage_line(record(output=144, thinking=100))
    assert rec.usage.output_tokens == 144
    assert rec.usage.thinking_tokens == 100


def test_thinking_exceeding_output_is_rejected_not_clamped():
    """A record this malformed is a shape change, and must be surfaced."""
    rec = parse_usage_line(record(output=10, thinking=999))
    assert rec is None


# ---------------------------------------------------------------------------
# Deduplication — the biggest single correction
# ---------------------------------------------------------------------------


def test_duplicate_request_ids_are_counted_once(tmp_path):
    """Measured: 1,438 duplicate requestIds against 1,316 unique — 52%.

    Records recur across resumed sessions. Blind summing roughly doubles the
    whole budget.
    """
    p = write(
        tmp_path,
        "a.jsonl",
        [record(request_id="req_a"), record(request_id="req_a"), record(request_id="req_b")],
    )
    scan = scan_transcript(p)
    assert len(scan.records) == 2
    assert scan.duplicates_dropped == 1


def test_duplicates_are_deduped_across_files(tmp_path):
    """A resumed session writes the same turn into a second transcript."""
    write(tmp_path, "a.jsonl", [record(request_id="req_x")])
    write(tmp_path, "b.jsonl", [record(request_id="req_x")])
    scan = scan_transcripts(sorted(tmp_path.glob("*.jsonl")))
    assert len(scan.records) == 1
    assert scan.duplicates_dropped == 1


def test_records_without_a_request_id_are_kept_not_dropped(tmp_path):
    """Measured: 3 of 2,760 records carry no requestId.

    Dropping them under-counts; collapsing them together under-counts worse,
    because they are distinct turns that merely lack an id.
    """
    p = write(
        tmp_path,
        "a.jsonl",
        [record(request_id=None), record(request_id=None)],
    )
    scan = scan_transcript(p)
    assert len(scan.records) == 2
    assert scan.duplicates_dropped == 0


# ---------------------------------------------------------------------------
# Records that must not be costed
# ---------------------------------------------------------------------------


def test_synthetic_records_are_skipped(tmp_path):
    """Measured: 9 records report model '<synthetic>'.

    These are CLI-generated messages, not API calls. Costing them invents spend
    that never happened.
    """
    p = write(tmp_path, "a.jsonl", [record(model="<synthetic>"), record(request_id="r2")])
    scan = scan_transcript(p)
    assert len(scan.records) == 1
    assert scan.skipped_synthetic == 1


def test_lines_without_usage_are_ignored_silently(tmp_path):
    """Measured: 7,973 lines carried only 2,760 usage records.

    Most lines are user turns and tool results. They are not warnings.
    """
    p = tmp_path / "a.jsonl"
    p.write_text(
        json.dumps({"type": "user", "message": {"content": "hi"}})
        + "\n"
        + json.dumps(record())
        + "\n",
        encoding="utf-8",
    )
    scan = scan_transcript(p)
    assert len(scan.records) == 1
    assert scan.warnings == []


def test_sidechain_turns_are_recorded_and_attributable(tmp_path):
    """Subagent turns spend real budget and must be countable separately."""
    p = write(
        tmp_path,
        "a.jsonl",
        [record(request_id="r1", sidechain=True), record(request_id="r2")],
    )
    scan = scan_transcript(p)
    assert sum(1 for r in scan.records if r.is_sidechain) == 1
    assert scan.totals().output_tokens == 288


# ---------------------------------------------------------------------------
# Fields DESIGN.md's schema had no home for
# ---------------------------------------------------------------------------


def test_server_tool_use_is_captured_because_it_is_billed_separately():
    """Web search is priced per request, not per token (catalogue: $0.01)."""
    rec = parse_usage_line(record(web_search=3, web_fetch=2))
    assert rec.web_search_requests == 3
    assert rec.web_fetch_requests == 2


def test_speed_is_captured_because_fast_variants_are_priced_higher():
    """`-fast` models cost 2-6x: opus-5 is $5/Mtok, opus-5-fast is $10/Mtok."""
    assert parse_usage_line(record(speed="fast")).speed == "fast"
    assert parse_usage_line(record()).speed == "standard"


def test_unknown_usage_keys_are_surfaced_not_swallowed(tmp_path):
    """A silently wrong budget is worse than a loud unknown."""
    r = record()
    r["message"]["usage"]["some_new_billing_channel"] = 12_345
    p = write(tmp_path, "a.jsonl", [r])
    scan = scan_transcript(p)
    assert len(scan.records) == 1
    assert any("some_new_billing_channel" in w for w in scan.warnings)


# ---------------------------------------------------------------------------
# Corruption tolerance, matching the runlog's contract
# ---------------------------------------------------------------------------


def test_a_torn_final_line_is_tolerated(tmp_path):
    p = tmp_path / "a.jsonl"
    p.write_text(
        json.dumps(record(request_id="r1")) + "\n" + '{"message":{"usa',
        encoding="utf-8",
    )
    scan = scan_transcript(p)
    assert len(scan.records) == 1
    assert any("final line" in w.lower() for w in scan.warnings)


def test_a_torn_middle_line_is_reported_but_does_not_abort(tmp_path):
    """Unlike results.jsonl, transcripts are not ours; be lenient, be loud."""
    p = tmp_path / "a.jsonl"
    p.write_text(
        json.dumps(record(request_id="r1"))
        + "\n"
        + '{"broken\n'
        + json.dumps(record(request_id="r2"))
        + "\n",
        encoding="utf-8",
    )
    scan = scan_transcript(p)
    assert len(scan.records) == 2
    assert any("line 2" in w for w in scan.warnings)


def test_an_unreadable_file_is_a_warning_not_a_crash(tmp_path):
    scan = scan_transcripts([tmp_path / "does-not-exist.jsonl"])
    assert scan.records == []
    assert len(scan.warnings) == 1


# ---------------------------------------------------------------------------
# Totals and windowing
# ---------------------------------------------------------------------------


def test_totals_sum_every_channel_across_records(tmp_path):
    p = write(
        tmp_path,
        "a.jsonl",
        [
            record(request_id="r1", input_tokens=10, cache_read=100, output=5),
            record(request_id="r2", input_tokens=20, cache_read=200, output=7),
        ],
    )
    t = scan_transcript(p).totals()
    assert t.input_tokens == 30
    assert t.cache_read_tokens == 300
    assert t.output_tokens == 12


def test_since_filter_excludes_older_records(tmp_path):
    p = write(
        tmp_path,
        "a.jsonl",
        [
            record(request_id="old", ts="2026-08-18T06:00:00.000Z"),
            record(request_id="new", ts="2026-08-18T11:30:00.000Z"),
        ],
    )
    scan = scan_transcript(p, since=datetime(2026, 8, 18, 9, 0, tzinfo=UTC))
    assert [r.request_id for r in scan.records] == ["new"]


def test_window_tokens_defaults_to_one_to_one(tmp_path):
    """1:1 over-estimates, which downshifts too eagerly rather than overrunning.

    Measured on the real corpus: 1:1 gives 516,136,404 and a price-weighted sum
    gives 86,580,933 — a 5.96x spread. Getting this wrong is a 6x error on the
    only resource that actually constrains a subscription run.
    """
    p = write(tmp_path, "a.jsonl", [record(input_tokens=1, cache_creation_1h=10, cache_read=100, output=1000, cache_creation_5m=0)])
    scan = scan_transcript(p)
    assert scan.window_tokens() == 1 + 10 + 100 + 1000


def test_window_tokens_accepts_an_explicit_weighting(tmp_path):
    p = write(tmp_path, "a.jsonl", [record(input_tokens=0, cache_creation_1h=0, cache_creation_5m=0, cache_read=1000, output=0)])
    scan = scan_transcript(p)
    assert scan.window_tokens(cache_read_weight=0.1) == 100


def test_an_empty_scan_reports_zero_rather_than_failing():
    scan = UsageScan(records=[], warnings=[])
    assert scan.window_tokens() == 0
    assert scan.totals().output_tokens == 0


# ---------------------------------------------------------------------------
# Boundary hygiene — transcripts are not ours
# ---------------------------------------------------------------------------


def test_warning_text_is_length_capped(tmp_path):
    """Warning text quotes field names verbatim from a file we do not control."""
    r = record()
    r["message"]["usage"]["x" * 5000] = 1
    p = write(tmp_path, "a.jsonl", [r])
    scan = scan_transcript(p)
    assert scan.warnings
    assert all(len(w) <= 300 for w in scan.warnings)


def test_the_parser_never_reads_message_content(tmp_path):
    """Transcripts hold prompts and source code. Only counters are extracted.

    Nothing this parser returns can carry conversation text, which is what keeps
    a budget scan from becoming a data-exfiltration path.
    """
    r = record()
    r["message"]["content"] = [{"type": "text", "text": "SECRET-CANARY-VALUE"}]
    p = write(tmp_path, "a.jsonl", [r])
    scan = scan_transcript(p)

    rec = scan.records[0]
    assert "SECRET-CANARY-VALUE" not in repr(rec)
    assert "SECRET-CANARY-VALUE" not in repr(scan.warnings)
    assert not hasattr(rec, "content")
