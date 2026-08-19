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
import os
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


class WorkspaceCollisionError(RuntimeError):
    """An attempt path existed before the harness claimed this attempt."""


def contained_regular_file(path: Path, root: Path) -> bool:
    """True only for a non-symlinked file physically beneath ``root``.

    Subagents control their workspace.  Following a symlink they created would
    let a claimed output or ``summary.md`` read an arbitrary host file and send
    it to the orchestrator or a downstream provider.
    """
    try:
        resolved_root = root.resolve(strict=True)
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(resolved_root) or not resolved.is_file():
            return False
        current = path
        while current != root:
            if current.is_symlink():
                return False
            current = current.parent
        return True
    except (OSError, RuntimeError):
        return False


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
        """Ensure an already-claimed workspace remains a real local directory."""
        if self.dir.exists():
            if self.dir.is_symlink() or not self.dir.is_dir():
                raise WorkspaceCollisionError(f"unsafe attempt workspace: {self.dir}")
            return
        self.prepare_fresh()

    def prepare_fresh(self) -> None:
        """Atomically claim a new attempt directory; never reuse old contents."""
        if Path(self.task_id).name != self.task_id or self.attempt < 1:
            raise WorkspaceCollisionError(
                f"unsafe attempt workspace identity: {self.task_id!r}/{self.attempt}"
            )
        parent = self.dir.parent
        artifacts_root = self.run_root / "artifacts"
        if artifacts_root.exists():
            if artifacts_root.is_symlink() or not artifacts_root.is_dir():
                raise WorkspaceCollisionError(
                    f"attempt workspace root is unsafe: {artifacts_root}"
                )
        else:
            artifacts_root.mkdir()
        try:
            parent.mkdir()
        except FileExistsError:
            pass
        if parent.is_symlink() or not parent.is_dir():
            raise WorkspaceCollisionError(
                f"attempt workspace parent is unsafe: {parent}"
            )
        try:
            self.dir.mkdir()
        except FileExistsError as exc:
            raise WorkspaceCollisionError(
                f"refusing to reuse pre-existing attempt workspace: {self.dir}"
            ) from exc

    def write_text(self, filename: str, text: str) -> None:
        """Write one harness-owned top-level file without following symlinks.

        The workspace must already have been atomically claimed. A provider can
        write inside it, so a normal Path.write_text after dispatch would follow
        a malicious pre-created ``outcome.json`` symlink into the host.
        """
        if Path(filename).name != filename or filename in {"", ".", ".."}:
            raise WorkspaceCollisionError(f"unsafe workspace filename: {filename!r}")
        try:
            directory_fd = os.open(self.dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except OSError as exc:
            raise WorkspaceCollisionError(f"unsafe attempt workspace: {self.dir}") from exc
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
            try:
                file_fd = os.open(filename, flags, 0o600, dir_fd=directory_fd)
            except OSError as exc:
                raise WorkspaceCollisionError(
                    f"unsafe workspace output path: {self.dir / filename}"
                ) from exc
            with os.fdopen(file_fd, "w", encoding="utf-8") as handle:
                handle.write(text)
        finally:
            os.close(directory_fd)

    def write_json(self, filename: str, payload: Any) -> None:
        self.write_text(filename, json.dumps(payload, indent=2, default=str))

    def read_summary(self) -> str | None:
        """The subagent's self-written summary, if it produced one."""
        if not contained_regular_file(self.summary_path, self.dir):
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
            if contained_regular_file(path, self.dir) and path.stat().st_size > 0:
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
            if not contained_regular_file(path, self.dir) or path.resolve() in claimed:
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
    "WorkspaceCollisionError",
    "clip_summary",
    "contained_regular_file",
    "sha256_file",
]
