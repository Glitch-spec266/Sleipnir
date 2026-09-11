"""The ambient voice boundary is local until an activated utterance is routed."""

from __future__ import annotations

import base64
import asyncio
import json
from pathlib import Path

import pytest
import httpx
from sleipnir.voice.config import VoiceConfig
from sleipnir.voice.providers import GeminiSpeech, OpenRouterSpeech, system_tts_command
from sleipnir.chat import ChatEvent
from sleipnir.voice.relay import AmbientRelay, WorkRelay
from sleipnir.voice.routing import (
    RouteMode,
    choose_ambient_provider,
    is_smalltalk,
    needs_reasoning,
    needs_screen,
    route_utterance,
)
from sleipnir.voice.runtime import VoiceRuntime
from sleipnir.voice.listener import (
    ARM_TIMEOUT_SECONDS,
    ListenerGate,
    VoiceSegmenter,
    WakeCommandDetector,
)
from sleipnir.voice.local_agent import (
    LocalCapabilityExceeded,
    LocalDesktopAgent,
    strip_thinking,
)
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


def _piper_tree(root):
    """Build a fake piper install: binary at the conventional path, one voice."""
    binary = root / ".local" / "opt" / "piper" / "piper" / "piper"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    voices = root / ".local" / "share" / "piper-voices"
    voices.mkdir(parents=True)
    model = voices / "en_GB-alan-medium.onnx"
    model.write_bytes(b"onnx")
    (voices / "en_GB-alan-medium.onnx.json").write_text(
        json.dumps({"audio": {"sample_rate": 22050}})
    )
    return binary, model


def test_piper_is_discovered_under_the_conventional_paths(tmp_path):
    """A desktop autostart process reads no shell profile, so discovery is by path."""
    from sleipnir.voice.providers import piper_setup

    binary, model = _piper_tree(tmp_path)
    setup = piper_setup({"HOME": str(tmp_path)})
    assert setup is not None
    assert setup.binary == binary
    assert setup.model == model
    assert setup.sample_rate == 22050


def test_piper_is_absent_without_a_voice_model(tmp_path):
    """The binary alone cannot speak, and a half-install must not win the race."""
    from sleipnir.voice.providers import piper_setup

    _piper_tree(tmp_path)
    (tmp_path / ".local" / "share" / "piper-voices" / "en_GB-alan-medium.onnx").unlink()
    assert piper_setup({"HOME": str(tmp_path)}) is None


def test_piper_is_never_taken_from_path(tmp_path, monkeypatch):
    """Arch ships an unrelated `piper` (a gaming-mouse tool) in `extra/`.

    Resolving the name on PATH would run that binary and fail confusingly, so
    the setup is only ever the conventional install directory or an explicit
    override.
    """
    from sleipnir.voice import providers

    monkeypatch.setattr(providers.shutil, "which", lambda _name: "/usr/bin/piper")
    assert providers.piper_setup({"HOME": str(tmp_path)}) is None


def test_piper_commands_carry_the_model_sample_rate(tmp_path):
    from sleipnir.voice.providers import piper_commands, piper_setup

    _piper_tree(tmp_path)
    setup = piper_setup({"HOME": str(tmp_path)})
    assert setup is not None
    synthesise, play = piper_commands(setup)
    assert synthesise[1:] == ["--model", str(setup.model), "--output_raw"]
    # A wrong rate here does not fail loudly; it plays the voice at the wrong
    # pitch, which reads as a broken model rather than a broken argument.
    assert play == ["paplay", "--raw", "--format=s16le", "--rate=22050", "--channels=1"]


def test_stop_kills_both_halves_of_the_piper_pipeline():
    """Piper renders in-process and paplay holds the audio, so both must die.

    Cancelling only the player leaves the synthesiser writing into a closed
    pipe, and cancelling only the synthesiser leaves already-buffered audio
    playing over the operator.
    """
    from sleipnir.voice.providers import SystemSpeech

    class FakeProcess:
        def __init__(self):
            self.returncode = None
            self.killed = False

        def kill(self):
            self.killed = True

    speech = SystemSpeech()
    player, synthesiser = FakeProcess(), FakeProcess()
    speech._process = player
    speech._synthesiser = synthesiser
    speech._executable = "/home/operator/.local/opt/piper/piper/piper"

    assert asyncio.run(speech.stop()) is True
    assert player.killed is True
    assert synthesiser.killed is True


