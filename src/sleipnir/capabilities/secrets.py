"""Credentials that live for one keystroke burst and then stop existing.

The rule this module enforces: a credential the operator types must never
reach a model prompt, the audit log, ``results.jsonl``, the manifest, a
traceback, or the terminal.  It goes from the operator's fingers into the
target field and nowhere else.

``Secret`` holds a ``bytearray`` rather than a ``str`` because CPython strings
are immutable and interned — there is no way to overwrite one in place.  The
byte buffer is zeroed the moment the secret is consumed.

    # ponytail: a transient `str` still exists for the microseconds between
    # decode and use, because both ydotool and Playwright take `str`. Killing
    # that last copy would need a C shim or piping bytes to a helper process;
    # upgrade path is a small setuid-free helper if the threat model ever
    # includes a same-user heap reader.
"""

from __future__ import annotations

import getpass
import sys
from dataclasses import dataclass, field
from types import TracebackType

from sleipnir.capabilities import audit, computer


class SecretConsumed(RuntimeError):
    """A secret was used twice.

    Deliberately fatal rather than forgiving: re-use almost always means a
    caller stashed the value somewhere, which is the exact failure this module
    exists to prevent.
    """


@dataclass
class Secret:
    """A one-shot credential.

    Every representation hook is overridden.  Without that, one ``print``,
    ``logging.info(locals())`` or unhandled exception in a caller would put the
    password in a transcript forever.
    """

    label: str
    _buffer: bytearray = field(repr=False, default_factory=bytearray)
    _spent: bool = field(repr=False, default=False)

    def __repr__(self) -> str:  # pragma: no cover - trivial but load-bearing
        return f"<Secret {self.label!r} len={len(self._buffer)} spent={self._spent}>"

    __str__ = __repr__

    def __format__(self, spec: str) -> str:
        return repr(self)

    def __len__(self) -> int:
        return len(self._buffer)

    def __bool__(self) -> bool:
        return bool(self._buffer) and not self._spent

    def wipe(self) -> None:
        for index in range(len(self._buffer)):
            self._buffer[index] = 0
        self._buffer.clear()
        self._spent = True

    def consume(self) -> str:
        """Yield the plaintext exactly once, then wipe the buffer."""
        if self._spent:
            raise SecretConsumed(f"secret {self.label!r} has already been used")
        value = self._buffer.decode("utf-8")
        self.wipe()
        return value

    def __enter__(self) -> Secret:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.wipe()


def capture(label: str, *, stream: object | None = None) -> Secret:
    """Prompt the operator for a credential with echo disabled.

    Reads straight into a byte buffer.  ``getpass`` is used for the terminal
    handling (it turns off echo correctly across platforms and restores it on
    interrupt), and its returned string is copied to bytes and dropped.
    """
    typed = getpass.getpass(f"  {label}: ", stream=stream or sys.stderr)
    secret = Secret(label=label, _buffer=bytearray(typed.encode("utf-8")))
    # Record that a credential was requested, never any part of its value.
    audit.record("secret.captured", {"label": label, "length": len(secret)})
    return secret


def type_into_focused_window(secret: Secret, *, submit: bool = False) -> None:
    """Type a captured credential into whatever window has focus, then wipe.

    This is the sign-in path: the operator brings the real login window
    forward, Sleipnir asks for the value inside its own frame, and the value is
    injected as keystrokes.  Nothing is stored, and the agent driving the flow
    never sees the characters.
    """
    computer.type_text(secret.consume(), key_delay_ms=18)
    if submit:
        computer.key("enter")
    audit.record("secret.typed", {"label": secret.label, "submitted": submit})


__all__ = ["Secret", "SecretConsumed", "capture", "type_into_focused_window"]
