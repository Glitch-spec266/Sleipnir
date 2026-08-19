"""Append-only record of every privileged action taken on the host.

Same discipline as ``results.jsonl``: one JSON object per line, fsynced, never
rewritten.  A capability that can type into any window and run any command is
only acceptable if there is an honest record of what it did.

The log records *what kind* of action happened and enough shape to audit it —
never the payload of a secret.  ``redact`` is applied at the boundary rather
than trusted to callers.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

DEFAULT_LOG = Path.home() / ".sleipnir" / "capability-audit.jsonl"

# Keys whose values must never be written, whatever a caller passes.
_FORBIDDEN = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "credential",
        "credentials",
        "otp",
        "pin",
        "text",  # typed keystrokes may be anything; record only the length
    }
)


def redact(detail: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in detail.items():
        if key.lower() in _FORBIDDEN:
            safe[key] = f"<redacted {len(value) if hasattr(value, '__len__') else '?'} chars>"
        else:
            safe[key] = value
    return safe


def record(action: str, detail: dict[str, Any] | None = None, *, log: Path | None = None) -> None:
    path = DEFAULT_LOG if log is None else log
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "action": action,
        "detail": redact(detail or {}),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


__all__ = ["DEFAULT_LOG", "record", "redact"]
