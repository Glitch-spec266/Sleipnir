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
import stat
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

REQUEST_DIR = Path.home() / ".sleipnir" / "secret-requests"
_MAX_REQUEST_BYTES = 4_096
_ANSWER_STATUSES = frozenset({"supplied", "cancelled", "failed"})


class HandoffError(RuntimeError):
    """Credential request state failed its local trust checks."""


@dataclass(frozen=True)
class SecretRequest:
    """A pending ask. Carries a label; never a value."""

    id: str
    label: str
    submit: bool
    path: Path
    requester_pid: int

    @property
    def answer_path(self) -> Path:
        return self.path.with_suffix(".answer")


def request_secret(label: str, *, submit: bool = False, directory: Path | None = None) -> SecretRequest:
    """File a request for the console to fulfil."""
    folder = directory or REQUEST_DIR
    if folder.exists() and (folder.is_symlink() or not folder.is_dir()):
        raise HandoffError(f"unsafe credential request directory: {folder}")
    folder.mkdir(parents=True, exist_ok=True)
    request_id = uuid.uuid4().hex[:12]
    path = folder / f"{request_id}.request"
    requester_pid = os.getpid()
    payload = {
        "id": request_id,
        "label": label,
        "submit": submit,
        "at": time.time(),
        "requester_pid": requester_pid,
    }
    with path.open("x", encoding="utf-8") as handle:
        os.chmod(handle.fileno(), 0o600)
        json.dump(payload, handle)
        handle.flush()
        os.fsync(handle.fileno())
    return SecretRequest(
        id=request_id,
        label=label,
        submit=submit,
        path=path,
        requester_pid=requester_pid,
    )


def _read_json_regular(path: Path) -> dict[str, object] | None:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_REQUEST_BYTES:
            return None
        raw = os.read(descriptor, _MAX_REQUEST_BYTES + 1)
        payload = json.loads(raw.decode("utf-8"))
        return payload if isinstance(payload, dict) else None
    except (OSError, UnicodeError, ValueError):
        return None
    finally:
        os.close(descriptor)


def _requester_alive(pid: object) -> bool:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid < 2:
        return False
    try:
        return (Path("/proc") / str(pid)).stat().st_uid == os.getuid()
    except OSError:
        return False


def await_answer(request: SecretRequest, *, timeout_s: float = 300.0, poll_s: float = 0.25) -> str:
    """Block until the console answers, and return its *status* only.

    Returns one of ``supplied``, ``cancelled``, or raises on timeout. The
    plaintext is deliberately unreachable from here — a caller that could read
    it would be a caller that could log it.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if request.answer_path.exists():
            payload = _read_json_regular(request.answer_path)
            status = payload.get("status") if payload is not None else "unknown"
            request.answer_path.unlink(missing_ok=True)
            return str(status) if status in _ANSWER_STATUSES else "unknown"
        time.sleep(poll_s)
    request.path.unlink(missing_ok=True)
    raise TimeoutError(
        f"no Sleipnir console answered the credential request for {request.label!r} "
        f"within {timeout_s:.0f}s"
    )


def pending(directory: Path | None = None) -> SecretRequest | None:
    """The oldest unanswered request, if any. Called by the console each frame."""
    folder = directory or REQUEST_DIR
    if folder.is_symlink() or not folder.is_dir():
        return None
    requests = sorted(
        folder.glob("*.request"),
        key=lambda path: path.lstat().st_mtime,
    )
    for path in requests:
        payload = _read_json_regular(path)
        if payload is None or not _requester_alive(payload.get("requester_pid")):
            path.unlink(missing_ok=True)  # unreadable request helps nobody
            continue
        request_id = payload.get("id")
        if not isinstance(request_id, str) or path.name != f"{request_id}.request":
            path.unlink(missing_ok=True)
            continue
        return SecretRequest(
            id=request_id,
            label=str(payload.get("label", "credential"))[:120],
            submit=bool(payload.get("submit", False)),
            path=path,
            requester_pid=int(payload["requester_pid"]),
        )
    return None


def answer(request: SecretRequest, status: str) -> None:
    """Tell the waiting process what happened. Status only — never the value."""
    if status not in _ANSWER_STATUSES:
        raise HandoffError(f"invalid credential handoff status: {status!r}")
    with request.answer_path.open("x", encoding="utf-8") as handle:
        os.chmod(handle.fileno(), 0o600)
        json.dump({"status": status}, handle)
        handle.flush()
        os.fsync(handle.fileno())
    request.path.unlink(missing_ok=True)


__all__ = [
    "REQUEST_DIR",
    "HandoffError",
    "SecretRequest",
    "answer",
    "await_answer",
    "pending",
    "request_secret",
]
