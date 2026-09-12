from __future__ import annotations

import asyncio
import io
import json
import subprocess
import sys

import pytest

from sleipnir.gui_history import EncryptedHistory
from sleipnir.voice import service
from sleipnir.voice.local_agent import LocalAgentReply
from sleipnir.voice.providers import AudioPayload


def test_resident_pipe_survives_bad_turns_and_keeps_replies_correlated(monkeypatch):
    agents = []

    async def dispatch(request, agent):
        agents.append(agent)
        print("provider diagnostic")
        if request["text"] == "fail":
            raise ValueError("turn failed")
        return {"status": "complete", "text": request["text"]}

    monkeypatch.setattr(service, "dispatch", dispatch)
    source = io.BytesIO(b'not json\n{"id":1,"text":"fail"}\n{"id":2,"text":"hello"}\n')
    target = io.StringIO()
    asyncio.run(service.serve(source, target))
    lines = [json.loads(line) for line in target.getvalue().splitlines()]
    assert lines[0] == {"type": "ready"}
    assert lines[1]["result"]["status"] == "error"
    assert lines[2] == {"id": 1, "result": {"status": "error", "text": "turn failed"}}
    assert lines[3] == {"id": 2, "result": {"status": "complete", "text": "hello"}}
    assert agents[0] is agents[1]
    assert "provider diagnostic" not in target.getvalue()


def test_agent_requests_preserve_encrypted_context_and_permission_boundary(tmp_path):
    calls = []

    class Agent:
        async def respond(self, text, **kwargs):
            calls.append((text, kwargs))
            return LocalAgentReply("Pineapple.", kwargs["model"], 1)

    history_path, key_path = tmp_path / "history.enc.jsonl", tmp_path / "history.key"
    arguments = [
        "--workspace", str(tmp_path), "--route", "ambient", "--ambient-provider", "ollama",
        "--history", str(history_path), "--history-key", str(key_path),
        "--operator-name", "Sam", "--permission-mode", "ask", "--task-grant",
    ]

    async def exchange():
        for identifier, text in enumerate(["say pineapple", "repeat that"], 1):
            result = await service.dispatch({"id": identifier, "entrypoint": "agent", "arguments": arguments, "text": text}, Agent())
            assert result["text"] == "Pineapple."

    asyncio.run(exchange())
    assert calls[0][1]["history"] == []
    assert [entry["text"] for entry in calls[1][1]["history"]] == ["say pineapple", "Pineapple."]
    assert calls[1][1]["permission_mode"] == "ask"
    assert calls[1][1]["task_grant"] is True
    assert calls[1][1]["operator_name"] == "Sam"
    assert "pineapple" not in history_path.read_text()
    assert len(EncryptedHistory(history_path, key_path).read()) == 4


def test_resident_speech_returns_browser_audio_without_protocol_noise(monkeypatch):
    async def synthesize(text, **kwargs):
        assert text == "Hello."
        return AudioPayload(b"audio", "audio/wav", kwargs["provider"])

    monkeypatch.setattr(service, "synthesize", synthesize)
    result = asyncio.run(service.dispatch({
        "entrypoint": "speak", "text": "Hello.",
        "arguments": ["--provider", "gemini", "--preset", "system-natural"],
    }, object()))
    assert result == {"status": "complete", "audio": {"data": "YXVkaW8=", "mimeType": "audio/wav"}}


def test_push_to_talk_audio_uses_resident_transcription_and_preserves_the_prompt(monkeypatch):
    async def transcribe(audio, **kwargs):
        assert audio == b"recording"
        assert kwargs["mime_type"] == "audio/webm"
        assert kwargs["prompt"] == "A conversation with JARVIS."
        return "Say pineapple."

    monkeypatch.setattr(service, "transcribe_audio", transcribe)
    result = asyncio.run(service.dispatch({
        "entrypoint": "transcribe", "text": "cmVjb3JkaW5n",
        "arguments": ["--mode", "local", "--mime-type", "audio/webm", "--prompt", "A conversation with JARVIS."],
    }, object()))
    assert result == {"status": "complete", "text": "Say pineapple."}


def test_invalid_and_oversized_audio_is_refused_before_transcription(monkeypatch):
    async def transcribe(*args, **kwargs):
        pytest.fail("invalid audio must not reach a provider")

    monkeypatch.setattr(service, "transcribe_audio", transcribe)
    request = {"entrypoint": "transcribe", "arguments": ["--mode", "local", "--mime-type", "audio/wav"]}
    for text in ("not valid base64!", "x" * (4 * ((service.MAX_AUDIO_BYTES + 2) // 3) + 1)):
        with pytest.raises(ValueError):
            asyncio.run(service.dispatch({**request, "text": text}, object()))


def test_oversized_pipe_request_is_refused_before_dispatch():
    with pytest.raises(ValueError, match="18 MiB"):
        asyncio.run(service.serve(io.BytesIO(b"x" * (service.MAX_REQUEST_BYTES + 1)), io.StringIO()))


def test_real_service_process_returns_clean_errors_then_exits_on_host_eof(tmp_path):
    requests = [
        {"id": 1, "entrypoint": "agent", "arguments": [], "text": "hello"},
        {"id": 2, "entrypoint": "unsupported", "text": "hello"},
    ]
    process = subprocess.run(
        [sys.executable, "-m", "sleipnir.voice.service"],
        input="".join(json.dumps(request) + "\n" for request in requests),
        capture_output=True, text=True, timeout=10,
    )
    assert process.returncode == 0
    lines = [json.loads(line) for line in process.stdout.splitlines()]
    assert lines[0] == {"type": "ready"}
    assert [line["id"] for line in lines[1:]] == [1, 2]
    assert all(line["result"]["status"] == "error" for line in lines[1:])
