"""Read text or images from the operator's Wayland clipboard.

Keyboard-driven copy/paste stays in :mod:`computer`: emitting Ctrl+Shift+C/V
lets the focused application preserve its native MIME payload. This module is
the receiving side for Sleipnir's own terminal. A PTY can carry pasted text but
cannot carry image pixels, so an image is materialised as a private file and
the model receives that path.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

from sleipnir.capabilities import audit

DEFAULT_DIR = Path.home() / ".sleipnir" / "clipboard"
MAX_CLIPBOARD_BYTES = 50 * 1024 * 1024

_IMAGE_SUFFIXES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
}
_TEXT_TYPES = ("text/plain;charset=utf-8", "text/plain", "UTF8_STRING", "STRING")


class ClipboardError(RuntimeError):
    """The desktop clipboard is unavailable or has no supported payload."""


@dataclass(frozen=True)
class ClipboardPayload:
    kind: str
    mime_type: str
    text: str | None = None
    path: Path | None = None


def available() -> bool:
    return shutil.which("wl-paste") is not None


def _run(*args: str) -> bytes:
    executable = shutil.which("wl-paste")
    if executable is None:
        raise ClipboardError("wl-paste is not installed; run `sleipnir setup`")
    result = subprocess.run(
        [executable, *args],
        capture_output=True,
        timeout=15,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()[:200]
        raise ClipboardError(f"could not read the Wayland clipboard: {detail}")
    if len(result.stdout) > MAX_CLIPBOARD_BYTES:
        raise ClipboardError(
            f"clipboard payload exceeds the {MAX_CLIPBOARD_BYTES // (1024 * 1024)} MiB limit"
        )
    return result.stdout


def offered_types() -> tuple[str, ...]:
    raw = _run("--list-types")
    return tuple(
        line.strip()
        for line in raw.decode("utf-8", "replace").splitlines()
        if line.strip()
    )


def read(*, destination_dir: Path = DEFAULT_DIR) -> ClipboardPayload:
    """Read text directly or save an image privately and return its path."""
    offered = offered_types()
    for mime_type, suffix in _IMAGE_SUFFIXES.items():
        if mime_type not in offered:
            continue
        body = _run("--type", mime_type)
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / f"clipboard-{uuid.uuid4().hex}{suffix}"
        with destination.open("xb") as handle:
            os.chmod(handle.fileno(), 0o600)
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        audit.record(
            "clipboard.image_read",
            {"mime_type": mime_type, "bytes": len(body), "path": str(destination)},
        )
        return ClipboardPayload(kind="image", mime_type=mime_type, path=destination)

    for mime_type in _TEXT_TYPES:
        if mime_type not in offered:
            continue
        body = _run("--no-newline", "--type", mime_type)
        text = body.decode("utf-8", "replace")
        audit.record("clipboard.text_read", {"mime_type": mime_type, "chars": len(text)})
        return ClipboardPayload(kind="text", mime_type=mime_type, text=text)

    detail = ", ".join(offered[:8]) or "empty"
    raise ClipboardError(f"clipboard has no supported text or image payload ({detail})")


__all__ = [
    "ClipboardError",
    "ClipboardPayload",
    "DEFAULT_DIR",
    "MAX_CLIPBOARD_BYTES",
    "available",
    "offered_types",
    "read",
]
