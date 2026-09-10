"""Long-lived, local-only wake listener for the native desktop host.

Audio stays in this process until the configured wake phrase is recognized.
Only the post-wake command is written to stdout for the Tauri host; pre-wake
transcripts are deliberately never emitted or logged.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import math
import os
import re
import shutil
import signal
import sys
import wave
from array import array
from collections import deque
from dataclasses import dataclass, field

from sleipnir.voice.config import VoiceConfig
from sleipnir.voice.runtime import VoiceRuntime, _words
from sleipnir.voice.transcription import LocalWhisperTranscriber

_RATE = 16_000
_CHANNELS = 1
_SAMPLE_WIDTH = 2


def _emit(payload: dict[str, str]) -> None:
    """Write one event to the host, and mirror it when diagnostics are on.

    The mirror carries exactly what the host is told and nothing more: a
    pre-wake transcript never becomes an event, so it can never become a log
    line either.
    """
    line = json.dumps(payload)
    print(line, flush=True)
    destination = os.environ.get("SLEIPNIR_VOICE_LOG")
    if not destination:
        return
    try:
        with open(destination, "a", encoding="utf-8") as handle:
            handle.write(f"{line}\n")
    except OSError:
        # Diagnostics must never take the listener down.
        pass


def _wake_span(transcript: str, wake_name: str) -> tuple[int, int] | None:
    """Return the character span of ``hey <wake name>`` in normalized prose."""
    phrase = r"\bhey[\s,.:;!?-]+" + r"[\s,.:;!?-]+".join(
        re.escape(word) for word in _words(wake_name)
    ) + r"\b"
    match = re.search(phrase, transcript, re.IGNORECASE)
    return match.span() if match else None


@dataclass(slots=True)
class WakeCommandDetector:
    """Privacy-preserving transcript gate around :class:`VoiceRuntime`."""

    config: VoiceConfig
    runtime: VoiceRuntime = field(init=False)

    def __post_init__(self) -> None:
        self.runtime = VoiceRuntime(self.config)

    def feed(self, transcript: str) -> str | None:
        clean = transcript.strip().strip(" .,!?:;-\t\n")
        if not clean:
            return None
        if self.runtime.phase == "hearing":
            self.runtime.submit_utterance(clean, remote=False)
            command = self.runtime.heard
            self.runtime.complete()
            return command
        span = _wake_span(clean, self.config.wake_name)
        if span is None or not self.runtime.feed_local_transcript(clean):
            return None
        command = clean[span[1] :].strip(" .,!?:;-\t\n")
        if not command:
            return None
        self.runtime.submit_utterance(command, remote=False)
        self.runtime.complete()
        return command


def _rms(pcm: bytes) -> float:
    if len(pcm) < 2:
        return 0.0
    samples = array("h")
    samples.frombytes(pcm[: len(pcm) - len(pcm) % 2])
    if sys.byteorder != "little":
        samples.byteswap()
    return math.sqrt(sum(sample * sample for sample in samples) / max(1, len(samples)))


def _has_voice(pcm: bytes, *, minimum_rms: int = 220) -> bool:
    return _rms(pcm) >= minimum_rms


CLIPPING_THRESHOLD = 32_000
MAX_CLIPPED_FRACTION = 0.02


def clipping_fraction(pcm: bytes) -> float:
    """Share of samples pinned at the top of the 16-bit range."""
    samples = array("h")
    samples.frombytes(pcm[: len(pcm) - len(pcm) % 2])
    if sys.byteorder != "little":
        samples.byteswap()
    if not samples:
        return 0.0
    return sum(1 for sample in samples if abs(sample) >= CLIPPING_THRESHOLD) / len(samples)


def is_clipping(pcm: bytes) -> bool:
    """True when the input is saturated rather than loud.

    An input volume far above the device's base volume amplifies into the rails,
    and a saturated waveform transcribes to nothing at all.  Whisper reports
    that as an empty command, which is indistinguishable from silence -- so the
    condition is detected here, where it can be named.
    """
    return clipping_fraction(pcm) > MAX_CLIPPED_FRACTION


@dataclass(slots=True)
class VoiceSegmenter:
    """Turn a raw microphone stream into utterances using local energy VAD.

    This intentionally runs before Whisper. Quiet-room chunks never start a
    transcription process, while a short pre-roll keeps the first consonant of
    a wake phrase from being clipped.
    """

    frame_seconds: float = 0.1
    minimum_rms: int = 220
    silence_seconds: float = 0.8
    minimum_seconds: float = 0.45
    maximum_seconds: float = 12.0
    pre_roll_seconds: float = 0.3
    _pre_roll: deque[bytes] = field(init=False)
    _frames: list[bytes] = field(default_factory=list, init=False)
    _silent_frames: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if not 0.02 <= self.frame_seconds <= 0.5:
            raise ValueError("VAD frame duration must be between 0.02 and 0.5 seconds")
        self._pre_roll = deque(
            maxlen=max(1, round(self.pre_roll_seconds / self.frame_seconds))
        )

    def feed(self, pcm: bytes) -> bytes | None:
        voiced = _has_voice(pcm, minimum_rms=self.minimum_rms)
        if not self._frames:
            self._pre_roll.append(pcm)
            if not voiced:
                return None
            self._frames = list(self._pre_roll)
            self._pre_roll.clear()
            self._silent_frames = 0
            return None

        self._frames.append(pcm)
        self._silent_frames = 0 if voiced else self._silent_frames + 1
        duration = len(self._frames) * self.frame_seconds
        ended = self._silent_frames >= round(self.silence_seconds / self.frame_seconds)
        if duration < self.maximum_seconds and not ended:
            return None

        trailing = self._silent_frames
        frames = self._frames[:-trailing] if trailing else self._frames
        self._frames = []
        self._silent_frames = 0
        self._pre_roll.clear()
        audio = b"".join(frames)
        if len(audio) < int(_RATE * _CHANNELS * _SAMPLE_WIDTH * self.minimum_seconds):
            return None
        return audio


def _wav_bytes(pcm: bytes) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(_CHANNELS)
        wav.setsampwidth(_SAMPLE_WIDTH)
        wav.setframerate(_RATE)
        wav.writeframes(pcm)
    return output.getvalue()


async def listen_forever(
    config: VoiceConfig, *, chunk_seconds: float = 0.1, device: str | None = None
) -> None:
    recorder = shutil.which("parecord")
    if recorder is None:
        raise RuntimeError("continuous local listening needs parecord")
    model = LocalWhisperTranscriber()
    detector = WakeCommandDetector(config)
    chunk_bytes = int(_RATE * _CHANNELS * _SAMPLE_WIDTH * chunk_seconds)
    segmenter = VoiceSegmenter(frame_seconds=chunk_seconds)
    recorder_args = [recorder]
    if device:
        recorder_args.append(f"--device={device}")
    recorder_args.extend([
        "--raw",
        "--format=s16le",
        f"--rate={_RATE}",
        f"--channels={_CHANNELS}",
    ])
    process = await asyncio.create_subprocess_exec(
        *recorder_args,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stdout is not None
    _emit({"type": "ready"})
    # Pulse/PipeWire may deliver a buffered burst faster than the consumer gets
    # scheduled. A two-frame queue discarded the entire spoken phrase and kept
    # only its trailing silence. This holds two maximum utterances while still
    # bounding memory to roughly 800 KiB at the default format.
    queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=256)

    async def capture() -> None:
        try:
            while True:
                current = await process.stdout.readexactly(chunk_bytes)
                if queue.full():
                    queue.get_nowait()
                queue.put_nowait(current)
                await asyncio.sleep(0)
        except asyncio.IncompleteReadError:
            await queue.put(None)

    capture_task = asyncio.create_task(capture())
    try:
        while True:
            frame = await queue.get()
            if frame is None:
                break
            pcm = segmenter.feed(frame)
            if pcm is None:
                continue
            if is_clipping(pcm):
                _emit({"type": "warning", "text": "microphone input is clipping; lower the input volume"})
                continue
            try:
                transcript = await model.transcribe(_wav_bytes(pcm), mime_type="audio/wav")
            except Exception as error:  # noqa: BLE001 - keep the listener alive
                _emit({"type": "warning", "text": str(error)[:240]})
                continue
            command = detector.feed(transcript)
            if command:
                _emit({"type": "command", "text": command})
    finally:
        capture_task.cancel()
        if process.returncode is None:
            process.terminate()
            await process.wait()
    if process.returncode not in {0, -signal.SIGTERM}:
        detail = (await process.stderr.read()).decode("utf-8", "replace").strip()[:240]
        raise RuntimeError(f"audio capture stopped{f': {detail}' if detail else ''}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sleipnir-desktop-listen")
    parser.add_argument("--wake-name", default="Sleipnir")
    parser.add_argument("--chunk-seconds", type=float, default=0.1)
    parser.add_argument("--device", help="PulseAudio/PipeWire source name (default: system input)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 0.02 <= args.chunk_seconds <= 0.5:
        _emit({"type": "error", "text": "audio frame must be 0.02 to 0.5 seconds"})
        return 2
    try:
        asyncio.run(
            listen_forever(
                VoiceConfig(wake_name=args.wake_name, local_wake=True),
                chunk_seconds=args.chunk_seconds,
                device=args.device,
            )
        )
    except KeyboardInterrupt:
        return 0
    except Exception as error:  # noqa: BLE001 - native boundary returns a clean envelope
        _emit({"type": "error", "text": str(error)})
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["VoiceSegmenter", "WakeCommandDetector", "listen_forever", "main"]
