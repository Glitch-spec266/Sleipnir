"""Speech provider adapters with explicit credential and payload boundaries."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


class VoiceProviderError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AudioPayload:
    data: bytes
    mime_type: str
    provider: str


PRESETS: dict[str, dict[str, str]] = {
    "system-natural": {"locale": "en", "gemini": "Kore", "openrouter": "alloy"},
    "american-warm": {"locale": "en-US", "gemini": "Aoede", "openrouter": "nova"},
    "british-calm": {"locale": "en-GB", "gemini": "Sulafat", "openrouter": "sage"},
    "australian-bright": {"locale": "en-AU", "gemini": "Leda", "openrouter": "shimmer"},
    "indian-clear": {"locale": "en-IN", "gemini": "Kore", "openrouter": "alloy"},
    "meme-dramatic": {"locale": "en", "gemini": "Charon", "openrouter": "onyx"},
    "meme-deadpan": {"locale": "en", "gemini": "Iapetus", "openrouter": "echo"},
}


def provider_voice(preset: str, provider: str) -> str:
    values = PRESETS.get(preset, PRESETS["system-natural"])
    return values.get(provider, values.get("locale", "en"))


def system_tts_command(
    system: str,
    text: str,
    *,
    preset: str,
    executable: str | None = None,
) -> list[str]:
    """Return argv only; ``text`` is deliberately sent over stdin by the caller."""
    del text
    family = system.lower()
    locale = provider_voice(preset, "locale")
    if family.startswith("linux"):
        if executable and os.path.basename(executable).startswith("espeak"):
            return [executable, "-v", locale, "--stdin"]
        return [executable or "spd-say", "-l", locale, "--pipe-mode"]
    if family in {"darwin", "macos"}:
        return [executable or "say", "-f", "-"]
    if family.startswith("win"):
        script = (
            "Add-Type -AssemblyName System.Speech;"
            "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
            "$s.Speak([Console]::In.ReadToEnd())"
        )
        return [executable or "powershell", "-NoProfile", "-NonInteractive", "-Command", script]
    raise VoiceProviderError(f"system speech is not supported on {system}")


_PIPER_INSTALL = Path(".local") / "opt" / "piper" / "piper" / "piper"
_PIPER_VOICES = "piper-voices"
_PIPER_DEFAULT_RATE = 22_050


@dataclass(frozen=True, slots=True)
class PiperVoice:
    """A local neural voice: the binary, one model, and the model's rate."""

    binary: Path
    model: Path
    sample_rate: int


def piper_setup(environment: dict[str, str] | None = None) -> PiperVoice | None:
    """Locate a local Piper install by path, never through an exported name.

    The binary is deliberately not resolved on ``PATH``: Arch's ``extra/piper``
    is an unrelated gaming-mouse configurator, and running it would fail in a
    way that reads like a broken voice model.  Discovery is by conventional
    path for the same reason the Whisper model is -- a desktop autostart
    process reads no shell profile.
    """
    env = os.environ if environment is None else environment
    home = Path(env.get("HOME", "~")).expanduser()
    override = env.get("SLEIPNIR_PIPER_BIN")
    binary = Path(override) if override else home / _PIPER_INSTALL
    if not binary.is_file():
        return None
    voice_override = env.get("SLEIPNIR_PIPER_VOICE")
    if voice_override:
        candidates = [Path(voice_override)]
    else:
        data_home = Path(env.get("XDG_DATA_HOME", home / ".local" / "share"))
        candidates = sorted((data_home / _PIPER_VOICES).glob("*.onnx"))
    model = next((candidate for candidate in candidates if candidate.is_file()), None)
    if model is None:
        return None
    sample_rate = _PIPER_DEFAULT_RATE
    try:
        config = json.loads(Path(f"{model}.json").read_text(encoding="utf-8"))
        sample_rate = int(config["audio"]["sample_rate"])
    except (OSError, ValueError, KeyError, TypeError):
        # A missing or malformed sidecar is not fatal; every shipped voice so
        # far renders at the default rate.
        pass
    return PiperVoice(binary=binary, model=model, sample_rate=sample_rate)


def piper_commands(voice: PiperVoice, *, player: str = "paplay") -> tuple[list[str], list[str]]:
    """Return the synthesiser and player argv; text goes over stdin."""
    return (
        [str(voice.binary), "--model", str(voice.model), "--output_raw"],
        [
            player,
            "--raw",
            "--format=s16le",
            f"--rate={voice.sample_rate}",
            "--channels=1",
        ],
    )


