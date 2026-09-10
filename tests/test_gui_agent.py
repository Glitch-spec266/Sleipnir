from __future__ import annotations

import asyncio

from sleipnir.gui_agent import handle_instruction
from sleipnir.gui_history import EncryptedHistory, main
from sleipnir.voice.relay import AmbientReply, WorkReply
from sleipnir.voice.local_agent import LocalAgentReply


class FakeAmbient:
    def __init__(self):
        self.calls = []

    async def respond(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        return AmbientReply("Fast answer.", kwargs["provider"], kwargs.get("model") or "free")


class FakeWork:
    def __init__(self):
        self.calls = []

    async def send(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        return WorkReply("Work complete.", kwargs["provider"], "session-1")


class FakeLocal:
    def __init__(self):
        self.calls = []

    async def respond(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        return LocalAgentReply("I can see the desktop.", kwargs["model"], 2)


def test_auto_route_stops_at_approval_before_work(tmp_path):
    work = FakeWork()
    result = asyncio.run(handle_instruction("Build and test the app", workspace=tmp_path, work=work))

    assert result["status"] == "approval"
    assert work.calls == []


def test_operator_approved_route_reaches_work_provider(tmp_path):
    work = FakeWork()
    result = asyncio.run(
        handle_instruction(
            "Build the app",
            workspace=tmp_path,
            route="codex",
            permission_mode="ask",
            work=work,
        )
    )

    assert result == {
        "status": "complete",
        "text": "Work complete.",
        "route": "codex",
        "rationale": "Operator approved the capable work lane.",
        "sessionId": "session-1",
    }
    assert work.calls[0][1]["permission_mode"] == "ask"


def test_ambient_uses_custom_activated_environment_name(tmp_path):
    ambient = FakeAmbient()
    result = asyncio.run(
        handle_instruction(
            "What is the status?",
            workspace=tmp_path,
            route="ambient",
            environment={"MY_GEMINI": "secret"},
            variable_names={"gemini": "MY_GEMINI", "openrouter": "NOPE", "nvidia-nim": "NOPE2"},
            ambient=ambient,
        )
    )

    assert result["text"] == "Fast answer."
    assert ambient.calls[0][1]["provider"] == "gemini"
    assert ambient.calls[0][1]["api_key"] == "secret"


def test_ambient_can_be_pinned_to_local_ollama_without_a_secret(tmp_path):
    ambient = FakeAmbient()
    result = asyncio.run(
        handle_instruction(
            "Explain angular momentum.",
            workspace=tmp_path,
            route="ambient",
            ambient_provider="ollama",
            model="qwen3.5:4b",
            environment={},
            ambient=ambient,
        )
    )

    assert result["text"] == "Fast answer."
    assert ambient.calls[0][1] == {
        "provider": "ollama",
        "api_key": "",
        "model": "qwen3.5:4b",
        "run_digest": "",
    }


def test_local_ollama_uses_the_multimodal_tool_loop_by_default(tmp_path):
    local = FakeLocal()
    result = asyncio.run(
        handle_instruction(
            "What is on my screen?",
            workspace=tmp_path,
            route="ambient",
            ambient_provider="ollama",
            model="jarvis",
            permission_mode="always",
            environment={},
            local_agent=local,
        )
    )

    assert result["text"] == "I can see the desktop."
    assert result["route"] == "ollama/jarvis"
    assert "2 step(s)" in result["rationale"]
    assert local.calls[0][1]["permission_mode"] == "always"


def test_a_completed_turn_round_trips_through_encrypted_history(tmp_path):
    """The Chronicle contract: a restart must reconstruct the conversation.

    The desktop keeps turns only in Rust memory during a session, so the
    encrypted log on disk is the sole thing a reconnect can rebuild from.  This
    covers the whole loop the Tauri host depends on: the agent writes both
    sides of the turn, and the sidecar CLI reads them back in order.
    """
    history_path = tmp_path / "history.enc.jsonl"
    key_path = tmp_path / "history.key"
    history = EncryptedHistory(history_path, key_path)

    asyncio.run(
        handle_instruction(
            "Build the app",
            workspace=tmp_path,
            route="codex",
            work=FakeWork(),
            history=history,
        )
    )

    entries = history.read()
    assert [entry["role"] for entry in entries] == ["operator", "sleipnir"]
    assert entries[0]["text"] == "Build the app"
    assert entries[1]["text"] == "Work complete."
    # Every entry carries a timestamp, or the rebuilt transcript has no order.
    assert all(entry["at"].endswith("Z") for entry in entries)

    # The bytes on disk are ciphertext; a restart is the only reader.
    assert b"Build the app" not in history_path.read_bytes()

    assert main(["--history", str(history_path), "--history-key", str(key_path)]) == 0