def test_local_agent_always_confirms_even_when_the_model_says_nothing(tmp_path):
    """A silent success reads to the operator as a machine that ignored them."""
    from sleipnir.voice.local_agent import LocalDesktopAgent

    class Observer:
        async def capture(self):
            return b"png-frame"

    async def run_tool(name, arguments):
        return "typed into focused window"

    replies = [
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "computer_type", "arguments": {"text": "hi"}}}]},
        {"role": "assistant", "content": "   "},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": replies.pop(0)})

    reply = asyncio.run(
        LocalDesktopAgent(
            transport=httpx.MockTransport(handler), observer=Observer(), tool_runner=run_tool
        ).respond("type hi", model="jarvis", workspace=tmp_path, permission_mode="always")
    )
    assert reply.text
    assert "computer_type" in reply.text


def test_local_agent_writes_a_document_into_the_output_directory(tmp_path):
    from sleipnir.voice.local_agent import LocalToolbox

    toolbox = LocalToolbox(
        workspace=tmp_path, permission_mode="ask", original_prompt="make me a deck",
        output_root=tmp_path / "out",
    )
    result = json.loads(
        asyncio.run(toolbox.execute("write_file", {"path": "deck.html", "content": "<h1>Deck</h1>"}))
    )
    assert result["status"] == "written"
    assert (tmp_path / "out" / "deck.html").read_text() == "<h1>Deck</h1>"


def test_local_agent_cannot_write_outside_the_output_directory(tmp_path):
    """The path comes from model output, so containment is not optional."""
    from sleipnir.voice.local_agent import LocalToolbox

    toolbox = LocalToolbox(
        workspace=tmp_path, permission_mode="always", original_prompt="",
        output_root=tmp_path / "out",
    )
    with pytest.raises(ValueError):
        asyncio.run(toolbox.execute("write_file", {"path": "../../.ssh/authorized_keys", "content": "key"}))


def test_local_agent_will_not_silently_overwrite_without_approval(tmp_path):
    from sleipnir.voice.local_agent import LocalToolbox

    root = tmp_path / "out"
    root.mkdir()
    (root / "notes.md").write_text("the operator's work")
    toolbox = LocalToolbox(
        workspace=tmp_path, permission_mode="ask", original_prompt="", output_root=root
    )
    result = json.loads(
        asyncio.run(toolbox.execute("write_file", {"path": "notes.md", "content": "replaced"}))
    )
    assert result["status"] == "approval_required"
    assert (root / "notes.md").read_text() == "the operator's work"


def test_delegation_is_not_the_default_advice():
    """The local model is asked to solve the problem, not to hand it off."""
    from sleipnir.voice.local_agent import LOCAL_AGENT_SYSTEM

    assert "Prefer delegate_work" not in LOCAL_AGENT_SYSTEM
    assert "delegate_work" in LOCAL_AGENT_SYSTEM
    assert "yourself" in LOCAL_AGENT_SYSTEM


def test_a_promise_to_act_is_pushed_back_once(tmp_path):
    """Small models answer "I'll write that file" and then stop.

    Measured live on qwen3.5:4b: the first turn described the deliverable and
    emitted no tool call, so nothing was produced.  One deterministic nudge
    turns the promise into the action; it is sent at most once so a chatty
    model cannot loop.
    """
    from sleipnir.voice.local_agent import LocalDesktopAgent

    class Observer:
        async def capture(self):
            return b"png-frame"

    performed = []

    async def run_tool(name, arguments):
        performed.append(name)
        return json.dumps({"status": "written", "path": "/home/operator/Sleipnir/deck.html"})

    bodies = []
    replies = [
        {"role": "assistant", "content": "I'll create that presentation for you now."},
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "write_file", "arguments": {"path": "deck.html", "content": "<h1>x</h1>"}}}]},
        {"role": "assistant", "content": "Saved to ~/Sleipnir/deck.html."},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"message": replies.pop(0)})

    reply = asyncio.run(
        LocalDesktopAgent(
            transport=httpx.MockTransport(handler), observer=Observer(), tool_runner=run_tool
        ).respond("make me a deck", model="jarvis", workspace=tmp_path, permission_mode="always")
    )

    assert performed == ["write_file"]
    assert reply.text == "Saved to ~/Sleipnir/deck.html."
    nudges = [
        message
        for message in bodies[-1]["messages"]
        if message.get("role") == "user" and "without describing" in str(message.get("content", ""))
    ]
    assert len(nudges) == 1