class SystemSpeech:
    """The native speech engine, and the one way to silence it again.

    ``speak`` and ``stop`` are a pair.  ``VoiceRuntime.interrupt`` only moves
    the state machine — it is deliberately free of I/O — so a caller handling an
    interruption must call both, or the operator gets a UI that says "hearing"
    while the machine talks over them.
    """

    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._synthesiser: asyncio.subprocess.Process | None = None
        self._executable: str | None = None

    async def _speak_piper(self, text: str, voice: PiperVoice) -> None:
        """Render with Piper and play the raw stream, as two joined processes.

        The pipe is built from real file descriptors rather than asyncio
        streams so the audio never passes through this process: a StreamReader
        cannot be handed to another child as stdin.
        """
        synthesise, play = piper_commands(voice)
        read_fd, write_fd = os.pipe()
        try:
            synthesiser = await asyncio.create_subprocess_exec(
                *synthesise,
                stdin=asyncio.subprocess.PIPE,
                stdout=write_fd,
                stderr=asyncio.subprocess.PIPE,
            )
        finally:
            os.close(write_fd)
        try:
            player = await asyncio.create_subprocess_exec(
                *play,
                stdin=read_fd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
        finally:
            os.close(read_fd)
        self._process = player
        self._synthesiser = synthesiser
        self._executable = str(voice.binary)
        try:
            _, stderr = await synthesiser.communicate(text.encode("utf-8"))
            await player.wait()
        finally:
            self._process = None
            self._synthesiser = None
        # A negative return code is the operator interrupting, not a failure.
        if synthesiser.returncode and synthesiser.returncode > 0:
            raise VoiceProviderError(
                f"piper failed: {stderr.decode('utf-8', 'replace')[:240]}"
            )

    async def speak(self, text: str, *, preset: str = "system-natural") -> None:
        family = "windows" if sys.platform == "win32" else ("darwin" if sys.platform == "darwin" else "linux")
        if family == "linux":
            voice = piper_setup()
            if voice is not None and shutil.which("paplay"):
                await self._speak_piper(text, voice)
                return
        candidates = ["spd-say", "espeak-ng", "espeak"] if family == "linux" else (["powershell"] if family == "windows" else ["say"])
        executable = next((candidate for candidate in candidates if shutil.which(candidate)), None)
        if executable is None:
            raise VoiceProviderError("no system speech engine is installed")
        command = system_tts_command(family, text, preset=preset, executable=executable)
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        self._process = process
        self._executable = executable
        try:
            _, stderr = await process.communicate(text.encode("utf-8"))
        finally:
            self._process = None
        if process.returncode:
            raise VoiceProviderError(f"system speech failed: {stderr.decode('utf-8', 'replace')[:240]}")

    async def stop(self) -> bool:
        """Silence speech already in flight.  True if anything was stopped."""
        executable = self._executable
        if executable is None:
            return False
        if os.path.basename(executable).startswith("spd-say"):
            # speech-dispatcher renders in a daemon, so the client that queued
            # the text has usually already exited -- measured at 0.19 s for a
            # four-second sentence.  Killing it silences nothing; the daemon
            # needs an explicit cancel.
            canceller = await asyncio.create_subprocess_exec(
                executable,
                "--cancel",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await canceller.wait()
            # Do NOT also kill the client.  Measured on an isolated sink, the
            # cancel alone stops the audio in 0.13 s -- killing the client adds
            # nothing, and it makes `speak` raise VoiceProviderError on a
            # returncode of -9 for what was an ordinary operator interruption.
            return canceller.returncode == 0
        # espeak, `say` and the Piper pipeline all render in the processes
        # themselves, so killing them is the cancel.  Piper is two halves and
        # both must go: killing only the player leaves the synthesiser writing
        # into a closed pipe, and killing only the synthesiser leaves buffered
        # audio playing over the operator.
        stopped = False
        for process in (self._process, self._synthesiser):
            if process is None or process.returncode is not None:
                continue
            process.kill()
            stopped = True
        return stopped


class OpenRouterSpeech:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "openai/gpt-4o-mini-tts",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.transport = transport

    async def synthesize(self, text: str, *, voice: str) -> AudioPayload:
        key = self.api_key or os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise VoiceProviderError("OPENROUTER_API_KEY is not set")
        async with httpx.AsyncClient(transport=self.transport, timeout=60) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/audio/speech",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": self.model,
                    "input": text,
                    "voice": provider_voice(voice, "openrouter"),
                    "response_format": "mp3",
                },
            )
        if response.status_code != 200:
            raise VoiceProviderError(f"OpenRouter speech returned HTTP {response.status_code}")
        return AudioPayload(response.content, response.headers.get("content-type", "audio/mpeg"), "openrouter")


class GeminiSpeech:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "gemini-2.5-flash-preview-tts",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.transport = transport

    async def synthesize(self, text: str, *, voice: str) -> AudioPayload:
        key = self.api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise VoiceProviderError("GEMINI_API_KEY is not set")
        payload = {
            "contents": [{"parts": [{"text": text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {"voiceName": provider_voice(voice, "gemini")}
                    }
                },
            },
        }
        async with httpx.AsyncClient(transport=self.transport, timeout=60) as client:
            response = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
                headers={"x-goog-api-key": key},
                json=payload,
            )
        if response.status_code != 200:
            raise VoiceProviderError(f"Gemini speech returned HTTP {response.status_code}")
        try:
            inline: dict[str, Any] = response.json()["candidates"][0]["content"]["parts"][0]["inlineData"]
            data = base64.b64decode(inline["data"], validate=True)
            mime_type = str(inline["mimeType"])
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise VoiceProviderError("Gemini speech returned no audio") from error
        return AudioPayload(data, mime_type, "gemini")


__all__ = [
    "AudioPayload",
    "GeminiSpeech",
    "OpenRouterSpeech",
    "PRESETS",
    "SystemSpeech",
    "VoiceProviderError",
    "provider_voice",
    "system_tts_command",
]
