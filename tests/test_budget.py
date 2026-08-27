"""Budget governor: usage parsing, window detection, projection, downshift.

The fixtures below reproduce the *real* record shape observed in
~/.claude/projects (CLI 2.1.234), including the two traps that made the naive
parser wrong by four orders of magnitude.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from test_router import CONFIG_TOML, catalog, model
from test_schema import make_task

from sleipnir.budget import (
    BudgetGovernor,
    current_window,
    parse_usage_line,
    scan_usage,
    window_tokens,
)
from sleipnir.config import SleipnirConfig
from sleipnir.router import TierRouter
from sleipnir.schema import Adapter, Plan, Tier, TokenUsage

NOW = datetime(2026, 8, 17, 23, 0, tzinfo=UTC)


def config(**overrides) -> SleipnirConfig:
    import tomllib
    raw = tomllib.loads(CONFIG_TOML)
    raw.update(overrides)
    return SleipnirConfig.from_dict(raw, source="<test>")


def assistant_line(*, ts, request_id="req-1", input_tokens=2, cache_creation=47052,
                   cache_read=0, output=901, thinking=611, sidechain=False, model_id="m"):
    """Mirrors the verified on-disk shape."""
    return {
        "type": "assistant",
        "timestamp": ts.isoformat().replace("+00:00", "Z"),
        "requestId": request_id,
        "isSidechain": sidechain,
        "uuid": request_id,
        "message": {
            "id": f"msg_{request_id}",
            "model": model_id,
            "usage": {
                "input_tokens": input_tokens,
                "cache_creation_input_tokens": cache_creation,
                "cache_read_input_tokens": cache_read,
                "output_tokens": output,
                "output_tokens_details": {"thinking_tokens": thinking},
                "cache_creation": {
                    "ephemeral_1h_input_tokens": cache_creation,
                    "ephemeral_5m_input_tokens": 0,
                },
                # The double-count trap: the same numbers again.
                "iterations": [
                    {"input_tokens": input_tokens, "output_tokens": output,
                     "cache_creation_input_tokens": cache_creation},
                ],
            },
        },
    }


def write_transcript(tmp_path: Path, lines, name="project/session.jsonl") -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")
    return tmp_path


# -- parsing ---------------------------------------------------------------


def test_cache_creation_tokens_are_counted():
    """The headline trap: input_tokens=2 while cache creation is 47,052."""
    record = parse_usage_line(assistant_line(ts=NOW))
    assert record is not None
    assert record.usage.input_tokens == 2
    assert record.usage.cache_write_1h_tokens == 47_052
    assert record.usage.total_input_tokens == 47_054
    assert window_tokens(record.usage) == 47_054 + 901


def test_iterations_are_not_double_counted():
    record = parse_usage_line(assistant_line(ts=NOW))
    assert record.usage.output_tokens == 901, "iterations[] must not be summed in"


def test_flat_cache_creation_is_attributed_when_ttl_breakdown_is_absent():
    """Older records carry no cache_creation table. Dropping those tokens would
    under-count; attributing them to the cheap 5m bucket would too."""
    line = assistant_line(ts=NOW)
    del line["message"]["usage"]["cache_creation"]
    record = parse_usage_line(line)
    assert record.usage.cache_write_1h_tokens == 47_052


def test_non_assistant_lines_are_ignored():
    assert parse_usage_line({"type": "user", "message": {}}) is None
    assert parse_usage_line({"type": "attachment"}) is None


def test_malformed_lines_return_none_rather_than_raising():
    """A parser that raises on an unfamiliar line makes the budget unavailable
    exactly when a CLI upgrade lands."""
    assert parse_usage_line({"type": "assistant"}) is None
    assert parse_usage_line({"type": "assistant", "message": {"usage": {}}}) is None
    assert parse_usage_line({"type": "assistant", "message": {"usage": {}}, "timestamp": "nope"}) is None


def test_thinking_tokens_never_exceed_output():
    record = parse_usage_line(assistant_line(ts=NOW, output=10, thinking=999))
    assert record.usage.thinking_tokens == 10


def test_duplicate_request_ids_are_dropped(tmp_path: Path):
    """Records recur across resumed sessions; 59% of the real corpus was
    duplicated. Blind summation multiplies the bill."""
    root = write_transcript(tmp_path, [
        assistant_line(ts=NOW, request_id="a"),
        assistant_line(ts=NOW, request_id="a"),
        assistant_line(ts=NOW, request_id="b"),
    ])
    scan = scan_usage(root)
    assert len(scan.records) == 2
    assert scan.duplicates_dropped == 1


def test_duplicates_are_dropped_across_files(tmp_path: Path):
    write_transcript(tmp_path, [assistant_line(ts=NOW, request_id="a")], "p1/s.jsonl")
    write_transcript(tmp_path, [assistant_line(ts=NOW, request_id="a")], "p2/s.jsonl")
    scan = scan_usage(tmp_path)
    assert len(scan.records) == 1
    assert scan.files_scanned == 2


def test_missing_projects_dir_warns_instead_of_crashing(tmp_path: Path):
    scan = scan_usage(tmp_path / "nope")
    assert scan.records == []
    assert any("does not exist" in w for w in scan.warnings)


def test_unparseable_lines_are_warned_not_fatal(tmp_path: Path):
    path = tmp_path / "p" / "s.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text('{"broken\n' + json.dumps(assistant_line(ts=NOW)) + "\n")
    scan = scan_usage(tmp_path)
    assert len(scan.records) == 1
    assert any("unparseable" in w for w in scan.warnings)


def test_cache_read_weight_lowers_counted_consumption():
    usage = TokenUsage(input_tokens=100, output_tokens=100, cache_read_tokens=100_000)
    assert window_tokens(usage, cache_read_weight=1.0) == 100_200
    assert window_tokens(usage, cache_read_weight=0.1) == 10_200


# -- window detection ------------------------------------------------------


def test_window_is_anchored_to_first_use_not_a_rolling_lookback():
    start_of_block = NOW - timedelta(hours=2)
    stamps = [start_of_block, start_of_block + timedelta(minutes=30)]
    start, end = current_window(stamps, NOW)
    assert start == start_of_block
    assert end == start_of_block + timedelta(hours=5)


def test_a_gap_of_five_hours_starts_a_new_window():
    old = NOW - timedelta(hours=9)
    recent = NOW - timedelta(minutes=10)
    start, _ = current_window([old, recent], NOW)
    assert start == recent


def test_no_recent_activity_reports_a_fresh_window():
    """Reporting full headroom is right; inventing consumption is not."""
    start, end = current_window([NOW - timedelta(hours=20)], NOW)
    assert start == NOW
    assert end == NOW + timedelta(hours=5)


def test_empty_history_is_a_fresh_window():
    start, _ = current_window([], NOW)
    assert start == NOW


# -- projection and downshift ----------------------------------------------


def plan_of(*tasks) -> Plan:
    return Plan(plan_id="p", goal="g", created_at=NOW, tasks=list(tasks))


def governor(tmp_path: Path, cfg=None, **kwargs) -> BudgetGovernor:
    cfg = cfg or config()
    router = TierRouter(cfg, catalog(model("cheap/x", price=0.05, context=200_000)))
    return BudgetGovernor(cfg, router, projects_dir=tmp_path / "empty", now=NOW, **kwargs)


def test_projection_includes_fixed_dispatch_overhead(tmp_path: Path):
    """A trivial task on a subscription backend is not cheap: the spawn alone
    costs ~30k tokens."""
    gov = governor(tmp_path)
    tokens, usd = gov.estimate_task(make_task("a", tier=Tier.CODE), Tier.CODE)
    assert tokens > 30_000
    assert usd == 0.0, "subscription work spends window, not dollars"


def test_metered_projection_is_in_dollars_not_window_tokens(tmp_path: Path):
    gov = governor(tmp_path)
    tokens, usd = gov.estimate_task(make_task("a", tier=Tier.MECHANICAL), Tier.MECHANICAL)
    assert tokens == 0
    assert usd > 0.0


def test_codex_subscription_projection_does_not_spend_claude_window(tmp_path: Path):
    cfg = config()
    backend = cfg.backends["sub"]
    cfg.backends["sub"] = type(backend)(
        name=backend.name,
        adapter=Adapter.CODEX,
        billing=backend.billing,
        models=backend.models,
        dispatch_overhead_tokens=backend.dispatch_overhead_tokens,
    )
    gov = governor(tmp_path, cfg=cfg)
    tokens, usd = gov.estimate_task(make_task("a", tier=Tier.CODE), Tier.CODE)
    assert tokens == 0 and usd == 0.0


def test_no_limit_means_no_downshift(tmp_path: Path):
    """The governor must never stop or reroute a run on a number it could not
    verify."""
    gov = governor(tmp_path)
    plan = plan_of(make_task("a", tier=Tier.REASON))
    assert gov.plan_tiers(plan) == {"a": Tier.REASON}
    assert gov.decisions == []


def test_tight_window_downshifts_the_costliest_task(tmp_path: Path):
    gov = governor(tmp_path, cfg=config(window_tokens_limit=60_000))
    plan = plan_of(make_task("a", tier=Tier.REASON), make_task("b", tier=Tier.EXTRACT))
    tiers = gov.plan_tiers(plan)
    assert gov.decisions, "a plan over budget must produce a logged downshift"
    assert tiers["a"] is not Tier.REASON
    assert all(d.reason for d in gov.decisions), "every downshift must record why"


def test_no_downshift_tasks_are_never_moved(tmp_path: Path):
    gov = governor(tmp_path, cfg=config(window_tokens_limit=1_000))
    plan = plan_of(make_task("a", tier=Tier.REASON, no_downshift=True))
    assert gov.plan_tiers(plan)["a"] is Tier.REASON
    assert gov.decisions == []


def test_longctx_is_never_downshifted(tmp_path: Path):
    """Moving a task off longctx is a correctness failure, not a saving."""
    gov = governor(tmp_path, cfg=config(window_tokens_limit=1_000))
    plan = plan_of(make_task("a", tier=Tier.LONGCTX))
    assert gov.plan_tiers(plan)["a"] is Tier.LONGCTX


def test_tier_for_reports_the_reason_a_task_moved(tmp_path: Path):
    gov = governor(tmp_path, cfg=config(window_tokens_limit=60_000))
    plan = plan_of(make_task("a", tier=Tier.REASON), make_task("b", tier=Tier.EXTRACT))
    gov.plan_tiers(plan)
    tier, reason = gov.tier_for(plan.by_id["a"])
    if tier is not Tier.REASON:
        assert reason and "window tokens" in reason


def test_completed_tasks_are_excluded_from_the_projection(tmp_path: Path):
    from sleipnir.projection import TaskState
    from sleipnir.schema import TaskStatus

    gov = governor(tmp_path)
    plan = plan_of(make_task("a", tier=Tier.CODE), make_task("b", tier=Tier.CODE))
    states = {
        "a": TaskState(task_id="a", status=TaskStatus.DONE),
        "b": TaskState(task_id="b", status=TaskStatus.READY),
    }
    projection = gov.project(plan, states)
    assert set(projection.per_task) == {"b"}


# -- dispatch control ------------------------------------------------------


def test_unknown_limit_never_denies_a_dispatch(tmp_path: Path):
    gov = governor(tmp_path)
    allowed, why = gov.should_dispatch(make_task("a"))
    assert allowed and why == ""


def test_exhausted_window_denies_dispatch(tmp_path: Path):
    root = write_transcript(tmp_path / "projects", [
        assistant_line(ts=NOW - timedelta(minutes=5), request_id="r1", cache_creation=500_000)
    ])
    cfg = config(window_tokens_limit=10_000)
    router = TierRouter(cfg, catalog(model("cheap/x", price=0.05, context=200_000)))
    gov = BudgetGovernor(cfg, router, projects_dir=root, now=NOW)
    allowed, why = gov.should_dispatch(make_task("a"))
    assert not allowed
    assert "window is exhausted" in why


def test_exhausted_claude_window_does_not_deny_codex_subscription(tmp_path: Path):
    root = write_transcript(tmp_path / "projects", [
        assistant_line(ts=NOW - timedelta(minutes=5), request_id="r1", cache_creation=500_000)
    ])
    cfg = config(window_tokens_limit=10_000)
    backend = cfg.backends["sub"]
    cfg.backends["sub"] = type(backend)(
        name=backend.name,
        adapter=Adapter.CODEX,
        billing=backend.billing,
        models=backend.models,
        dispatch_overhead_tokens=backend.dispatch_overhead_tokens,
    )
    router = TierRouter(cfg, catalog(model("cheap/x", price=0.05, context=200_000)))
    gov = BudgetGovernor(cfg, router, projects_dir=root, now=NOW, read_real_utilization=False)

    allowed, why = gov.should_dispatch(make_task("a", tier=Tier.CODE), Tier.CODE)

    assert allowed and why == ""


def test_spent_metered_budget_denies_dispatch(tmp_path: Path):
    cfg = config(metered_budget_usd=1.0)
    router = TierRouter(cfg, catalog(model("cheap/x", price=0.05, context=200_000)))
    gov = BudgetGovernor(
        cfg, router, projects_dir=tmp_path / "none", now=NOW, metered_spent_usd=5.0
    )
    allowed, why = gov.should_dispatch(make_task("a"), Tier.MECHANICAL)
    assert not allowed
    assert "metered budget" in why


def test_metered_reservations_prevent_concurrent_dispatches_from_exceeding_budget(tmp_path: Path):
    cfg = config()
    router = TierRouter(cfg, catalog(model("cheap/x", price=0.05, context=200_000)))
    gov = BudgetGovernor(cfg, router, projects_dir=tmp_path / "none", now=NOW)
    first = make_task("a", tier=Tier.MECHANICAL)
    second = make_task("b", tier=Tier.MECHANICAL)
    cfg.metered_budget_usd = gov.estimate_task(first, Tier.MECHANICAL)[1] * 1.5

    allowed, _ = gov.should_dispatch(first, Tier.MECHANICAL)
    assert allowed
    allowed, why = gov.should_dispatch(second, Tier.MECHANICAL)
    assert not allowed
    assert "would be exceeded" in why


def test_snapshot_surfaces_parse_warnings(tmp_path: Path):
    gov = governor(tmp_path)
    snapshot = gov.snapshot()
    assert any("does not exist" in w for w in snapshot.parse_warnings)


def test_synthetic_records_are_not_costed():
    """The CLI writes its own messages under model "<synthetic>".

    They carry a usage block but were never API calls, so costing them invents
    spend that never happened. Nine appear in the local transcript corpus.
    """
    from sleipnir.budget import parse_usage_line

    payload = {
        "type": "assistant",
        "timestamp": "2026-08-18T12:00:00.000Z",
        "requestId": "req_synthetic",
        "message": {
            "model": "<synthetic>",
            "usage": {"input_tokens": 5, "output_tokens": 7},
        },
    }
    assert parse_usage_line(payload) is None

    payload["message"]["model"] = "claude-opus-5"
    assert parse_usage_line(payload) is not None


# ---------------------------------------------------------------------------
# Real window utilisation (operator-approved credential read)
# ---------------------------------------------------------------------------


def _creds(tmp_path, *, token="tok-abc", expires_ms=None, extra=None):
    import json as _json
    from datetime import UTC as _UTC, datetime as _dt, timedelta as _td

    if expires_ms is None:
        expires_ms = int((_dt.now(_UTC) + _td(hours=1)).timestamp() * 1000)
    payload = {
        "claudeAiOauth": {
            "accessToken": token,
            "refreshToken": "refresh",
            "expiresAt": expires_ms,
        },
        # The same file holds unrelated plugin secrets. They must never be read.
        "pluginSecrets": {"someplugin": {"api_token": "MUST-NOT-BE-READ"}},
    }
    if extra:
        payload.update(extra)
    p = tmp_path / ".credentials.json"
    p.write_text(_json.dumps(payload), encoding="utf-8")
    return p


@pytest.mark.allow_utilization_reads
def test_reads_only_the_oauth_access_token(tmp_path):
    from sleipnir.budget import read_oauth_token

    assert read_oauth_token(_creds(tmp_path, token="tok-xyz")) == "tok-xyz"


@pytest.mark.allow_utilization_reads
def test_missing_credential_file_yields_none_not_an_error(tmp_path):
    from sleipnir.budget import read_oauth_token

    assert read_oauth_token(tmp_path / "nope.json") is None


@pytest.mark.allow_utilization_reads
def test_expired_token_is_not_used(tmp_path):
    """Skip the round trip rather than send a token that will 401."""
    from sleipnir.budget import read_oauth_token

    assert read_oauth_token(_creds(tmp_path, expires_ms=1)) is None


@pytest.mark.allow_utilization_reads
def test_unexpected_credential_shape_yields_none(tmp_path):
    import json as _json

    from sleipnir.budget import read_oauth_token

    p = tmp_path / ".credentials.json"
    p.write_text(_json.dumps({"somethingElse": {}}), encoding="utf-8")
    assert read_oauth_token(p) is None

    p.write_text("{not json", encoding="utf-8")
    assert read_oauth_token(p) is None


@pytest.mark.allow_utilization_reads
def test_utilisation_is_parsed_from_the_meters_response():
    import httpx as _httpx

    from sleipnir.budget import fetch_window_utilization

    def handler(request: _httpx.Request) -> _httpx.Response:
        assert request.headers["authorization"] == "Bearer tok-abc"
        return _httpx.Response(
            200,
            json={
                "five_hour": {
                    "utilization": 77.0,
                    "resets_at": "2026-08-18T18:20:00.481653+00:00",
                    # Null on a subscription: there is no token count and no
                    # dollar figure, only a percentage.
                    "limit_dollars": None,
                    "used_dollars": None,
                },
                "seven_day": {"utilization": 22.0, "resets_at": None},
            },
        )

    reading = fetch_window_utilization(
        token="tok-abc", transport=_httpx.MockTransport(handler)
    )
    assert reading is not None
    assert reading.five_hour_percent == 77.0
    assert reading.seven_day_percent == 22.0
    assert reading.resets_at is not None


@pytest.mark.allow_utilization_reads
def test_a_failing_endpoint_degrades_to_none_rather_than_raising():
    import httpx as _httpx

    from sleipnir.budget import fetch_window_utilization

    def boom(request: _httpx.Request) -> _httpx.Response:
        raise _httpx.ConnectError("no network")

    assert (
        fetch_window_utilization(token="t", transport=_httpx.MockTransport(boom))
        is None
    )

    def unauthorised(request: _httpx.Request) -> _httpx.Response:
        return _httpx.Response(401, text="expired")

    assert (
        fetch_window_utilization(
            token="t", transport=_httpx.MockTransport(unauthorised)
        )
        is None
    )


@pytest.mark.allow_utilization_reads
def test_a_changed_response_shape_degrades_to_none():
    import httpx as _httpx

    from sleipnir.budget import fetch_window_utilization

    def renamed(request: _httpx.Request) -> _httpx.Response:
        return _httpx.Response(200, json={"5h": {"pct": 77.0}})

    assert (
        fetch_window_utilization(token="t", transport=_httpx.MockTransport(renamed))
        is None
    )


def test_implied_limit_solves_for_the_limit_matching_local_accounting():
    """The reading is a percentage; everything downstream works in tokens.

    Solving limit = used / (pct/100) is self-calibrating: whatever weight the
    real meter gives cache reads is absorbed into the implied limit, so the
    1:1-versus-price-weighted question stops mattering.
    """
    from sleipnir.budget import WindowUtilization

    reading = WindowUtilization(five_hour_percent=50.0)
    assert reading.implied_limit_tokens(1_000_000) == 2_000_000

    reading = WindowUtilization(five_hour_percent=77.0)
    assert reading.implied_limit_tokens(7_700_000) == 10_000_000


def test_implied_limit_refuses_when_utilisation_is_too_small_to_divide_by():
    """Near zero the division explodes and would imply a wildly wrong limit."""
    from sleipnir.budget import WindowUtilization

    assert WindowUtilization(five_hour_percent=0.0).implied_limit_tokens(1_000) is None
    assert WindowUtilization(five_hour_percent=1.0).implied_limit_tokens(1_000) is None
    assert WindowUtilization(five_hour_percent=50.0).implied_limit_tokens(0) is None


@pytest.mark.allow_utilization_reads
def test_a_rate_limited_meter_degrades_and_does_not_retry_immediately():
    """The usage endpoint is itself rate-limited — observed returning 429.

    A governor that retried on 429 would throttle itself out of the very
    reading it depends on, so a failure must be cached like a success.
    """
    import httpx as _httpx

    from sleipnir.budget import fetch_window_utilization

    calls = {"n": 0}

    def throttled(request: _httpx.Request) -> _httpx.Response:
        calls["n"] += 1
        return _httpx.Response(429, text="rate limited")

    assert (
        fetch_window_utilization(token="t", transport=_httpx.MockTransport(throttled))
        is None
    )
    assert calls["n"] == 1, "a 429 must not be retried inside a single call"
