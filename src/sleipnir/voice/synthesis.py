"""Native speech-output boundary for the desktop voice surface."""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import os
import re
import sys
import wave

from sleipnir.voice.providers import (
    AudioPayload,
    GeminiSpeech,
    OpenRouterSpeech,
    SystemSpeech,
)

MAX_SPEECH_BYTES = 64 * 1024


def browser_audio(payload: AudioPayload) -> AudioPayload:
    """Wrap Gemini's raw 16-bit PCM so desktop webviews can play it."""
    if not payload.mime_type.casefold().startswith("audio/l16"):
        return payload
    match = re.search(r"rate=(\d+)", payload.mime_type, re.IGNORECASE)
    rate = int(match.group(1)) if match else 24_000
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(rate)
        target.writeframes(payload.data)
    return AudioPayload(buffer.getvalue(), "audio/wav", payload.provider)


async def synthesize(
    text: str,
    *,
    provider: str,
    preset: str,
    openrouter_key: str | None = None,
    gemini_key: str | None = None,
) -> AudioPayload | None:
    clean = text.strip()
    if not clean:
        raise ValueError("speech text cannot be empty")
    if len(clean.encode("utf-8")) > MAX_SPEECH_BYTES:
        raise ValueError("speech text exceeds the 64 KiB safety limit")
    if provider == "system":
        await SystemSpeech().speak(clean, preset=preset)
        return None
    if provider == "gemini":
        return browser_audio(
            await GeminiSpeech(api_key=gemini_key).synthesize(clean, voice=preset)
        )
    if provider == "openrouter":
        return await OpenRouterSpeech(api_key=openrouter_key).synthesize(clean, voice=preset)
    raise ValueError(f"voice provider {provider!r} is not available")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sleipnir-desktop-speak")
    parser.add_argument("--provider", choices=["system", "gemini", "openrouter"], required=True)
    parser.add_argument("--preset", required=True)
    parser.add_argument("--openrouter-env", default="OPENROUTER_API_KEY")
    parser.add_argument("--gemini-env", default="GEMINI_API_KEY")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    raw = sys.stdin.buffer.read(MAX_SPEECH_BYTES + 1)
    if len(raw) > MAX_SPEECH_BYTES:
        print(json.dumps({"status": "error", "text": "speech text exceeds 64 KiB"}))
        return 2
    try:
        payload = asyncio.run(
            synthesize(
                raw.decode("utf-8"),
                provider=args.provider,
                preset=args.preset,
                openrouter_key=os.environ.get(args.openrouter_env),
                gemini_key=os.environ.get(args.gemini_env),
            )
        )
    except Exception as error:  # noqa: BLE001 - native boundary returns a clean envelope
        print(json.dumps({"status": "error", "text": str(error)}))
        return 2
    print(
        json.dumps(
            {
                "status": "complete",
                "audio": (
                    {
                        "data": base64.b64encode(payload.data).decode("ascii"),
                        "mimeType": payload.mime_type,
                    }
                    if payload
                    else None
                ),
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["MAX_SPEECH_BYTES", "browser_audio", "main", "synthesize"]
