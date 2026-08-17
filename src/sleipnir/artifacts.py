"""Attempt workspace layout and output collection.

One directory per attempt, never shared:

    artifacts/task-<id>/attempt-NN/
        prompt.txt          exactly what was sent to the model
        input-manifest.json what was resolved into that prompt, and what was clipped
        stdout.log          raw provider stream
        stderr.log          raw provider stderr
        outcome.json        adapter's structured outcome, for forensics
        summary.md          the subagent's bounded self-summary
        <declared outputs>  at the paths the task's OutputContract named

Write-once per attempt is what makes retry and `resume` safe: a re-run can
never overwrite the evidence from the attempt that failed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sleipnir.schema import AttemptFinished, OutputContract, ProducedArtifact

SUMMARY_FILENAME = "summary.md"
PROMPT_FILENAME = "prompt.txt"
INPUT_MANIFEST_FILENAME = "input-manifest.json"
STDOUT_FILENAME = "stdout.log"
STDERR_FILENAME = "stderr.log"
OUTCOME_FILENAME = "outcome.json"

#: Files the harness itself writes. Excluded when scanning for undeclared
#: outputs, so housekeeping never shows up as a task deliverable.
RESERVED_FILENAMES = frozenset(
    {
        SUMMARY_FILENAME,
        PROMPT_FILENAME,
        INPUT_MANIFEST_FILENAME,
        STDOUT_FILENAME,
        STDERR_FILENAME,
        OUTCOME_FILENAME,
    }
)

_HASH_CHUNK = 1 << 20


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(slots=True, frozen=True)
class AttemptWorkspace:
    """Filesystem home for one attempt. Paths recorded in results.jsonl are
    always relative to the run root, so a run directory stays portable."""

    run_root: Path
    task_id: str
    attempt: int

    @property
    def rel_dir(self) -> str:
        return f"artifacts/task-{self.task_id}/attempt-{self.attempt:02d}"

    @property
    def dir(self) -> Path:
        return self.run_root / self.rel_dir

    def rel(self, filename: str) -> str:
        return f"{self.rel_dir}/{filename}"

    @property
    def stdout_path(self) -> Path:
        return self.dir / STDOUT_FILENAME

    @property
    def stderr_path(self) -> Path:
        return self.dir / STDERR_FILENAME

    @property
    def prompt_path(self) -> Path:
        return self.dir / PROMPT_FILENAME

    @property
    def summary_path(self) -> Path:
        return self.dir / SUMMARY_FILENAME

    def prepare(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)

    def write_text(self, filename: str, text: str) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / filename).write_text(text, encoding="utf-8")

    def write_json(self, filename: str, payload: Any) -> None:
        self.write_text(filename, json.dumps(payload, indent=2, default=str))

    def read_summary(self) -> str | None:
        """The subagent's self-written summary, if it produced one."""
        if not self.summary_path.exists():
            return None
        text = self.summary_path.read_text(encoding="utf-8", errors="replace").strip()
        return text or None

    def collect_outputs(
        self, contract: OutputContract
    ) -> tuple[list[ProducedArtifact], list[str]]:
        """Match what is on disk against what the task promised.

        Returns (produced, missing_required_names). Only *required* outputs
        count as missing — an absent optional output is not a partial failure.
        """
        produced: list[ProducedArtifact] = []
        missing: list[str] = []
        claimed: set[Path] = set()

        for expected in contract.outputs:
            path = self.dir / expected.path
            if path.is_file() and path.stat().st_size > 0:
                claimed.add(path.resolve())
                produced.append(
                    ProducedArtifact(
                        name=expected.name,
                        path=self.rel(expected.path),
                        bytes=path.stat().st_size,
                        sha256=sha256_file(path),
                    )
                )
            elif expected.required:
                missing.append(expected.name)

        produced.extend(self._unexpected(claimed))
        return produced, missing

    def _unexpected(self, claimed: set[Path]) -> list[ProducedArtifact]:
        """Files the task wrote but never declared.

        Recorded with an empty ``name`` rather than discarded: a task that
        writes something it did not promise is usually a spec bug, and silently
        dropping the evidence makes that bug invisible.
        """
        extras: list[ProducedArtifact] = []
        if not self.dir.exists():
            return extras
        for path in sorted(self.dir.rglob("*")):
            if not path.is_file() or path.resolve() in claimed:
                continue
            if path.parent == self.dir and path.name in RESERVED_FILENAMES:
                continue
            extras.append(
                ProducedArtifact(
                    name="",
                    path=self.rel(str(path.relative_to(self.dir))),
                    bytes=path.stat().st_size,
                    sha256=None,
                )
            )
        return extras


def clip_summary(text: str) -> tuple[str, bool]:
    """Enforce the schema's hard summary cap at the write site.

    The schema *rejects* an over-long summary rather than silently truncating,
    so truncation has to happen deliberately, here, where we can also record
    that it happened.
    """
    limit = AttemptFinished.SUMMARY_MAX_CHARS
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed, False
    return collapsed[: limit - 1] + "…", True


__all__ = [
    "INPUT_MANIFEST_FILENAME",
    "OUTCOME_FILENAME",
    "PROMPT_FILENAME",
    "RESERVED_FILENAMES",
    "STDERR_FILENAME",
    "STDOUT_FILENAME",
    "SUMMARY_FILENAME",
    "AttemptWorkspace",
    "clip_summary",
    "sha256_file",
]