def test_a_plain_answer_is_never_nudged(tmp_path):
    """A question that needs no tool must be answered in one turn."""
    from sleipnir.voice.local_agent import LocalDesktopAgent

    class Observer:
        async def capture(self):
            return b"png-frame"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "Photosynthesis converts light into sugar."}})

    reply = asyncio.run(
        LocalDesktopAgent(
            transport=httpx.MockTransport(handler), observer=Observer(), tool_runner=lambda *_a: None
        ).respond("what is photosynthesis", model="jarvis", workspace=tmp_path, permission_mode="ask")
    )
    assert reply.steps == 1


def test_a_clipping_microphone_is_reported_not_transcribed():
    """A mic at +60 dB over its base volume saturates, and Whisper returns "".

    Measured on this machine: input volume 100% against a 10% base gave a solid
    10 s of RMS 26,010 with the peak pinned at 32,768, and every segment
    transcribed to nothing.  The failure is silent and looks exactly like a
    machine that cannot hear, so the segment is reported rather than sent.
    """
    from sleipnir.voice.listener import clipping_fraction, is_clipping

    saturated = b"".join((32767).to_bytes(2, "little", signed=True) for _ in range(1600))
    speech = b"".join((3000).to_bytes(2, "little", signed=True) for _ in range(1600))
    assert clipping_fraction(saturated) == 1.0
    assert is_clipping(saturated) is True
    assert is_clipping(speech) is False


def test_one_sentence_split_into_two_segments_does_not_start_two_turns():
    """A >0.8s pause splits a sentence, and both halves reached the host.

    Nothing downstream deduplicates, so the operator heard two agents answer
    the same instruction at once.
    """
    detector = WakeCommandDetector(VoiceConfig(wake_name="JARVIS"))

    assert detector.feed("Hey JARVIS what is on my screen", now=0.0) == "what is on my screen"
    assert detector.feed("what is on my screen", now=0.4) is None
    # The same words much later are a genuine second request, not an echo.
    assert detector.feed("Hey JARVIS what is on my screen", now=60.0) == "what is on my screen"


def test_a_bare_wake_word_disarms_instead_of_capturing_the_next_utterance_forever():
    """``feed`` used to return None without completing the runtime.

    The phase stayed ``hearing`` indefinitely, so any later speech -- a remark
    to somebody else in the room -- was emitted verbatim as a command.
    """
    detector = WakeCommandDetector(VoiceConfig(wake_name="JARVIS"))

    assert detector.feed("Hey JARVIS", now=0.0) is None
    assert detector.runtime.phase == "hearing"
    assert detector.feed("open the browser", now=2.0) == "open the browser"

    assert detector.feed("Hey JARVIS", now=10.0) is None
    assert detector.feed("no I was talking to you", now=10.0 + ARM_TIMEOUT_SECONDS + 0.1) is None
    assert detector.runtime.phase == "armed"


def test_the_host_can_mute_the_listener_so_sleipnir_never_hears_its_own_voice():
    gate = ListenerGate()

    assert gate.muted is False
    assert gate.apply('{"type": "mute"}') is True
    assert gate.muted is True
    assert gate.apply('{"type": "unmute"}') is True
    assert gate.muted is False
    # A malformed or unknown control line must never take the listener down.
    assert gate.apply("not json at all") is False
    assert gate.apply('{"type": "detonate"}') is False
    assert gate.muted is False


def test_muting_discards_the_partial_utterance_instead_of_resuming_mid_word():
    segmenter = VoiceSegmenter(
        frame_seconds=0.1,
        minimum_rms=200,
        silence_seconds=0.3,
        minimum_seconds=0.2,
        pre_roll_seconds=0.1,
    )
    quiet = (0).to_bytes(2, "little", signed=True) * 1600
    voice = (2000).to_bytes(2, "little", signed=True) * 1600

    assert segmenter.feed(voice) is None
    assert segmenter.feed(voice) is None
    segmenter.reset()

    # Only silence remains buffered, so the resumed stream cannot emit the
    # half-utterance that was in flight when speech began.
    assert segmenter.feed(quiet) is None
    assert segmenter.feed(quiet) is None
    assert segmenter.feed(quiet) is None


