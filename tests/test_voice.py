"""The ambient voice boundary is local until an activated utterance is routed."""

from __future__ import annotations

import base64
import asyncio
import json

import httpx
from sleipnir.voice.config import VoiceConfig
from sleipnir.voice.providers import GeminiSpeech, OpenRouterSpeech, system_tts_command
from sleipnir.chat import ChatEvent
from sleipnir.voice.relay import AmbientRelay, WorkRelay
from sleipnir.voice.routing import RouteMode, choose_ambient_provider, route_utterance
from sleipnir.voice.runtime import VoiceRuntime


def test_configurable_wake_phrase_is_detected_without_network():
    called = []
    runtime = VoiceRuntime(VoiceConfig(wake_name="Friday"), network_hook=called.append)

    assert runtime.phase == "armed"
    assert runtime.feed_local_transcript("Hey Friday, continue the app") is True
    assert runtime.phase == "hearing"
    assert called == []


def test_complex_work_prompts_for_escalation_unless_operator_forces_it():
    suggested = route_utterance("Build the full-stack settings page and run its tests")
    forced = route_utterance("Build the settings page", force=RouteMode.HIGH)

    assert suggested.mode is RouteMode.CONFIRM_ESCALATION
    assert suggested.target in {"claude", "codex"}
    assert forced.mode is RouteMode.HIGH
    assert forced.requires_confirmation is False


def test_free_ambient_provider_is_preferred_when_gemini_is_activated():
    assert choose_ambient_provider({"GEMINI_API_KEY": "set", "OPENROUTER_API_KEY": "set"}) == "gemini"
    assert choose_ambient_provider({"OPENROUTER_API_KEY": "set"}) == "openrouter"
    assert choose_ambient_provider({}) is None


def test_openrouter_speech_uses_key_in_header_not_payload():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, content=b"audio", headers={"content-type": "audio/mpeg"})

    speech = OpenRouterSpeech(
        api_key="private-key",
        model="vendor/speech-model",
        transport=httpx.MockTransport(handler),
    )
    result = asyncio.run(speech.synthesize("Done.", voice="british-calm"))

    assert captured["authorization"] == "Bearer private-key"
    assert "private-key" not in json.dumps(captured["body"])
    assert result.data == b"audio"


def test_gemini_speech_decodes_inline_audio():
    encoded = base64.b64encode(b"wav-bytes").decode()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-goog-api-key"] == "gemini-key"
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"inlineData": {"mimeType": "audio/L16;rate=24000", "data": encoded}}]}}
                ]
            },
        )

    speech = GeminiSpeech(api_key="gemini-key", transport=httpx.MockTransport(handler))
    result = asyncio.run(speech.synthesize("Ready.", voice="american-warm"))

    assert result.data == b"wav-bytes"
    assert result.mime_type.startswith("audio/L16")


def test_system_speech_commands_never_use_a_shell():
    assert system_tts_command("linux", "Hello", preset="british-calm", executable="spd-say")[:2] == ["spd-say", "-l"]
    assert system_tts_command("darwin", "Hello", preset="system-natural", executable="say")[-1] == "-"
    windows = system_tts_command("windows", "Hello", preset="system-natural", executable="powershell")
    assert windows[0] == "powershell"
    assert "Hello" not in windows[-1]


def test_ambient_relay_supports_gemini_openrouter_and_nvidia_without_key_payloads():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if "generativelanguage" in str(request.url):
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "Gemini reply"}]}}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": "OpenAI-shaped reply"}}]})

    relay = AmbientRelay(transport=httpx.MockTransport(handler))
    gemini = asyncio.run(relay.respond("Status?", provider="gemini", api_key="g-secret"))
    openrouter = asyncio.run(relay.respond("Status?", provider="openrouter", api_key="o-secret"))
    nvidia = asyncio.run(relay.respond("Status?", provider="nvidia-nim", api_key="n-secret"))

    assert [gemini.text, openrouter.text, nvidia.text] == ["Gemini reply", "OpenAI-shaped reply", "OpenAI-shaped reply"]
    for request in requests:
        assert not any(secret.encode() in request.content for secret in ("g-secret", "o-secret", "n-secret"))


def test_work_relay_maps_operator_policy_and_reuses_provider_session(tmp_path):
    built = []

    class Transport:
        async def turn(self, prompt):
            yield ChatEvent(kind="final", text=f"completed: {prompt}")

        async def close(self):
            return None

    def factory(session, **kwargs):
        built.append((session, kwargs))
        return Transport()

    relay = WorkRelay(transport_factory=factory)
    first = asyncio.run(relay.send("build it", provider="codex", workspace=tmp_path, permission_mode="ask"))
    second = asyncio.run(relay.send("test it", provider="codex", workspace=tmp_path, permission_mode="ask"))

    assert first.text == "completed: build it"
    assert second.session_id == first.session_id
    assert len(built) == 1
    assert built[0][1]["permission_mode"] == "acceptEdits"
    assert built[0][1]["add_dirs"] == (tmp_path.resolve(),)
