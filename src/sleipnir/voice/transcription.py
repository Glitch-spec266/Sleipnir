"""Speech-to-text adapters for the activated desktop voice boundary."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import httpx

from sleipnir.voice.providers import VoiceProviderError

MAX_AUDIO_BYTES = 12 * 1024 * 1024


def _audio_suffix(mime_type: str) -> str:
    family = mime_type.casefold().split(";", 1)[0].strip()
    return {
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/webm": ".webm",
        "audio/ogg": ".ogg",
        "audio/mpeg": ".mp3",
        "audio/mp4": ".m4a",
    }.get(family, ".audio")


class GeminiTranscriber:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "gemini-2.5-flash-lite",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.transport = transport

    async def transcribe(self, audio: bytes, *, mime_type: str) -> str:
        if not audio:
            raise VoiceProviderError("recording is empty")
        if len(audio) > MAX_AUDIO_BYTES:
            raise VoiceProviderError("recording exceeds the 12 MiB safety limit")
        key = self.api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise VoiceProviderError("GEMINI_API_KEY is not set")
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": (
                                "Transcribe this command exactly. Return only the transcript, "
                                "without commentary, quotation marks, or markdown."
                            )
                        },
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": base64.b64encode(audio).decode("ascii"),
                            }
                        },
                    ]
                }
            ]
        }
        async with httpx.AsyncClient(transport=self.transport, timeout=90) as client:
            response = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
                headers={"x-goog-api-key": key},
                json=payload,
            )
        if response.status_code != 200:
            raise VoiceProviderError(f"Gemini transcription returned HTTP {response.status_code}")
        try:
            text = str(response.json()["candidates"][0]["content"]["parts"][0]["text"]).strip()
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise VoiceProviderError("Gemini transcription returned no text") from error
        if not text:
            raise VoiceProviderError("Gemini transcription returned an empty command")
        return text


class LocalWhisperTranscriber:
    """Use an operator-installed whisper.cpp model without a network request."""

    def __init__(
        self,
        *,
        executable: str | None = None,
        model: Path | None = None,
        ffmpeg: str | None = None,
    ) -> None:
        self.executable = executable
        self.model = model
        self.ffmpeg = ffmpeg

    async def transcribe(self, audio: bytes, *, mime_type: str) -> str:
        if not audio:
            raise VoiceProviderError("recording is empty")
        if len(audio) > MAX_AUDIO_BYTES:
            raise VoiceProviderError("recording exceeds the 12 MiB safety limit")
        executable = self.executable or shutil.which("whisper-cli") or shutil.which("whisper-cpp")
        model = self.model or (
            Path(value) if (value := os.environ.get("SLEIPNIR_WHISPER_MODEL")) else None
        )
        if executable is None or model is None or not model.is_file():
            raise VoiceProviderError(
                "local transcription needs whisper-cli and SLEIPNIR_WHISPER_MODEL"
            )

        with tempfile.TemporaryDirectory(prefix="sleipnir-voice-") as temporary:
            root = Path(temporary)
            source = root / f"recording{_audio_suffix(mime_type)}"
            source.write_bytes(audio)
            wave = source
            if source.suffix != ".wav":
                ffmpeg = self.ffmpeg or shutil.which("ffmpeg")
                if ffmpeg is None:
                    raise VoiceProviderError("ffmpeg is required for this local recording format")
                wave = root / "recording.wav"
                await _run_checked(
                    [
                        ffmpeg,
                        "-nostdin",
                        "-loglevel",
                        "error",
                        "-i",
                        str(source),
                        "-ar",
                        "16000",
                        "-ac",
                        "1",
                        str(wave),
                    ],
                    "convert recording",
                )
            output = root / "transcript"
            await _run_checked(
                [executable, "-m", str(model), "-f", str(wave), "-otxt", "-of", str(output)],
                "transcribe recording",
            )
            transcript = output.with_suffix(".txt")
            if not transcript.is_file():
                raise VoiceProviderError("local transcription produced no transcript")
            text = transcript.read_text(encoding="utf-8").strip()
            if not text:
                raise VoiceProviderError("local transcription produced an empty command")
            return text


async def _run_checked(command: list[str], action: str) -> None:
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=180)
    except TimeoutError as error:
        process.kill()
        await process.wait()
        raise VoiceProviderError(f"{action} timed out") from error
    if process.returncode:
        detail = stderr.decode("utf-8", "replace").strip()[:240]
        raise VoiceProviderError(f"{action} failed{f': {detail}' if detail else ''}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sleipnir-desktop-transcribe")
    parser.add_argument("--mode", choices=["local", "gemini"], required=True)
    parser.add_argument("--mime-type", required=True)
    parser.add_argument("--gemini-env", default="GEMINI_API_KEY")
    parser.add_argument("--model")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    audio = sys.stdin.buffer.read(MAX_AUDIO_BYTES + 1)
    if len(audio) > MAX_AUDIO_BYTES:
        print(json.dumps({"status": "error", "text": "recording exceeds 12 MiB"}))
        return 2
    try:
        if args.mode == "gemini":
            key = os.environ.get(args.gemini_env)
            transcriber = GeminiTranscriber(api_key=key, model=args.model or "gemini-2.5-flash-lite")
        else:
            transcriber = LocalWhisperTranscriber()
        text = asyncio.run(transcriber.transcribe(audio, mime_type=args.mime_type))
    except Exception as error:  # noqa: BLE001 - native boundary returns a clean envelope
        print(json.dumps({"status": "error", "text": str(error)}))
        return 2
    print(json.dumps({"status": "complete", "text": text}, separators=(",", ":")))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["GeminiTranscriber", "LocalWhisperTranscriber", "MAX_AUDIO_BYTES", "main"]
