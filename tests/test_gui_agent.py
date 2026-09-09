from __future__ import annotations

import asyncio

from sleipnir.gui_agent import handle_instruction
from sleipnir.voice.relay import AmbientReply, WorkReply


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
