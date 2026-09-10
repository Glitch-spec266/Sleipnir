"""Phase 21.7 gate: destructive-action and secret-boundary adversarial tests.

These do not confirm the happy path.  Each one tries to get a secret out of a
surface that promises not to carry it, or tries to reach a capable work lane
without the operator having approved it.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from sleipnir.gui import load_dashboard
from sleipnir.gui_agent import handle_instruction
from sleipnir.gui_history import EncryptedHistory
from sleipnir.voice.relay import AmbientReply, WorkRelay

SECRET = "sk-do-not-leak-4f9a2c"


class RecordingAmbient:
    def __init__(self):
        self.calls = []

    async def respond(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        return AmbientReply("Fast answer.", kwargs["provider"], "free")


class RefusingWork:
    """A work lane that fails the test if it is ever reached."""

    def __init__(self):
        self.calls = []

    async def send(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        raise AssertionError("work lane reached without operator approval")


class CapturingTransport:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def turn(self, _prompt):
        class Event:
            kind = "final"
            text = "done"

        yield Event()

    async def close(self):
        return None


# --------------------------------------------------------------------------
# Secret boundary
# --------------------------------------------------------------------------


def test_dashboard_snapshot_never_carries_a_provider_key_value(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", SECRET)
    monkeypatch.setenv("GEMINI_API_KEY", SECRET)
    monkeypatch.setenv("NVIDIA_API_KEY", SECRET)

    encoded = json.dumps(load_dashboard(tmp_path))

    assert SECRET not in encoded


def test_snapshot_provider_env_carries_names_and_not_values(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", SECRET)

    snapshot = load_dashboard(tmp_path)
    provider_env = snapshot["settings"]["providerEnv"]

    # Names are safe to render; the values behind them are not.
    assert provider_env["openrouter"] == "OPENROUTER_API_KEY"
    assert SECRET not in provider_env.values()


def test_an_activated_key_never_reaches_the_reply_or_the_history(tmp_path):
    history = EncryptedHistory(tmp_path / "history.enc.jsonl", tmp_path / "history.key")
    ambient = RecordingAmbient()

    result = asyncio.run(
        handle_instruction(
            "What is the status?",
            workspace=tmp_path,
            route="ambient",
            environment={"GEMINI_API_KEY": SECRET},
            variable_names={
                "gemini": "GEMINI_API_KEY",
                "openrouter": "OPENROUTER_API_KEY",
                "nvidia-nim": "NVIDIA_API_KEY",
            },
            ambient=ambient,
            history=history,
        )
    )

    # The relay legitimately receives it; nothing downstream may.
    assert ambient.calls[0][1]["api_key"] == SECRET
    assert SECRET not in json.dumps(result)
    assert SECRET not in json.dumps(history.read())
    assert SECRET.encode() not in (tmp_path / "history.enc.jsonl").read_bytes()


# --------------------------------------------------------------------------
# Destructive actions need approval
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "instruction",
    [
        "deploy the release to production",
        "delete and rebuild the entire codebase",
        "commit and push everything",
        "install a new system package",
        "refactor the auth module",
    ],
)
def test_a_consequential_instruction_stops_at_approval(tmp_path, instruction):
    work = RefusingWork()

    result = asyncio.run(handle_instruction(instruction, workspace=tmp_path, work=work))

    assert result["status"] == "approval"
    assert result["text"] == ""
    assert work.calls == []


def test_an_unknown_permission_mode_is_refused_and_never_forwarded(tmp_path):
    """A silently ignored posture reads to the operator as applied.

    The mapping is a two-branch `if`, so anything that is not "always" lands on
    the permissive-by-default branch.  A future stricter mode ("readonly",
    "never") would therefore *loosen* the posture instead of tightening it.
    """
    captured = []

    def factory(_session, **kwargs):
        captured.append(kwargs["permission_mode"])
        return CapturingTransport(**kwargs)

    relay = WorkRelay(transport_factory=factory)

    with pytest.raises(ValueError, match="permission mode"):
        asyncio.run(
            relay.send(
                "do the thing",
                provider="claude",
                workspace=tmp_path,
                permission_mode="readonly",
            )
        )
    assert captured == []


@pytest.mark.parametrize(
    ("mode", "posture"),
    [("ask", "acceptEdits"), ("always", "bypassPermissions")],
)
def test_the_permission_posture_mapping_is_pinned(tmp_path, mode, posture):
    captured = []

    def factory(_session, **kwargs):
        captured.append(kwargs["permission_mode"])
        return CapturingTransport(**kwargs)

    relay = WorkRelay(transport_factory=factory)
    asyncio.run(
        relay.send("do the thing", provider="claude", workspace=tmp_path, permission_mode=mode)
    )

    assert captured == [posture]
