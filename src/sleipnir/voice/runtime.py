"""I/O-neutral local wake-word state machine used by desktop microphone hosts."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from sleipnir.voice.config import VoiceConfig


def _words(text: str) -> list[str]:
    return re.findall(r"[\w]+", text.casefold(), re.UNICODE)


@dataclass(slots=True)
class VoiceRuntime:
    config: VoiceConfig
    network_hook: Callable[[str], None] | None = None
    phase: str = field(default="armed", init=False)
    heard: str = field(default="", init=False)

    def feed_local_transcript(self, transcript: str) -> bool:
        """Consume on-device text and never perform network I/O."""
        if self.phase != "armed":
            return False
        heard = _words(transcript)
        phrase = ["hey", *_words(self.config.wake_name)]
        activated = any(
            heard[index : index + len(phrase)] == phrase
            for index in range(max(0, len(heard) - len(phrase) + 1))
        )
        if activated:
            self.phase = "hearing"
        return activated

    def begin_push_to_talk(self) -> None:
        self.phase = "hearing"
        self.heard = ""

    def submit_utterance(self, transcript: str, *, remote: bool) -> None:
        if self.phase != "hearing":
            raise RuntimeError("voice is not hearing an utterance")
        self.heard = transcript.strip()
        if not self.heard:
            raise ValueError("utterance cannot be empty")
        self.phase = "thinking"
        if remote and self.network_hook is not None:
            self.network_hook("utterance")

    def begin_action(self) -> None:
        self.phase = "acting"

    def await_approval(self) -> None:
        self.phase = "approval"

    def begin_speaking(self) -> None:
        self.phase = "speaking"

    def interrupt(self) -> bool:
        if self.phase != "speaking" or not self.config.interruptible:
            return False
        self.phase = "hearing"
        return True

    def complete(self) -> None:
        self.phase = "armed"
        self.heard = ""


__all__ = ["VoiceRuntime"]
