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
from types import TracebackType

from pydantic import TypeAdapter, ValidationError

from sleipnir import platform
from sleipnir.schema import AttemptFinished, AttemptStarted, ResultRecord

_ADAPTER: TypeAdapter[AttemptStarted | AttemptFinished] = TypeAdapter(ResultRecord)


class TornRecordError(RuntimeError):
    """Raised when a non-final line fails to parse — that is real corruption,
    not the torn trailing write a crash leaves behind."""


class RunLockError(RuntimeError):
    """Raised when another process already owns a run directory."""


class RunLock:
    """Kernel-backed exclusive ownership of a run directory.

    The result log alone cannot prevent two executors from observing the same
    READY task before either writes its start record.  ``flock`` closes that
    race, is released automatically on process death, and therefore needs no
    unsafe stale-lock cleanup protocol.
    """

    def __init__(self, run_root: Path) -> None:
        self.path = run_root / "run.lock"
        self._handle: object | None = None

    def __enter__(self) -> "RunLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+", encoding="utf-8")
        try:
            platform.try_lock_exclusive(handle)
        except platform.LockUnavailable as exc:
            handle.seek(0)
            owner = handle.read().strip() or "unknown owner"
            handle.close()
            raise RunLockError(
                f"run directory {self.path.parent} is already active ({owner})"
            ) from exc
        handle.seek(0)
        handle.truncate()
        handle.write(f"pid={os.getpid()}\n")
        handle.flush()
        os.fsync(handle.fileno())
        self._handle = handle
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        handle = self._handle
        self._handle = None
        if handle is not None:
            platform.unlock(handle)  # type: ignore[union-attr]
            handle.close()  # type: ignore[union-attr]


def run_is_active(run_root: Path) -> bool:
    """Whether another file description currently owns the run lock."""
    path = run_root / "run.lock"
    if not path.exists():
        return False
    try:
        # "r+" rather than "r": Windows' msvcrt.locking requires the handle
        # to be opened for writing to take any lock on it at all, even a
        # probe that is released immediately below. fcntl.flock has no such
        # requirement, so this was never an issue on the POSIX path.
        with path.open("r+", encoding="utf-8") as handle:
            try:
                platform.try_lock_exclusive(handle)
            except platform.LockUnavailable:
                return True
            finally:
                # Unlock is harmless after a failed non-blocking acquisition.
                try:
                    platform.unlock(handle)
                except OSError:
                    pass
    except OSError:
        # An unreadable lock is safer to present as active than as resumable.
        return True
    return False


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
        if platform.is_reparse_point(self.path):
            raise TornRecordError(f"refusing to append through symlinked result log: {self.path}")
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
        if platform.is_reparse_point(self.path):
            raise TornRecordError(f"refusing to read through symlinked result log: {self.path}")

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


__all__ = ["ResultLog", "RunLock", "RunLockError", "TornRecordError", "run_is_active"]
