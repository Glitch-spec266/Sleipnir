"""Append-only reader/writer for ``results.jsonl``.

Deliberately synchronous. Appends happen at attempt boundaries, not in hot
loops, and a *synchronous* fsync is what lets the executor write a terminal
record from inside a cancellation handler — where awaiting anything is
unreliable, since the task is already being torn down.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from sleipnir.schema import AttemptFinished, AttemptStarted, ResultRecord

_ADAPTER: TypeAdapter[AttemptStarted | AttemptFinished] = TypeAdapter(ResultRecord)


class TornRecordError(RuntimeError):
    """Raised when a non-final line fails to parse — that is real corruption,
    not the torn trailing write a crash leaves behind."""


class ResultLog:
    """Append-only attempt log. The single source of truth for run state."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.warnings: list[str] = []
        self._cache: list[AttemptStarted | AttemptFinished] = []
        self._cache_key: tuple[int, int] | None = None

    def append(self, record: AttemptStarted | AttemptFinished) -> None:
        """Append one record and fsync it.

        fsync per record is the cost of the recovery story: an attempt that was
        dispatched must be on disk *before* the dispatch, or a crash loses the
        knowledge that money was spent. At attempt granularity this is a few
        milliseconds against a multi-second model call.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = record.model_dump_json() + "\n"
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())

    def read(self) -> list[AttemptStarted | AttemptFinished]:
        """Read every record, tolerating exactly one torn trailing line.

        A crash mid-append leaves a partial final line. That is expected and
        recoverable. A malformed line anywhere else means the file was damaged
        by something other than a clean crash, and silently skipping it would
        under-count spend — so it raises.
        """
        if not self.path.exists():
            return []

        # The executor folds the whole log on every readiness check, so an
        # uncached read makes a run O(n^2) in file I/O. Append-only means
        # (mtime, size) is a sound cache key: every append changes the size.
        stat = self.path.stat()
        key = (stat.st_mtime_ns, stat.st_size)
        if key == self._cache_key:
            return self._cache

        lines = self.path.read_text(encoding="utf-8", errors="replace").splitlines()
        records: list[AttemptStarted | AttemptFinished] = []
        for index, raw in enumerate(lines):
            if not raw.strip():
                continue
            try:
                records.append(_ADAPTER.validate_python(json.loads(raw)))
            except (json.JSONDecodeError, ValidationError) as exc:
                if index == len(lines) - 1:
                    self.warnings.append(
                        f"discarded torn trailing record at line {index + 1}: {exc}"
                    )
                    continue
                raise TornRecordError(
                    f"{self.path}:{index + 1} is malformed and is not the final line; "
                    "the log is damaged beyond ordinary crash recovery"
                ) from exc

        self._cache, self._cache_key = records, key
        return records

    def open_attempts(self) -> dict[tuple[str, int], AttemptStarted]:
        """Attempts with a start and no finish — in flight when the process died."""
        started: dict[tuple[str, int], AttemptStarted] = {}
        finished: set[tuple[str, int]] = set()
        for record in self.read():
            key = (record.task_id, record.attempt)
            if isinstance(record, AttemptStarted):
                started[key] = record
            else:
                finished.add(key)
        return {key: rec for key, rec in started.items() if key not in finished}


__all__ = ["ResultLog", "TornRecordError"]
