import asyncio
import io
import wave
from pathlib import Path

from sleipnir.voice import transcription


def recording(seconds):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(16000)
        target.writeframes(bytes(seconds * 32000))
    return buffer.getvalue()


def test_whisper_window_has_headroom_for_longer_speech_and_invalid_headers(tmp_path):
    path = tmp_path / "recording.wav"
    for seconds, expected in [(2, 512), (9, 768), (15, 1024), (30, 1500)]:
        path.write_bytes(recording(seconds))
        assert transcription.whisper_audio_context(path) == expected
    path.write_bytes(b"unsupported wave format")
    assert transcription.whisper_audio_context(path) == 0


def test_local_cli_receives_the_bounded_audio_window_and_returns_transcript(monkeypatch, tmp_path):
    commands = []

    class Process:
        returncode = 0

        async def communicate(self):
            return None, b""

    async def spawn(*arguments, **kwargs):
        commands.append(arguments)
        output = Path(arguments[arguments.index("-of") + 1])
        output.with_suffix(".txt").write_text("Say pineapple.")
        return Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    model = tmp_path / "model.bin"
    model.touch()
    engine = transcription.LocalWhisperTranscriber(executable="whisper-cli", model=model)
    text = asyncio.run(engine.transcribe(recording(2), mime_type="audio/wav"))
    assert text == "Say pineapple."
    assert commands[0][commands[0].index("-ac") + 1] == "512"
