"""Asking the operator for a credential from a process that has no terminal.

The original design was wrong in a way only a live run could show. `secret
prompt` used ``getpass``, which needs a controlling terminal — and the process
that needs to call it is a tool subprocess spawned by a model, where
``/dev/tty`` is "No such device or address". The credential path could not be
driven by the model it was built for.

The fix is a handoff. The subprocess writes a *request* — a label and nothing
else — and waits. The console, which does own the terminal, notices it, prompts
inside its own frame, and injects the value. The waiting process is told only
whether it succeeded.

The value never travels. It exists in the console process, goes to the target,
and is wiped. No file, no pipe, and no environment variable ever holds it, which
is the property that makes the whole path worth having.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

REQUEST_DIR = Path.home() / ".sleipnir" / "secret-requests"


@dataclass(frozen=True)
class SecretRequest:
    """A pending ask. Carries a label; never a value."""

    id: str
    label: str
    submit: bool
    path: Path

    @property
    def answer_path(self) -> Path:
        return self.path.with_suffix(".answer")


def request_secret(label: str, *, submit: bool = False, directory: Path | None = None) -> SecretRequest:
    """File a request for the console to fulfil."""
    folder = directory or REQUEST_DIR
    folder.mkdir(parents=True, exist_ok=True)
    request_id = uuid.uuid4().hex[:12]
    path = folder / f"{request_id}.request"
    payload = {"id": request_id, "label": label, "submit": submit, "at": time.time()}
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle)
        handle.flush()
        os.fsync(handle.fileno())
    return SecretRequest(id=request_id, label=label, submit=submit, path=path)


def await_answer(request: SecretRequest, *, timeout_s: float = 300.0, poll_s: float = 0.25) -> str:
    """Block until the console answers, and return its *status* only.

    Returns one of ``supplied``, ``cancelled``, or raises on timeout. The
    plaintext is deliberately unreachable from here — a caller that could read
    it would be a caller that could log it.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if request.answer_path.exists():
            try:
                status = json.loads(request.answer_path.read_text(encoding="utf-8"))["status"]
            except (OSError, ValueError, KeyError):
                status = "unknown"
            request.answer_path.unlink(missing_ok=True)
            return str(status)
        time.sleep(poll_s)
    request.path.unlink(missing_ok=True)
    raise TimeoutError(
        f"no Sleipnir console answered the credential request for {request.label!r} "
        f"within {timeout_s:.0f}s"
    )


def pending(directory: Path | None = None) -> SecretRequest | None:
    """The oldest unanswered request, if any. Called by the console each frame."""
    folder = directory or REQUEST_DIR
    if not folder.is_dir():
        return None
    requests = sorted(folder.glob("*.request"), key=lambda path: path.stat().st_mtime)
    for path in requests:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            path.unlink(missing_ok=True)  # unreadable request helps nobody
            continue
        return SecretRequest(
            id=str(payload.get("id", "")),
            label=str(payload.get("label", "credential"))[:120],
            submit=bool(payload.get("submit", False)),
            path=path,
        )
    return None


def answer(request: SecretRequest, status: str) -> None:
    """Tell the waiting process what happened. Status only — never the value."""
    with request.answer_path.open("w", encoding="utf-8") as handle:
        json.dump({"status": status}, handle)
        handle.flush()
        os.fsync(handle.fileno())
    request.path.unlink(missing_ok=True)


__all__ = [
    "REQUEST_DIR",
    "SecretRequest",
    "answer",
    "await_answer",
    "pending",
    "request_secret",
]
