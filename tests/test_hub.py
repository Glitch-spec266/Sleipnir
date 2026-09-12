"""The phone hub: what it will answer, and what it refuses to answer."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from sleipnir import platform
from sleipnir.hub import DEFAULT_PORT, HubConfig, MAX_TASKS, decide, load_token, serve


@pytest.fixture()
def hub(tmp_path: Path):
    (tmp_path / "proposals").mkdir()
    (tmp_path / "proposals" / "rev-1.json").write_text("{}", encoding="utf-8")
    preferences = tmp_path / "preferences.json"
    preferences.write_text(json.dumps({"voice": {"listeningEnabled": True}}), encoding="utf-8")
    config = HubConfig(run_root=tmp_path, token="test-token", preferences=preferences)
    # Port 0 lets the OS pick, so a developer already running a hub does not
    # make the suite fail with "address already in use".
    server = serve(config, host="127.0.0.1", port=0)
    try:
        yield config, f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()


def test_every_endpoint_refuses_an_unpaired_device(hub) -> None:
    """One of these returns a photograph of the operator's screen. An open
    endpoint on a home network is a screen-sharing server for the network."""
    _, base = hub

    assert httpx.get(f"{base}/api/status").status_code == 401
    assert httpx.get(f"{base}/api/screen").status_code == 401
    assert httpx.get(f"{base}/api/status", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert httpx.post(f"{base}/api/voice", json={"enabled": True}).status_code == 401


def test_the_status_response_does_not_grow_with_the_plan(hub, monkeypatch) -> None:
    """Same rule as the manifest and the dashboard snapshot: a field that grows
    with task count makes every poll from the phone linear in plan size."""
    config, base = hub

    def dashboard(run_root, **_):
        return {
            "runtime": {},
            "run": None,
            "tasks": [
                {"id": f"t{index}", "title": "x", "status": "DONE", "group": "g"}
                for index in range(500)
            ],
            "reviews": [],
            "voice": {"phase": "armed"},
        }

    monkeypatch.setattr("sleipnir.gui.load_dashboard", dashboard)
    response = httpx.get(f"{base}/api/status", headers={"Authorization": "Bearer test-token"})

    payload = response.json()
    assert payload["taskTotal"] == 500
    assert payload["counts"] == {"DONE": 500}
    assert len(payload["tasks"]) == MAX_TASKS


def test_a_denied_review_keeps_the_desktop_s_own_naming(tmp_path: Path) -> None:
    """The desktop marks these ``<id>.json.rejected`` and the TUI counts
    pending work by looking for names still ending in ``.json``. Substituting
    the suffix instead of appending it would hide the file from both."""
    (tmp_path / "proposals").mkdir()
    (tmp_path / "proposals" / "rev-1.json").write_text("{}", encoding="utf-8")
    config = HubConfig(run_root=tmp_path, token="t")

    code, payload = decide(config, "rev-1", "reject")

    assert code == 200 and payload["status"] == "reject"
    assert (tmp_path / "proposals" / "rev-1.json.rejected").is_file()


def test_a_review_id_that_is_not_a_plain_name_is_refused(tmp_path: Path) -> None:
    config = HubConfig(run_root=tmp_path, token="t")

    for hostile in ("../secrets", "a/b", "a b", "a%2Fb", ""):
        code, payload = decide(config, hostile, "reject")
        assert code == 400, hostile
        assert "invalid" in payload["error"]


def test_an_unknown_decision_changes_nothing(tmp_path: Path) -> None:
    (tmp_path / "proposals").mkdir()
    proposal = tmp_path / "proposals" / "rev-1.json"
    proposal.write_text("{}", encoding="utf-8")
    config = HubConfig(run_root=tmp_path, token="t")

    code, _ = decide(config, "rev-1", "approve-everything")

    assert code == 400
    assert proposal.is_file()


def test_the_token_file_is_never_world_readable(tmp_path: Path) -> None:
    """Created with the mode, not chmod'ed afterwards: the gap between the two
    is a window where every account on the machine can read the credential."""
    path = tmp_path / "hub-token"

    first = load_token(path)
    assert first == load_token(path)
    assert platform.path_is_private(path)
    assert len(first) >= 24


def test_the_voice_toggle_is_requested_and_never_performed(hub) -> None:
    """The listener is a child of the desktop host. The hub emits an event and
    reports what it asked for; claiming it toggled would be a lie the phone
    would then display as fact."""
    _, base = hub

    response = httpx.post(
        f"{base}/api/voice",
        headers={"Authorization": "Bearer test-token"},
        json={"enabled": False},
    )

    assert response.json() == {"status": "requested", "enabled": False}


def test_the_default_port_is_stable() -> None:
    # The phone stores a paired address; changing this silently unpairs it.
    assert DEFAULT_PORT == 8765
