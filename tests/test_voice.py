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
from sleipnir.voice.listener import VoiceSegmenter, WakeCommandDetector
from sleipnir.voice.local_agent import LocalDesktopAgent
from sleipnir.voice.transcription import GeminiTranscriber, MAX_AUDIO_BYTES, resolve_whisper_model
from sleipnir.voice.synthesis import browser_audio
from sleipnir.voice.providers import AudioPayload


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


def test_wake_listener_releases_only_the_command_after_the_local_phrase():
    detector = WakeCommandDetector(VoiceConfig(wake_name="JARVIS"))

    assert detector.feed("A private conversation before activation") is None
    assert detector.feed("Hey, JARVIS, what is on my screen?") == "what is on my screen"
    assert detector.runtime.phase == "armed"
    assert detector.feed("Hey JARVIS") is None
    assert detector.runtime.phase == "hearing"
    assert detector.feed("ask Claude to diagnose the current error") == (
        "ask Claude to diagnose the current error"
    )
    assert detector.runtime.phase == "armed"


def test_listener_segments_speech_and_never_transcribes_quiet_chunks():
    segmenter = VoiceSegmenter(
        frame_seconds=0.1,
        minimum_rms=200,
        silence_seconds=0.3,
        minimum_seconds=0.2,
        pre_roll_seconds=0.1,
    )
    quiet = (0).to_bytes(2, "little", signed=True) * 1600
    voice = (2000).to_bytes(2, "little", signed=True) * 1600

    assert all(segmenter.feed(quiet) is None for _ in range(20))
    assert segmenter.feed(voice) is None
    assert segmenter.feed(voice) is None
    assert segmenter.feed(quiet) is None
    assert segmenter.feed(quiet) is None
    utterance = segmenter.feed(quiet)

    assert utterance is not None
    assert voice in utterance


def test_local_agent_sends_live_vision_and_continues_after_a_tool_call(tmp_path):
    requests = []

    class Observer:
        calls = 0

        async def capture(self):
            self.calls += 1
            return b"png-frame"

    async def run_tool(name, arguments):
        assert name == "computer_scroll"
        assert arguments == {"amount": -3}
        return "scrolled focused window"

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            return httpx.Response(200, json={"message": {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "computer_scroll", "arguments": {"amount": -3}}}]}})
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "The requested section is visible now."}})

    reply = asyncio.run(
        LocalDesktopAgent(
            transport=httpx.MockTransport(handler),
            observer=Observer(),
            tool_runner=run_tool,
        ).respond("Find the error on screen", model="jarvis", workspace=tmp_path, permission_mode="always")
    )

    assert reply.text == "The requested section is visible now."
    assert reply.steps == 2
    assert requests[0]["messages"][1]["images"]
    assert any(message.get("role") == "tool" for message in requests[1]["messages"])
    assert sum(1 for message in requests[1]["messages"] if message.get("images")) == 1

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


def test_gemini_transcription_keeps_key_out_of_audio_payload():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = request.headers
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "continue the build"}]}}]},
        )

    transcriber = GeminiTranscriber(
        api_key="private-gemini-key",
        transport=httpx.MockTransport(handler),
    )
    text = asyncio.run(transcriber.transcribe(b"webm-audio", mime_type="audio/webm"))

    assert text == "continue the build"
    assert captured["headers"]["x-goog-api-key"] == "private-gemini-key"
    assert "private-gemini-key" not in json.dumps(captured["body"])
    assert captured["body"]["contents"][0]["parts"][1]["inline_data"]["mime_type"] == "audio/webm"


def test_transcription_rejects_oversized_audio_before_network():
    transcriber = GeminiTranscriber(api_key="unused")

    try:
        asyncio.run(transcriber.transcribe(b"x" * (MAX_AUDIO_BYTES + 1), mime_type="audio/wav"))
    except RuntimeError as error:
        assert "12 MiB" in str(error)
    else:
        raise AssertionError("oversized recording was accepted")


def test_local_whisper_model_is_discovered_for_desktop_autostart(tmp_path):
    model = tmp_path / ".local" / "share" / "whisper-models" / "ggml-base.en.bin"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"model")

    assert resolve_whisper_model({}, home=tmp_path) == model


def test_raw_gemini_speech_is_wrapped_as_browser_playable_wav():
    payload = browser_audio(AudioPayload(b"\x00\x00\x01\x00", "audio/L16;rate=24000", "gemini"))

    assert payload.mime_type == "audio/wav"
    assert payload.data.startswith(b"RIFF")
    assert b"WAVE" in payload.data[:16]


def test_system_speech_commands_never_use_a_shell():
    assert system_tts_command("linux", "Hello", preset="british-calm", executable="spd-say")[:2] == ["spd-say", "-l"]
    assert system_tts_command("linux", "Hello", preset="british-calm", executable="espeak-ng")[-1] == "--stdin"
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


def test_ambient_relay_supports_local_ollama_without_an_api_key():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "Local answer"}}]})

    relay = AmbientRelay(transport=httpx.MockTransport(handler))
    reply = asyncio.run(
        relay.respond(
            "Explain inertia.",
            provider="ollama",
            api_key="",
            model="qwen3.5:4b",
        )
    )

    assert reply.text == "Local answer"
    assert reply.provider == "ollama"
    assert captured["url"] == "http://127.0.0.1:11434/v1/chat/completions"
    assert captured["authorization"] is None
    assert captured["body"]["model"] == "qwen3.5:4b"
    assert captured["body"]["reasoning_effort"] == "none"


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


def test_stop_does_nothing_before_anything_has_been_spoken():
    from sleipnir.voice.providers import SystemSpeech

    assert asyncio.run(SystemSpeech().stop()) is False


def test_stop_cancels_the_daemon_without_killing_the_client(monkeypatch):
    """speech-dispatcher renders in a daemon, so the cancel is the whole fix.

    Killing the `spd-say` client silences nothing on its own -- it queues and
    exits in ~0.19 s for a four-second sentence.  Measured on an isolated null
    sink, `--cancel` alone stops the audio 0.13 s later, and killing the client
    as well changes nothing except to make `speak` raise on returncode -9 for
    what was an ordinary interruption.
    """
    from sleipnir.voice.providers import SystemSpeech

    spawned: list[tuple[str, ...]] = []

    class FakeProcess:
        returncode = None

        def __init__(self):
            self.killed = False

        def kill(self):
            self.killed = True

        async def wait(self):
            return 0

    async def fake_exec(*argv, **_kwargs):
        spawned.append(argv)
        process = FakeProcess()
        process.returncode = 0
        return process

    speech = SystemSpeech()
    client = FakeProcess()
    speech._process = client
    speech._executable = "/usr/bin/spd-say"
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    assert asyncio.run(speech.stop()) is True
    assert spawned == [("/usr/bin/spd-say", "--cancel")]
    # An interruption is not a failure, so the client is left to exit cleanly.
    assert client.killed is False