def test_the_classifier_separates_smalltalk_from_screen_questions():
    assert is_smalltalk("what's up") is True
    assert is_smalltalk("Hey there") is True
    assert is_smalltalk("thanks") is True
    assert is_smalltalk("how are you doing") is True
    assert is_smalltalk("what is on my screen right now") is False
    assert is_smalltalk("derive the escape velocity of Earth") is False

    assert needs_screen("what is on my screen right now") is True
    assert needs_screen("read the question in this window") is True
    assert needs_screen("what am I looking at") is True
    assert needs_screen("what's up") is False
    assert needs_screen("what is the capital of France") is False


def test_reasoning_never_reaches_the_operator_s_speakers():
    """`think: false` is a request, not a guarantee.

    A qwen3-style model can still emit a literal <think> block inside the
    message content, and nothing stripped it -- so twenty seconds of the model
    deliberating about how to answer "what's up" was spoken aloud verbatim.
    """
    assert strip_thinking("<think>They said hi. I should greet them.</think>Morning.") == "Morning."
    assert strip_thinking("<think>unterminated reasoning that never closes") == ""
    assert strip_thinking("  plain answer  ") == "plain answer"
    assert strip_thinking("<think>a</think>one<think>b</think>two") == "one two"


def test_smalltalk_answers_in_one_call_with_no_tools_and_no_screenshot(tmp_path):
    requests: list[dict] = []

    class Observer:
        calls = 0

        async def capture(self) -> bytes:
            Observer.calls += 1
            return b"frame"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "All good, thanks."}})

    agent = LocalDesktopAgent(
        transport=httpx.MockTransport(handler),
        observer=Observer(),
        tool_runner=lambda name, arguments: {"status": "unexpected"},
    )
    reply = asyncio.run(agent.respond("what's up", workspace=tmp_path, model="jarvis", permission_mode="ask"))

    assert reply.text == "All good, thanks."
    assert len(requests) == 1
    assert "tools" not in requests[0]
    assert Observer.calls == 0
    assert all("images" not in message for message in requests[0]["messages"])


def test_a_question_that_is_not_about_the_screen_does_not_pay_for_a_frame(tmp_path):
    class Observer:
        calls = 0

        async def capture(self) -> bytes:
            Observer.calls += 1
            return b"frame"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "Paris."}})

    agent = LocalDesktopAgent(
        transport=httpx.MockTransport(handler),
        observer=Observer(),
        tool_runner=lambda name, arguments: {"status": "unexpected"},
    )
    reply = asyncio.run(agent.respond("what is the capital of France", workspace=tmp_path, model="jarvis", permission_mode="ask"))

    assert reply.text == "Paris."
    assert Observer.calls == 0


def test_multi_step_arithmetic_is_routed_to_the_reasoning_lane():
    """MEASURED: with ``think: false`` every candidate model got 17*24+139 wrong.

    jarvis answered 425, qwen3.5:9b answered 445; the correct 547 came back
    only once the model was allowed a scratchpad. Denying reasoning is what
    made the assistant bad at maths, so the classifier has to spot the shape.
    """
    assert needs_reasoning("what is 17 times 24 plus 139") is True
    assert needs_reasoning("how high does a ball thrown at 20 metres per second go") is True
    assert needs_reasoning("derive the escape velocity of Earth") is True
    assert needs_reasoning("calculate the compound interest on 5000 at 4 percent") is True
    assert needs_reasoning("what's up") is False
    assert needs_reasoning("what is on my screen") is False


