"""CLI: the five commands, end to end, with no network and no spend."""

from __future__ import annotations

import httpx
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_executor import ScriptedAdapter
from test_router import CONFIG_TOML

from sleipnir import cli
from sleipnir.adapters.base import DispatchOutcome, DispatchRequest
from sleipnir.planner import PlanningError, assemble_plan, extract_plan_json
from sleipnir.pricing import ModelCatalog
from sleipnir.schema import (
    Adapter,
    AttemptFinished,
    AttemptStatus,
    BillingMode,
    RetryPolicy,
    Task,
    TokenUsage,
)

GOOD_TASKS = {
    "tasks": [
        {
            "id": "schema",
            "description": "Design the state schema for the widget service.",
            "tier": "reason",
            "depends_on": [],
            "inputs": {"summaries": []},
            "outputs": {"outputs": [
                {"name": "schema", "kind": "file", "path": "schema.py",
                 "description": "Pydantic models."}
            ]},
        },
        {
            "id": "api",
            "description": "Implement the HTTP API against the agreed schema.",
            "tier": "code",
            "depends_on": ["schema"],
            "inputs": {"summaries": ["schema"]},
            "outputs": {"outputs": [
                {"name": "api", "kind": "file", "path": "api.py",
                 "description": "Route handlers."}
            ]},
        },
    ]
}


