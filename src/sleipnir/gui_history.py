"""Encrypted, append-only operator conversation history for the desktop app."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

MAX_ENTRY_BYTES = 1_048_576


class HistoryError(RuntimeError):
    pass


class EncryptedHistory:
    """Encrypt every entry independently so an interrupted append loses one line."""

    def __init__(self, path: Path, key_path: Path) -> None:
        self.path = path
        self.key_path = key_path

    def _key(self) -> bytes:
        if self.key_path.exists():
            if self.key_path.is_symlink() or not self.key_path.is_file():
                raise HistoryError(f"unsafe history key path: {self.key_path}")
            info = self.key_path.stat()
            if info.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
                raise HistoryError("history key is accessible by another account")
            return self.key_path.read_bytes().strip()

        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        if self.key_path.parent.is_symlink():
            raise HistoryError(f"unsafe history directory: {self.key_path.parent}")
        key = Fernet.generate_key()
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(self.key_path, flags, 0o600)
        except FileExistsError:
            return self._key()
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(key)
            handle.flush()
            os.fsync(handle.fileno())
        return key

    def append(self, entry: dict[str, Any]) -> None:
        encoded = json.dumps(entry, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if len(encoded) > MAX_ENTRY_BYTES:
            raise HistoryError("history entry exceeds the 1 MiB safety limit")
        token = Fernet(self._key()).encrypt(encoded) + b"\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(self.path, flags, 0o600)
        with os.fdopen(descriptor, "ab") as handle:
            os.chmod(handle.fileno(), 0o600)
            handle.write(token)
            handle.flush()
            os.fsync(handle.fileno())

    def read(self, *, limit: int = 1_000) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        if self.path.is_symlink() or not self.path.is_file():
            raise HistoryError(f"unsafe history path: {self.path}")
        lines = self.path.read_bytes().splitlines()
        cipher = Fernet(self._key())
        entries: list[dict[str, Any]] = []
        for index, line in enumerate(lines):
            if not line:
                continue
            try:
                decoded = cipher.decrypt(line)
                payload = json.loads(decoded)
                if not isinstance(payload, dict):
                    raise ValueError("history payload is not an object")
            except (InvalidToken, json.JSONDecodeError, ValueError) as error:
                if index == len(lines) - 1:
                    continue
                raise HistoryError(f"history is damaged at line {index + 1}") from error
            entries.append(payload)
        return entries[-max(0, limit) :]


__all__ = ["EncryptedHistory", "HistoryError", "MAX_ENTRY_BYTES"]
