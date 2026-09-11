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
import stat
import sys
import time
import wave
from array import array
from collections import deque
from dataclasses import dataclass, field

import httpx

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


ARM_TIMEOUT_SECONDS = 8.0
REPEAT_WINDOW_SECONDS = 6.0


@dataclass(slots=True)
class WakeCommandDetector:
    """Privacy-preserving transcript gate around :class:`VoiceRuntime`.

    Time arrives as an explicit argument rather than from a hidden clock, for
    the same reason terminal chrome takes a frame number: it is what makes the
    cooldown and the arming timeout testable without sleeping.
    """

    config: VoiceConfig
    arm_timeout_seconds: float = ARM_TIMEOUT_SECONDS
    repeat_window_seconds: float = REPEAT_WINDOW_SECONDS
    runtime: VoiceRuntime = field(init=False)
    _armed_at: float = field(default=0.0, init=False)
    _last_command: str = field(default="", init=False)
    _last_command_at: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        self.runtime = VoiceRuntime(self.config)

    def _release(self, command: str, now: float) -> str | None:
        """Emit a command unless it repeats the previous one immediately.

        The segmenter ends an utterance on 0.8 s of silence, so one spoken
        sentence with a pause in it arrives as two transcripts. Both used to
        reach the host, which started two turns and spoke both replies at once.
        """
        if command == self._last_command and now - self._last_command_at < self.repeat_window_seconds:
            return None
        self._last_command = command
        self._last_command_at = now
        return command

    def feed(self, transcript: str, *, now: float = 0.0) -> str | None:
        clean = transcript.strip().strip(" .,!?:;-\t\n")
        if not clean:
            return None
        if self.runtime.phase == "hearing":
            if now - self._armed_at <= self.arm_timeout_seconds:
                self.runtime.submit_utterance(clean, remote=False)
                command = self.runtime.heard
                self.runtime.complete()
                return self._release(command, now)
            # Nobody followed the wake phrase in time. Disarm rather than
            # treating an unrelated remark as an instruction.
            self.runtime.complete()
        span = _wake_span(clean, self.config.wake_name)
        if span is None or not self.runtime.feed_local_transcript(clean):
            return None
        command = clean[span[1] :].strip(" .,!?:;-\t\n")
        if not command:
            self._armed_at = now
            return None
        self.runtime.submit_utterance(command, remote=False)
        self.runtime.complete()
        return self._release(command, now)


@dataclass(slots=True)
class ListenerGate:
    """Host-controlled mute.

    Piper renders through the speakers while ``parecord`` is still capturing,
    so without this Sleipnir wakes itself on its own reply. The host also holds
    the gate shut for the whole of a turn, which is what stops a second wake
    phrase from starting a second concurrent agent.
    """

    muted: bool = False

    def apply(self, line: str) -> bool:
        """Apply one control line; return whether it was understood."""
        try:
            payload = json.loads(line)
        except (TypeError, ValueError):
            return False
        if not isinstance(payload, dict):
            return False
        kind = payload.get("type")
        if kind == "mute":
            self.muted = True
            return True
        if kind == "unmute":
            self.muted = False
            return True
        return False


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

    def reset(self) -> None:
        """Discard whatever is buffered, without emitting it.

        Used when the host mutes the listener mid-utterance: resuming must not
        splice speech from before the mute onto speech from after it.
        """
        self._frames = []
        self._silent_frames = 0
        self._pre_roll.clear()

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


# MEASURED on this machine 2026-09-10: a cold ``jarvis`` turn took 4.99 s and a
# warm one 0.20 s. ``keep_alive`` expires while the operator is simply not
# talking, so the first question after any quiet spell paid the whole load.
OLLAMA_KEEP_ALIVE = "30m"
OLLAMA_WARM_SECONDS = 480.0


async def keep_model_warm(
    model: str,
    *,
    interval: float = OLLAMA_WARM_SECONDS,
    transport: object | None = None,
    iterations: int | None = None,
) -> None:
    """Hold the local model in VRAM for as long as the wake loop is listening.

    Ollama loads a model for a request that carries no prompt, so this costs an
    HTTP round trip and no tokens. Warmth is an optimisation and never a
    dependency: every failure is swallowed, because a stopped Ollama must not
    take the microphone down with it.
    """
    remaining = iterations
    while remaining is None or remaining > 0:
        try:
            async with httpx.AsyncClient(transport=transport, timeout=120) as client:  # type: ignore[arg-type]
                await client.post(
                    "http://127.0.0.1:11434/api/generate",
                    json={"model": model, "keep_alive": OLLAMA_KEEP_ALIVE},
                )
        except Exception:  # noqa: BLE001 - warmth is best effort, never fatal
            pass
        if remaining is not None:
            remaining -= 1
            if remaining <= 0:
                return
        await asyncio.sleep(interval)


def _wav_bytes(pcm: bytes) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(_CHANNELS)
        wav.setsampwidth(_SAMPLE_WIDTH)
        wav.setframerate(_RATE)
        wav.writeframes(pcm)
    return output.getvalue()


async def listen_forever(
    config: VoiceConfig,
    *,
    chunk_seconds: float = 0.1,
    device: str | None = None,
    warm_model: str = "",
) -> None:
    recorder = shutil.which("parecord")
    if recorder is None:
        raise RuntimeError("continuous local listening needs parecord")
    model = LocalWhisperTranscriber()
    detector = WakeCommandDetector(config)
    gate = ListenerGate()
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

    async def control() -> None:
        """Apply host mute/unmute lines arriving on stdin.

        The host holds the gate shut for the whole of a turn and while it is
        speaking, so the microphone cannot start a second turn or hear Piper.
        """
        reader = asyncio.StreamReader()
        try:
            await asyncio.get_running_loop().connect_read_pipe(
                lambda: asyncio.StreamReaderProtocol(reader), sys.stdin
            )
        except (OSError, ValueError):
            return  # No usable stdin: the listener simply never mutes.
        while True:
            line = await reader.readline()
            if not line:
                break
            gate.apply(line.decode("utf-8", "replace").strip())
        # EOF on a pipe means the host that spawned us is gone. Exiting here is
        # what stops an orphaned listener from holding the microphone and
        # racing the next app launch for the same wake word.
        try:
            parented = stat.S_ISFIFO(os.fstat(sys.stdin.fileno()).st_mode)
        except OSError:
            parented = False
        if parented:
            await queue.put(None)

    capture_task = asyncio.create_task(capture())
    control_task = asyncio.create_task(control())
    # Residency is tied to the wake loop rather than to a timer: the model is
    # held exactly while the assistant is listening for its name.
    warm_task = asyncio.create_task(keep_model_warm(warm_model)) if warm_model else None
    try:
        while True:
            frame = await queue.get()
            if frame is None:
                break
            if gate.muted:
                segmenter.reset()
                continue
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
            if gate.muted:
                # The turn started while this utterance was being transcribed.
                continue
            command = detector.feed(transcript, now=time.monotonic())
            if command:
                _emit({"type": "command", "text": command})
    finally:
        capture_task.cancel()
        control_task.cancel()
        if warm_task is not None:
            warm_task.cancel()
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
    parser.add_argument(
        "--warm-model",
        default="",
        help="keep this Ollama model resident while listening (empty disables)",
    )
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
                warm_model=args.warm_model.strip(),
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


__all__ = ["VoiceSegmenter", "WakeCommandDetector", "keep_model_warm", "listen_forever", "main"]