class PlanningAdapter(ScriptedAdapter):
    """Writes a plan.json instead of generic output."""

    name = Adapter.CLAUDE

    def __init__(self, payload=None, *, produce=True, **kwargs):
        super().__init__(**kwargs)
        # `produce=False` models the case where the planner returns prose.
        self.payload = (payload if payload is not None else GOOD_TASKS) if produce else None

    async def dispatch(self, request: DispatchRequest) -> DispatchOutcome:
        self.dispatched.append((request.task.id, request.attempt))
        request.workspace.prepare()
        if self.payload is not None:
            request.workspace.write_text("plan.json", json.dumps(self.payload))
        return DispatchOutcome(
            status=AttemptStatus.SUCCEEDED,
            billing_mode=BillingMode.SUBSCRIPTION,
            response_text=json.dumps(self.payload) if self.payload else "sorry, no.",
        )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A run root with a config and a pre-seeded catalogue cache (no network)."""
    cache = tmp_path / "models.json"
    cache.write_text(json.dumps({
        "_fetched_at": datetime.now(UTC).isoformat(),
        "data": [
            {"id": "cheap/x", "context_length": 200000,
             "pricing": {"prompt": "0.0000001", "completion": "0.0000004"},
             "supported_parameters": ["tools"]},
        ],
    }))
    # Top-level keys MUST precede the [tables]; a bare key after a table
    # header belongs to that table, not to the document root.
    (tmp_path / "sleipnir.toml").write_text(
        f'catalog_cache_path = "{cache}"\ncatalog_ttl_s = 99999\n' + CONFIG_TOML
    )
    return tmp_path


def invoke(workspace: Path, *args: str) -> int:
    return cli.main(["--config", str(workspace / "sleipnir.toml"),
                     "--run-root", str(workspace), *args])


# -- plan ------------------------------------------------------------------


def test_plan_writes_a_validated_dag(workspace: Path, monkeypatch, capsys):
    adapter = PlanningAdapter()
    monkeypatch.setattr(cli, "build_adapters", lambda config: {Adapter.CLAUDE: adapter})
    assert invoke(workspace, "plan", "Build a widget service") == 0

    plan_file = workspace / "plan.json"
    assert plan_file.exists()
    payload = json.loads(plan_file.read_text())
    assert [t["id"] for t in payload["tasks"]] == ["schema", "api"]
    assert payload["goal"] == "Build a widget service"
    out = capsys.readouterr().out
    assert "2 tasks" in out and "schema" in out


def test_plan_refuses_to_clobber_an_existing_plan(workspace: Path, monkeypatch):
    monkeypatch.setattr(cli, "build_adapters", lambda config: {Adapter.CLAUDE: PlanningAdapter()})
    invoke(workspace, "plan", "Build it")
    assert invoke(workspace, "plan", "Build it again") == 2
    assert invoke(workspace, "plan", "Build it again", "--force") == 0
    attempts = workspace / "artifacts" / "task-sleipnir-plan"
    assert sorted(path.name for path in attempts.iterdir()) == ["attempt-01", "attempt-02"]


def test_plan_rejects_an_invalid_dag(workspace: Path, monkeypatch, capsys):
    """A cycle must fail at planning time, not at task 40."""
    cyclic = {"tasks": [
        dict(GOOD_TASKS["tasks"][0], depends_on=["api"], inputs={"summaries": ["api"]}),
        GOOD_TASKS["tasks"][1],
    ]}
    monkeypatch.setattr(
        cli, "build_adapters", lambda config: {Adapter.CLAUDE: PlanningAdapter(cyclic)}
    )
    assert invoke(workspace, "plan", "Build it") == 2
    assert "invalid" in capsys.readouterr().err


def test_plan_reports_when_the_model_produced_no_json(workspace: Path, monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "build_adapters", lambda config: {Adapter.CLAUDE: PlanningAdapter(produce=False)}
    )
    assert invoke(workspace, "plan", "Build it") == 2
    assert "no parseable JSON" in capsys.readouterr().err


# -- run / dry-run ---------------------------------------------------------


def seed_plan(workspace: Path, monkeypatch) -> None:
    monkeypatch.setattr(cli, "build_adapters", lambda config: {Adapter.CLAUDE: PlanningAdapter()})
    invoke(workspace, "plan", "Build a widget service")


def test_dry_run_dispatches_nothing(workspace: Path, monkeypatch, capsys):
    seed_plan(workspace, monkeypatch)
    worker = ScriptedAdapter()
    monkeypatch.setattr(cli, "build_adapters", lambda config: {
        Adapter.CLAUDE: worker, Adapter.OPENROUTER: worker
    })
    assert invoke(workspace, "run", "--dry-run") == 0
    assert worker.dispatched == []
    assert not (workspace / "results.jsonl").exists()
    assert "nothing dispatched, nothing spent" in capsys.readouterr().out


def test_run_executes_the_dag_in_dependency_order(workspace: Path, monkeypatch, capsys):
    seed_plan(workspace, monkeypatch)
    worker = ScriptedAdapter()
    monkeypatch.setattr(cli, "build_adapters", lambda config: {
        Adapter.CLAUDE: worker, Adapter.OPENROUTER: worker
    })
    assert invoke(workspace, "run") == 0
    assert [tid for tid, _ in worker.dispatched] == ["schema", "api"]
    assert "ok=2" in capsys.readouterr().out


def test_resume_does_not_repeat_completed_work(workspace: Path, monkeypatch):
    seed_plan(workspace, monkeypatch)
    first = ScriptedAdapter()
    monkeypatch.setattr(cli, "build_adapters", lambda config: {
        Adapter.CLAUDE: first, Adapter.OPENROUTER: first
    })
    invoke(workspace, "run")

    second = ScriptedAdapter()
    monkeypatch.setattr(cli, "build_adapters", lambda config: {
        Adapter.CLAUDE: second, Adapter.OPENROUTER: second
    })
    assert invoke(workspace, "resume") == 0
    assert second.dispatched == []


def test_explain_flag_prints_routing_for_every_task(workspace: Path, monkeypatch, capsys):
    seed_plan(workspace, monkeypatch)
    worker = ScriptedAdapter()
    monkeypatch.setattr(cli, "build_adapters", lambda config: {
        Adapter.CLAUDE: worker, Adapter.OPENROUTER: worker
    })
    invoke(workspace, "run", "--dry-run", "--explain")
    out = capsys.readouterr().out
    assert "=== routing ===" in out
    assert "tier declared" in out and "candidates:" in out


# -- status / explain ------------------------------------------------------


def test_status_shows_every_task_and_the_budget(workspace: Path, monkeypatch, capsys):
    seed_plan(workspace, monkeypatch)
    worker = ScriptedAdapter()
    monkeypatch.setattr(cli, "build_adapters", lambda config: {
        Adapter.CLAUDE: worker, Adapter.OPENROUTER: worker
    })
    invoke(workspace, "run")
    assert invoke(workspace, "status") == 0
    out = capsys.readouterr().out
    assert "schema" in out and "api" in out
    assert "done" in out
    assert "burn rate" in out and "headroom" in out
    assert "manifest:" in out


def test_status_before_any_run_shows_pending_work(workspace: Path, monkeypatch, capsys):
    seed_plan(workspace, monkeypatch)
    capsys.readouterr()
    assert invoke(workspace, "status") == 0
    out = capsys.readouterr().out
    assert "ready" in out or "blocked" in out


def test_tui_renders_a_safe_static_dashboard(workspace: Path, monkeypatch, capsys):
    seed_plan(workspace, monkeypatch)
    async def no_catalog(*args, **kwargs):
        raise AssertionError("static TUI must not load the network catalogue")
    monkeypatch.setattr(cli, "load_catalog", no_catalog)
    capsys.readouterr()
    assert invoke(workspace, "tui") == 0
    out = capsys.readouterr().out
    assert "SLEIPNIR" in out and "schema" in out and "api" in out


def test_tui_can_own_and_execute_the_run(workspace: Path, monkeypatch, capsys):
    seed_plan(workspace, monkeypatch)
    worker = ScriptedAdapter()
    monkeypatch.setattr(cli, "build_adapters", lambda config: {
        Adapter.CLAUDE: worker, Adapter.OPENROUTER: worker
    })
    capsys.readouterr()
    assert invoke(workspace, "tui", "--run", "--refresh", "0.001") == 0
    assert [task_id for task_id, _ in worker.dispatched] == ["schema", "api"]
    assert "SLEIPNIR" in capsys.readouterr().out


def test_tui_can_own_sparse_orchestration_without_an_extra_brain_call(
    workspace: Path, monkeypatch, capsys
):
    seed_plan(workspace, monkeypatch)
    worker = ScriptedAdapter()
    monkeypatch.setattr(cli, "build_adapters", lambda config: {
        Adapter.CLAUDE: worker, Adapter.OPENROUTER: worker
    })
    capsys.readouterr()
    assert invoke(workspace, "tui", "--orchestrate", "--refresh", "0.001") == 0
    assert [task_id for task_id, _ in worker.dispatched] == ["schema", "api"]
    out = capsys.readouterr().out
    assert "SLEIPNIR" in out and "orchestration complete" in out


def test_orchestrate_completes_without_spending_a_brain_call_when_workers_succeed(
    workspace: Path, monkeypatch, capsys
):
    seed_plan(workspace, monkeypatch)
    worker = ScriptedAdapter()
    monkeypatch.setattr(cli, "build_adapters", lambda config: {
        Adapter.CLAUDE: worker, Adapter.OPENROUTER: worker
    })
    capsys.readouterr()
    assert invoke(workspace, "orchestrate") == 0
    assert [task_id for task_id, _ in worker.dispatched] == ["schema", "api"]
    assert "orchestration complete" in capsys.readouterr().out


def test_orchestrate_applies_brain_revision_and_resumes_failed_work(
    workspace: Path, monkeypatch, capsys
):
    seed_plan(workspace, monkeypatch)
    plan = cli.load_plan(workspace)
    replacement = plan.by_id["schema"].model_copy(
        update={"retry": RetryPolicy(max_attempts=3)}
    )

    class BrainAndWorkers(ScriptedAdapter):
        name = Adapter.CLAUDE

        def __init__(self):
            super().__init__(fail_first=2)
            self.control_calls = 0

        async def dispatch(self, request):
            if request.task.id == "sleipnir-control":
                self.control_calls += 1
                request.workspace.prepare()
                request.workspace.write_text("decision.json", json.dumps({
                    "action": "revise",
                    "reason": "Allow one additional routed attempt for the failed schema task.",
                    "changes": [{
                        "op": "retarget_task",
                        "task_id": "schema",
                        "detail": "Increase retry allowance without changing task meaning.",
                        "task": replacement.model_dump(mode="json"),
                        "dependency_id": None,
                    }],
                }))
                return DispatchOutcome(
                    status=AttemptStatus.SUCCEEDED,
                    billing_mode=BillingMode.SUBSCRIPTION,
                    usage=TokenUsage(input_tokens=80, output_tokens=20),
                    reported_cost_usd=0.25,
                )
            return await super().dispatch(request)

    harness = BrainAndWorkers()
    monkeypatch.setattr(cli, "build_adapters", lambda config: {
        Adapter.CLAUDE: harness, Adapter.OPENROUTER: harness
    })
    capsys.readouterr()
    # --no-auto-escalate keeps this test on the path it was written for: the
    # phase gate would otherwise retry the failed module one tier stronger and
    # the brain would never be consulted. The gate's own path is covered by
    # test_phase_gate_escalates_a_failed_module_without_waking_the_brain.
    assert invoke(workspace, "orchestrate", "--no-auto-escalate") == 0
    assert harness.control_calls == 1
    assert [item for item in harness.dispatched if item[0] == "schema"] == [
        ("schema", 1), ("schema", 2), ("schema", 3)
    ]
    assert cli.load_plan(workspace).revision == 1
    assert (workspace / "revisions.jsonl").exists()
    control_records = [
        record
        for record in cli.result_log(workspace).read()
        if isinstance(record, AttemptFinished)
        and record.task_id == "sleipnir-control"
    ]
    assert len(control_records) == 1
    assert control_records[0].cost.window_tokens == 100
    assert control_records[0].cost.quota_pool == "claude"
    assert control_records[0].artifacts[0].name == "decision"


def test_phase_gate_escalates_a_failed_module_without_waking_the_brain(
    workspace: Path, monkeypatch, capsys
):
    """The gate exists to keep the expensive brain asleep.

    A module that failed on a weak tier is the common case, and it has a
    mechanical answer: run it again with a better agent. Paying for a
    reason-tier spawn to be told that is the cost the whole design avoids.
    """
    seed_plan(workspace, monkeypatch)
    # The seeded `schema` task is reason-tier, which is the top of the ladder —
    # the gate rightly refuses to "escalate" it, since there is no better agent
    # to give it. Drop it a rung so this test exercises the escalation path.
    payload = json.loads((workspace / "plan.json").read_text())
    for entry in payload["tasks"]:
        if entry["id"] == "schema":
            entry["tier"] = "code"
    (workspace / "plan.json").write_text(json.dumps(payload))

    class NeverConsulted(ScriptedAdapter):
        name = Adapter.CLAUDE

        def __init__(self):
            super().__init__(fail_first=2)
            self.control_calls = 0

        async def dispatch(self, request):
            if request.task.id == "sleipnir-control":
                self.control_calls += 1
            return await super().dispatch(request)

    harness = NeverConsulted()
    monkeypatch.setattr(cli, "build_adapters", lambda config: {
        Adapter.CLAUDE: harness, Adapter.OPENROUTER: harness
    })
    capsys.readouterr()
    assert invoke(workspace, "orchestrate") == 0
    assert harness.control_calls == 0, "the gate must not need the brain for this"

    output = capsys.readouterr().out
    assert "phase gate" in output
    assert "gate escalation" in output
    # The escalation is a real, audited plan revision — not a hidden retry.
    assert (workspace / "revisions.jsonl").exists()
    assert cli.load_plan(workspace).revision >= 1


def test_apply_revision_requires_explicit_operator_command_for_semantic_change(
    workspace: Path, monkeypatch, capsys
):
    seed_plan(workspace, monkeypatch)
    plan = cli.load_plan(workspace)
    replacement = plan.by_id["schema"].model_copy(
        update={"description": "Implement a materially corrected schema contract."}
    )
    proposal = workspace / "reviewed.json"
    proposal.write_text(json.dumps({
        "action": "revise",
        "reason": "The operator reviewed and approved this corrected schema contract.",
        "changes": [{
            "op": "respec_task",
            "task_id": "schema",
            "detail": "Correct the semantic contract.",
            "task": replacement.model_dump(mode="json"),
            "dependency_id": None,
        }],
    }))
    capsys.readouterr()
    assert invoke(workspace, "apply-revision", str(proposal)) == 0
    revised = cli.load_plan(workspace)
    assert revised.revision == 1
    assert revised.by_id["schema"].description == replacement.description


def test_apply_revision_clears_pending_proposal_badge_source(
    workspace: Path, monkeypatch, capsys
):
    seed_plan(workspace, monkeypatch)
    plan = cli.load_plan(workspace)
    replacement = plan.by_id["schema"].model_copy(
        update={"retry": plan.by_id["schema"].retry.model_copy(update={"max_attempts": 4})}
    )
    proposals = workspace / "proposals"
    proposals.mkdir()
    proposal = proposals / "revision-1-reviewed.json"
    proposal.write_text(json.dumps({
        "action": "revise",
        "reason": "Operator reviewed the routing-only retry change.",
        "changes": [{
            "op": "retarget_task",
            "task_id": "schema",
            "detail": "Permit one more provider retry.",
            "task": replacement.model_dump(mode="json"),
            "dependency_id": None,
        }],
    }))
    capsys.readouterr()
    assert invoke(workspace, "apply-revision", str(proposal)) == 0
    assert not proposal.exists()
    assert proposal.with_suffix(".json.applied").exists()
    assert list(proposals.glob("*.json")) == []


def test_explain_shows_contract_and_attempts(workspace: Path, monkeypatch, capsys):
    seed_plan(workspace, monkeypatch)
    worker = ScriptedAdapter()
    monkeypatch.setattr(cli, "build_adapters", lambda config: {
        Adapter.CLAUDE: worker, Adapter.OPENROUTER: worker
    })
    invoke(workspace, "run")
    capsys.readouterr()
    assert invoke(workspace, "explain", "api") == 0
    out = capsys.readouterr().out
    assert "depends on : schema" in out
    assert "attempts:" in out
    assert "artifacts :" in out
    assert "rationale" in out


def test_explain_rejects_an_unknown_task(workspace: Path, monkeypatch, capsys):
    seed_plan(workspace, monkeypatch)
    assert invoke(workspace, "explain", "ghost") == 2
    assert "no task 'ghost'" in capsys.readouterr().err


# -- failure modes ---------------------------------------------------------


def test_missing_config_is_a_clean_error(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["--run-root", str(tmp_path), "status"]) == 2
    assert "no sleipnir.toml found" in capsys.readouterr().err


@pytest.mark.parametrize("args", [("run", "--concurrency", "0"), ("tui", "--refresh", "nan")])
def test_cli_rejects_values_that_would_stall_or_spin(workspace: Path, args):
    with pytest.raises(SystemExit):
        invoke(workspace, *args)


def test_missing_plan_is_a_clean_error(workspace: Path, capsys):
    assert invoke(workspace, "status") == 2
    assert "no plan at" in capsys.readouterr().err


def test_no_catalogue_and_no_network_refuses_to_run(workspace: Path, monkeypatch, capsys):
    """Deleting the cache is not enough — the fetch must actually be blocked.

    Without this the test only passes on a machine that happens to be offline:
    a live fetch succeeds, the refusal never fires, and the run proceeds. That
    made one of the project's stated safety guarantees pass by accident.
    """
    seed_plan(workspace, monkeypatch)
    (workspace / "models.json").unlink()

    async def no_network(self):
        raise httpx.ConnectError("network disabled for this test")

    monkeypatch.setattr(ModelCatalog, "_fetch", no_network)
    monkeypatch.setattr(cli, "build_adapters", lambda config: {})
    assert invoke(workspace, "run") == 2
    assert "will not guess model prices" in capsys.readouterr().err


# -- planner helpers -------------------------------------------------------


def test_extract_plan_json_handles_fenced_output():
    assert extract_plan_json('here you go:\n```json\n{"tasks": []}\n```') == {"tasks": []}


def test_extract_plan_json_handles_bare_json():
    assert extract_plan_json('{"tasks": [1]}') == {"tasks": [1]}


def test_extract_plan_json_returns_none_on_prose():
    assert extract_plan_json("I could not do that.") is None


def test_assemble_plan_requires_a_task_list():
    with pytest.raises(PlanningError, match="non-empty 'tasks' list"):
        assemble_plan({"tasks": []}, goal="g", plan_id="p")


# ---------------------------------------------------------------------------
# Top-level mode split (Phase 10)
# ---------------------------------------------------------------------------


def test_every_project_command_exists_in_both_namespaces():
    """`sleipnir project run` is canonical; `sleipnir run` stays as a legacy
    alias. Both must resolve to the same handler so existing scripts and new
    muscle memory agree."""
    parser = cli.build_parser()
    for name, extra in (("plan", ["x"]), ("explain", ["task-1"]), ("apply-revision", ["p.json"])):
        argv_tail = [name] + extra
        top = parser.parse_args(argv_tail)
        nested = parser.parse_args(["project"] + argv_tail)
        assert top.func is nested.func, name
    for bare in ("run", "resume", "status", "tui", "orchestrate"):
        top = parser.parse_args([bare])
        nested = parser.parse_args(["project", bare])
        assert top.func is nested.func, bare


def test_bare_sleipnir_opens_the_chat_console_as_claude(monkeypatch):
    import asyncio

    opened: dict = {}

    class FakeConsole:
        def __enter__(self):
            return True

        def __exit__(self, *exc):
            return False

    async def fake_run_console(state, *, splash=True):
        opened["provider"] = state.provider
        opened["model"] = state.model
        return 0

    monkeypatch.setattr("sleipnir.console.run_console", fake_run_console)
    monkeypatch.setattr("sleipnir.console.raw_terminal", FakeConsole)
    rc = cli.main([])
    assert rc == 0
    assert opened == {"provider": "claude", "model": "sonnet"}


def test_chat_selects_the_provider_from_the_command_line(monkeypatch):
    import asyncio

    opened: dict = {}

    class FakeConsole:
        def __enter__(self):
            return True

        def __exit__(self, *exc):
            return False

    async def fake_run_console(state, *, splash=True):
        opened["provider"] = state.provider
        return 0

    monkeypatch.setattr("sleipnir.console.run_console", fake_run_console)
    monkeypatch.setattr("sleipnir.console.raw_terminal", FakeConsole)
    cli.main(["chat", "--provider", "codex"])
    assert opened["provider"] == "codex"


def test_the_direct_console_never_touches_orchestration_machinery():
    """Executable form of the boundary between modes: direct-mode chat must
    not load plans, build manifests or apply revisions — anywhere, including
    lazy imports. The duty officer's bounded digest (gate/projection folds)
    is the one sanctioned overlap and stays read-only."""
    from pathlib import Path

    package = Path(cli.__file__).parent
    for module_name in ("chat.py", "console.py"):
        source = package.joinpath(module_name).read_text(encoding="utf-8")
        for forbidden in ("load_plan", "build_manifest", "apply_revision", "RunLock("):
            assert forbidden not in source, f"{module_name} references {forbidden}"


def test_the_planner_is_told_how_to_declare_a_dependency_artifact():
    """The schema has always supported artifact reads; the prompt hid them.

    A live run planned a test task whose acceptance command imported the
    library task's output, but declared only that task's summary. Each task
    runs in its own directory, so the file was simply absent and all three
    attempts failed identically.
    """
    from sleipnir.planner import build_planner_task

    instructions = build_planner_task("build something").inputs.instructions or ""
    assert "inputs.artifacts" in instructions
    assert "not on PATH" in instructions


def test_a_long_goal_is_clipped_instead_of_truncating_the_planner_rules():
    """The goal sits near the top of the prompt, the rules below it.

    Clipping the assembled prompt therefore threw away the output contract and
    every rule while keeping the goal, and did it silently — the planner would
    be asked for a plan with no description of what a plan is.
    """
    from sleipnir.planner import build_planner_task

    instructions = build_planner_task("Y" * 5_000).inputs.instructions or ""
    assert "inputs.artifacts" in instructions
    assert "Write only" in instructions
    assert "truncated" in instructions