def test_a_local_model_that_deliberates_without_converging_asks_to_be_replaced(tmp_path):
    """MEASURED: "17 times 24 plus 139" made the 4B deliberate for 121 s and the
    9B for 131 s, both answering nothing, and a retry at a larger token ceiling
    only bought a longer wait. Budget was never the problem, so exhaustion is
    reported as a capability limit the caller must delegate -- not retried.
    """
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={"message": {"role": "assistant", "content": "", "thinking": "round and round"}},
        )

    agent = LocalDesktopAgent(
        transport=httpx.MockTransport(handler),
        observer=None,
        tool_runner=lambda name, arguments: {"status": "unexpected"},
    )
    with pytest.raises(LocalCapabilityExceeded):
        asyncio.run(
            agent.respond(
                "what is 17 times 24 plus 139",
                workspace=tmp_path,
                model="jarvis",
                permission_mode="ask",
            )
        )

    # Exactly one attempt: a looping model is not owed a second, longer one.
    assert len(calls) == 1
    assert calls[0]["think"] is True


def test_a_model_that_stays_silent_without_thinking_still_answers_a_greeting(tmp_path):
    """MEASURED: qwen3-vl returns empty content whenever thinking is disabled.

    Every greeting fell through to the placeholder, so the operator got
    "I'm here." no matter what they said.
    """
    thinks: list[bool] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        thinks.append(body["think"])
        content = "Morning." if body["think"] else ""
        return httpx.Response(200, json={"message": {"role": "assistant", "content": content}})

    agent = LocalDesktopAgent(
        transport=httpx.MockTransport(handler),
        observer=None,
        tool_runner=lambda name, arguments: {"status": "unexpected"},
    )
    reply = asyncio.run(
        agent.respond("hey there", workspace=tmp_path, model="jarvis", permission_mode="ask")
    )

    assert reply.text == "Morning."
    assert thinks == [False, True]


def test_a_close_look_crops_before_downscaling_instead_of_shrinking_the_whole_screen(monkeypatch, tmp_path):
    """A 1920x1080 screen downscaled to 1280 leaves small text a guess.

    Cropping first means the region the operator asked about keeps its own
    pixels, which is the difference between reading a form question and
    inventing one.
    """
    import shutil as _shutil
    from sleipnir.capabilities import computer as _computer
    from sleipnir.voice import local_agent as module

    calls: list[list[str]] = []

    def fake_screenshot(path):
        Path(path).write_bytes(b"\x89PNG rawframe")
        return Path(path)

    class _Process:
        async def wait(self):
            return 0

    async def fake_exec(*argv, **kwargs):
        calls.append(list(argv))
        Path(argv[-1]).write_bytes(b"\xff\xd8jpeg")
        return _Process()

    monkeypatch.setattr(_computer, "screenshot", fake_screenshot)
    monkeypatch.setattr(module.computer, "screenshot", fake_screenshot)
    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/magick" if name == "magick" else None)
    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", fake_exec)

    observer = module.ScreenObserver()
    assert asyncio.run(observer.capture()) == b"\xff\xd8jpeg"
    assert "-crop" not in calls[0]

    calls.clear()
    assert asyncio.run(observer.capture(region=(100, 200, 640, 360))) == b"\xff\xd8jpeg"
    argv = calls[0]
    assert "-crop" in argv
    assert "640x360+100+200" in argv
    # A cropped region is small enough to keep at full fidelity.
    assert argv[argv.index("-quality") + 1] == "90"


def test_a_region_must_have_a_positive_size():
    from sleipnir.voice import local_agent as module

    with pytest.raises(ValueError, match="region"):
        asyncio.run(module.ScreenObserver().capture(region=(0, 0, 0, 100)))


def test_a_blocked_action_asks_once_for_the_whole_task_not_once_per_click(tmp_path):
    """In `ask` mode every click returned approval_required and did nothing.

    Answering a five-question form needs a dozen consequential actions, so
    per-action refusal made the task unreachable by construction rather than
    merely guarded.
    """
    from sleipnir.voice.local_agent import LocalToolbox

    toolbox = LocalToolbox(
        workspace=tmp_path, permission_mode="ask", original_prompt="fill in the form"
    )
    blocked = asyncio.run(toolbox.execute("computer_click", {"x": 1, "y": 2}))
    assert json.loads(blocked)["status"] == "approval_required"
    assert toolbox.blocked == ["computer_click"]

    granted = LocalToolbox(
        workspace=tmp_path,
        permission_mode="ask",
        original_prompt="fill in the form",
        task_grant=True,
    )
    # The grant covers the task, so the gate stops answering for every action.
    assert granted._approval("computer_click") is None
    # It never reaches credentials: those stay behind the operator prompt.
    assert granted.permission_mode == "ask"


