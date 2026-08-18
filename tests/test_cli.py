"""CLI: the five commands, end to end, with no network and no spend."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_executor import ScriptedAdapter
from test_router import CONFIG_TOML

from sleipnir import cli
from sleipnir.adapters.base import DispatchOutcome, DispatchRequest
from sleipnir.planner import PlanningError, assemble_plan, extract_plan_json
from sleipnir.schema import Adapter, AttemptStatus, BillingMode

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


def test_missing_plan_is_a_clean_error(workspace: Path, capsys):
    assert invoke(workspace, "status") == 2
    assert "no plan at" in capsys.readouterr().err


def test_no_catalogue_and_no_network_refuses_to_run(workspace: Path, monkeypatch, capsys):
    seed_plan(workspace, monkeypatch)
    (workspace / "models.json").unlink()
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