def test_the_reply_carries_what_it_needs_permission_for(tmp_path):
    """The operator has to be told what they are approving, in one sentence."""
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if len(body["messages"]) <= 2:
            return httpx.Response(200, json={"message": {
                "role": "assistant",
                "tool_calls": [{"function": {"name": "computer_click", "arguments": {"x": 1, "y": 2}}}],
            }})
        return httpx.Response(200, json={"message": {
            "role": "assistant", "content": "I need to click the answer to continue."
        }})

    class Observer:
        async def capture(self, *, region=None) -> bytes:
            return b"frame"

    agent = LocalDesktopAgent(transport=httpx.MockTransport(handler), observer=Observer())
    reply = asyncio.run(
        agent.respond(
            "answer the question on my screen",
            workspace=tmp_path,
            model="jarvis",
            permission_mode="ask",
        )
    )

    assert reply.approval == "computer_click"
    assert reply.text


def test_ordinary_conversation_stays_off_the_tool_loop():
    """A remark is not an instruction, and the tool loop is the wrong shape for it.

    Reproduced live on 2026-09-10: "I'm pretty tired today" entered the
    twelve-step loop, took a screenshot and began narrating an unrelated web
    page.  The cause was that conversation was a *whitelist* of greetings and
    everything else fell through to the tool lane by default.  Tools are now
    entered on evidence of an actual request, never by exhaustion.
    """
    from sleipnir.voice.routing import needs_tools

    for remark in (
        "I'm pretty tired today",
        "how's your day going",
        "what do you think about the weather",
        "tell me a joke",
        "do you like music",
        "who was Ada Lovelace",
        "that was a rough meeting",
    ):
        assert needs_tools(remark) is False, remark

    for instruction in (
        "what is on my screen right now",
        "open the sleipnir repository and fix the router",
        "click the submit button",
        "search for flights to Tokyo",
        "write me a presentation about photosynthesis",
        "scroll down a bit",
    ):
        assert needs_tools(instruction) is True, instruction


def test_the_conversation_lane_sees_the_recent_turns(tmp_path):
    """Without prior turns the assistant cannot answer a follow-up at all.

    ``gui_agent`` already wrote every turn to the encrypted history and then
    passed none of it back, so "and you?" reached the model as a standalone
    sentence with no referent.
    """
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "Not bad at all."}})

    agent = LocalDesktopAgent(
        transport=httpx.MockTransport(handler),
        tool_runner=lambda name, arguments: {"status": "unexpected"},
    )
    reply = asyncio.run(
        agent.respond(
            "and you?",
            workspace=tmp_path,
            model="jarvis",
            permission_mode="ask",
            history=[
                {"role": "operator", "text": "how are you"},
                {"role": "sleipnir", "text": "Good thanks."},
            ],
        )
    )

    assert reply.text == "Not bad at all."
    assert len(requests) == 1
    spoken = [message["content"] for message in requests[0]["messages"]]
    assert "how are you" in spoken
    assert "Good thanks." in spoken
    assert spoken[-1] == "and you?"


def test_the_listener_keeps_the_local_model_resident():
    """MEASURED 2026-09-10: a cold ``jarvis`` turn costs 4.99 s, a warm one 0.20 s.

    ``keep_alive`` alone does not help an assistant that is spoken to less
    often than its own unload timer, which is the ordinary case -- every first
    question of the morning paid a five second model load. The preload request
    carries no prompt, so keeping it resident costs one HTTP call per interval
    and no tokens at all.
    """
    from sleipnir.voice.listener import keep_model_warm

    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"done": True})

    asyncio.run(
        keep_model_warm(
            "jarvis", interval=0, transport=httpx.MockTransport(handler), iterations=2
        )
    )

    assert len(calls) == 2
    assert calls[0]["model"] == "jarvis"
    assert "prompt" not in calls[0] or calls[0]["prompt"] == ""
    assert calls[0]["keep_alive"] != "0"


def test_keeping_the_model_warm_never_takes_the_listener_down():
    """A dead Ollama must cost the wake loop nothing; warmth is an optimisation."""
    from sleipnir.voice.listener import keep_model_warm

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    asyncio.run(
        keep_model_warm(
            "jarvis", interval=0, transport=httpx.MockTransport(handler), iterations=2
        )
    )
