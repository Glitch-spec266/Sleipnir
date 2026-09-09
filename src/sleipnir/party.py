"""Encrypted, live collaboration between Sleipnir consoles.

The public relay is deliberately only a dumb wire.  It sees a random topic and
AES-GCM ciphertext; the join code carries the topic, the AEAD key, and the
creator's Ed25519 public key.  Every member signs its encrypted message and its
identity is the hash of that signing key.  Sharing the party key therefore lets
somebody join, but it does not let them impersonate the creator and rewrite the
hierarchy.

Party messages are coordination text, never plans, artifacts, transcripts, or
task output.  In particular, receiving a message does not mutate ``plan.json``.
Any proposed plan change still goes through the existing revision review gate.

``cryptography`` is a required dependency because party is a first-class
console feature. There is still no insecure fallback: without an AEAD and
signatures a public ntfy topic is refused rather than used in plaintext.
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote, urlsplit

from sleipnir.capabilities import audit

DEFAULT_RELAY = "https://ntfy.sh"
PROTOCOL_VERSION = 1
MAX_TEXT_CHARS = 4_000
MAX_WIRE_BYTES = 16_384
MAX_REPLAY_IDS = 2_048
POLL_INTERVAL_S = 1.0

_TOPIC = re.compile(r"^sleipnir-[a-z0-9]{32}$")
_MEMBER = re.compile(r"^[A-Za-z0-9_-]{12}$")
_WIRE_PREFIX = "sp1."
_CODE_PREFIX = "spj1."


class PartyError(RuntimeError):
    """The party could not be reached or used."""


class PartyDependencyError(PartyError):
    """Authenticated encryption support is not installed."""


class PartyCodeError(PartyError):
    """A join code is malformed or names an unapproved relay."""


class PartyProtocolError(PartyError):
    """A relay payload failed validation, authentication, or signature checks."""


class PartyPolicyError(PartyError):
    """A member tried to perform an action its role does not permit."""


class PartyMode(StrEnum):
    COLLABORATE = "collaborate"
    DELEGATE = "delegate"


class MessageKind(StrEnum):
    HELLO = "hello"
    CHAT = "chat"
    QUESTION = "question"
    REPLY = "reply"
    STATUS = "status"
    ASSIGNMENT = "assignment"
    MODE = "mode"
    LEAVE = "leave"


def wipe(buffer: bytearray) -> None:
    """Overwrite a mutable secret before releasing it."""
    for index in range(len(buffer)):
        buffer[index] = 0
    buffer.clear()


def _b64(data: bytes | bytearray) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    try:
        return base64.b64decode(
            text + "=" * (-len(text) % 4), altchars=b"-_", validate=True
        )
    except (ValueError, binascii.Error) as error:
        raise PartyProtocolError("invalid base64 in party payload") from error


def _crypto() -> tuple[Any, Any, Any]:
    try:
        from cryptography.exceptions import InvalidSignature, InvalidTag
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as error:  # pragma: no cover - exercised in packaging smoke tests
        raise PartyDependencyError(
            "party encryption is unavailable; reinstall Sleipnir with its required dependencies"
        ) from error
    return AESGCM, InvalidTag, InvalidSignature


def _ed25519() -> tuple[Any, Any, Any]:
    _crypto()
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )

    return Ed25519PrivateKey, Ed25519PublicKey, serialization


def _clean_name(value: str) -> str:
    cleaned = "".join(ch for ch in " ".join(value.split()) if ch.isprintable())
    return cleaned[:80] or "member"


def _member_id(public_key: bytes) -> str:
    return _b64(hashlib.sha256(public_key).digest()[:9])


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _normalise_relay(value: str) -> str:
    relay = value.rstrip("/")
    parts = urlsplit(relay)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
        or parts.path not in ("", "/")
    ):
        raise PartyCodeError("party relay must be an HTTPS origin with no credentials or path")
    return relay


@dataclass
class JoinCode:
    """A wipeable party credential. Its representation never includes the code."""

    relay_url: str
    topic: str
    leader_public: bytes
    _key: bytearray
    _spent: bool = False

    @property
    def leader_id(self) -> str:
        return _member_id(self.leader_public)

    def __repr__(self) -> str:
        return f"<JoinCode redacted spent={self._spent}>"

    __str__ = __repr__

    def export(self) -> bytearray:
        if self._spent:
            raise PartyCodeError("join code has already been wiped")
        payload = {
            "v": PROTOCOL_VERSION,
            "relay": self.relay_url,
            "topic": self.topic,
            "key": _b64(self._key),
            "leader": _b64(self.leader_public),
        }
        return bytearray((_CODE_PREFIX + _b64(_canonical(payload))).encode("ascii"))

    def consume(self) -> bytearray:
        encoded = self.export()
        self.wipe()
        return encoded

    def wipe(self) -> None:
        wipe(self._key)
        self._spent = True

    @classmethod
    def decode(
        cls,
        encoded: bytes | bytearray,
        *,
        allowed_relays: Sequence[str] = (DEFAULT_RELAY,),
    ) -> JoinCode:
        try:
            text = bytes(encoded).decode("ascii").strip()
            if not text.startswith(_CODE_PREFIX):
                raise PartyCodeError("not a Sleipnir party join code")
            raw = _unb64(text[len(_CODE_PREFIX) :])
            payload = json.loads(raw)
        except PartyError:
            raise
        except (UnicodeError, ValueError, TypeError) as error:
            raise PartyCodeError("malformed Sleipnir party join code") from error
        if not isinstance(payload, dict) or payload.get("v") != PROTOCOL_VERSION:
            raise PartyCodeError("unsupported Sleipnir party join code version")
        relay_url = _normalise_relay(str(payload.get("relay", "")))
        approved = {_normalise_relay(item) for item in allowed_relays}
        if relay_url not in approved:
            raise PartyCodeError(
                f"join code names unapproved relay {relay_url!r}; approve it explicitly"
            )
        topic = str(payload.get("topic", ""))
        if not _TOPIC.fullmatch(topic):
            raise PartyCodeError("join code contains an invalid topic")
        try:
            key = _unb64(str(payload.get("key", "")))
            leader = _unb64(str(payload.get("leader", "")))
        except PartyProtocolError as error:
            raise PartyCodeError("join code contains invalid key material") from error
        if len(key) != 32 or len(leader) != 32:
            raise PartyCodeError("join code contains invalid key material")
        return cls(relay_url, topic, leader, bytearray(key))


@dataclass(frozen=True)
class RelayRecord:
    id: str
    payload: str


class Relay(Protocol):
    def publish(self, topic: str, payload: str) -> str: ...

    def poll(self, topic: str, since: str | None) -> tuple[RelayRecord, ...]: ...


class NtfyRelay:
    """The documented ntfy publish and cached JSON-poll APIs."""

    def __init__(self, relay_url: str = DEFAULT_RELAY, *, client: Any = None) -> None:
        import httpx

        self.relay_url = _normalise_relay(relay_url)
        self._owns_client = client is None
        self.client = client or httpx.Client(timeout=15.0, follow_redirects=False)

    def _url(self, topic: str) -> str:
        if not _TOPIC.fullmatch(topic):
            raise PartyProtocolError("invalid party topic")
        return f"{self.relay_url}/{quote(topic, safe='')}"

    def publish(self, topic: str, payload: str) -> str:
        if len(payload.encode("ascii", "strict")) > MAX_WIRE_BYTES:
            raise PartyProtocolError("encrypted party payload exceeds the relay limit")
        try:
            response = self.client.post(
                self._url(topic),
                content=payload,
                headers={"Content-Type": "text/plain", "Cache": "yes"},
            )
            response.raise_for_status()
            message_id = response.json().get("id")
        except Exception as error:  # noqa: BLE001 - HTTP clients vary at this seam
            raise PartyError(f"party relay publish failed: {type(error).__name__}") from error
        if not isinstance(message_id, str) or not message_id:
            raise PartyProtocolError("party relay returned no message id")
        return message_id[:80]

    def poll(self, topic: str, since: str | None) -> tuple[RelayRecord, ...]:
        params = {"poll": "1", "since": since or "all"}
        try:
            response = self.client.get(self._url(topic) + "/json", params=params)
            response.raise_for_status()
            raw = response.content
        except Exception as error:  # noqa: BLE001 - HTTP clients vary at this seam
            raise PartyError(f"party relay poll failed: {type(error).__name__}") from error
        if len(raw) > 2 * 1024 * 1024:
            raise PartyProtocolError("party relay replay exceeds the local safety limit")
        records: list[RelayRecord] = []
        for line in raw.splitlines():
            try:
                item = json.loads(line)
            except (UnicodeError, ValueError):
                continue
            if not isinstance(item, dict) or item.get("event") != "message":
                continue
            message_id, payload = item.get("id"), item.get("message")
            if isinstance(message_id, str) and isinstance(payload, str):
                records.append(RelayRecord(message_id[:80], payload))
        return tuple(records)

    def close(self) -> None:
        if self._owns_client:
            self.client.close()


@dataclass(frozen=True)
class PartyMessage:
    id: str
    sent_at: int
    kind: MessageKind
    sender: str
    sender_name: str
    recipient: str | None
    text: str
    mode: PartyMode | None


class PartySession:
    """One in-memory member, with optional background relay polling."""

    def __init__(
        self,
        *,
        name: str,
        relay_url: str,
        topic: str,
        key: bytes | bytearray,
        leader_public: bytes,
        signing_key: bytes | bytearray,
        relay: Relay | None = None,
    ) -> None:
        self.name = _clean_name(name)
        self.relay_url = _normalise_relay(relay_url)
        self.topic = topic
        self._key = bytearray(key)
        self.leader_public = bytes(leader_public)
        self._signing_key = bytearray(signing_key)
        self.public_key = self._public_from_private(self._signing_key)
        self.member_id = _member_id(self.public_key)
        self.leader_id = _member_id(self.leader_public)
        self.mode = PartyMode.COLLABORATE
        self.members: dict[str, str] = {self.member_id: self.name}
        self._relay = relay or NtfyRelay(self.relay_url)
        self._last_relay_id: str | None = None
        self._seen: dict[str, None] = {}
        self._closed = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._inbox: queue.SimpleQueue[PartyMessage] = queue.SimpleQueue()
        self._last_error: str | None = None

    @staticmethod
    def _new_signing_key() -> tuple[bytearray, bytes]:
        Private, _, serialization = _ed25519()
        key = Private.generate()
        private = key.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
        public = key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        return bytearray(private), public

    @staticmethod
    def _public_from_private(private: bytes | bytearray) -> bytes:
        Private, _, serialization = _ed25519()
        return Private.from_private_bytes(bytes(private)).public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )

    @classmethod
    def create(
        cls,
        name: str,
        *,
        relay_url: str = DEFAULT_RELAY,
        relay: Relay | None = None,
    ) -> tuple[PartySession, JoinCode]:
        AESGCM, _, _ = _crypto()
        private, public = cls._new_signing_key()
        key = AESGCM.generate_key(bit_length=256)
        topic = "sleipnir-" + os.urandom(16).hex()
        session: PartySession | None = None
        try:
            session = cls(
                name=name,
                relay_url=relay_url,
                topic=topic,
                key=key,
                leader_public=public,
                signing_key=private,
                relay=relay,
            )
            return session, session.join_code()
        except Exception:
            if session is not None:
                session.close()
            raise
        finally:
            wipe(private)

    @classmethod
    def join(
        cls,
        encoded: bytes | bytearray,
        name: str,
        *,
        relay: Relay | None = None,
        allowed_relays: Sequence[str] = (DEFAULT_RELAY,),
    ) -> PartySession:
        try:
            code = JoinCode.decode(encoded, allowed_relays=allowed_relays)
        finally:
            if isinstance(encoded, bytearray):
                wipe(encoded)
        private, _ = cls._new_signing_key()
        try:
            return cls(
                name=name,
                relay_url=code.relay_url,
                topic=code.topic,
                key=code._key,
                leader_public=code.leader_public,
                signing_key=private,
                relay=relay,
            )
        finally:
            wipe(private)
            code.wipe()

    @property
    def is_leader(self) -> bool:
        return self.member_id == self.leader_id

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def join_code(self) -> JoinCode:
        if not self.is_leader:
            raise PartyPolicyError("only the party leader can export a join code")
        self._require_open()
        return JoinCode(
            self.relay_url,
            self.topic,
            self.leader_public,
            bytearray(self._key),
        )

    def _require_open(self) -> None:
        if self._closed:
            raise PartyError("party session is closed")

    def _sign(self, body: bytes) -> bytes:
        Private, _, _ = _ed25519()
        return Private.from_private_bytes(bytes(self._signing_key)).sign(body)

    def _encode_message(
        self,
        *,
        kind: MessageKind,
        text: str,
        recipient: str | None,
        mode: PartyMode | None = None,
        claimed_sender: str | None = None,
    ) -> str:
        self._require_open()
        if len(text) > MAX_TEXT_CHARS:
            raise PartyPolicyError(f"party message is too long (maximum {MAX_TEXT_CHARS} characters)")
        if recipient is not None and not _MEMBER.fullmatch(recipient):
            raise PartyPolicyError("invalid party recipient")
        body = {
            "v": PROTOCOL_VERSION,
            "id": uuid.uuid4().hex,
            "at": int(time.time()),
            "kind": kind.value,
            "sender": claimed_sender or self.member_id,
            "public": _b64(self.public_key),
            "name": self.name,
            "to": recipient,
            "text": "".join(ch for ch in text if ch.isprintable() or ch in "\n\t"),
            "mode": mode.value if mode is not None else None,
        }
        signed = {"body": body, "signature": _b64(self._sign(_canonical(body)))}
        nonce = os.urandom(12)
        AESGCM, _, _ = _crypto()
        ciphertext = AESGCM(bytes(self._key)).encrypt(
            nonce, _canonical(signed), f"sleipnir-party-v1:{self.topic}".encode()
        )
        wire = _WIRE_PREFIX + _b64(nonce + ciphertext)
        if len(wire.encode("ascii")) > MAX_WIRE_BYTES:
            raise PartyPolicyError("encrypted party message exceeds the relay limit")
        return wire

    def _decode_message(self, wire: str) -> PartyMessage:
        if not wire.startswith(_WIRE_PREFIX) or len(wire) > MAX_WIRE_BYTES:
            raise PartyProtocolError("not a bounded Sleipnir party payload")
        packed = _unb64(wire[len(_WIRE_PREFIX) :])
        if len(packed) < 12 + 16:
            raise PartyProtocolError("truncated party payload")
        nonce, ciphertext = packed[:12], packed[12:]
        AESGCM, InvalidTag, InvalidSignature = _crypto()
        try:
            raw = AESGCM(bytes(self._key)).decrypt(
                nonce, ciphertext, f"sleipnir-party-v1:{self.topic}".encode()
            )
        except InvalidTag as error:
            raise PartyProtocolError("party payload did not authenticate") from error
        try:
            signed = json.loads(raw)
            body = signed["body"]
            signature = _unb64(signed["signature"])
            public = _unb64(body["public"])
            sender = str(body["sender"])
            if len(public) != 32 or sender != _member_id(public):
                raise PartyProtocolError("party sender identity does not match its signing key")
            _, Public, _ = _ed25519()
            Public.from_public_bytes(public).verify(signature, _canonical(body))
            kind = MessageKind(body["kind"])
            mode = PartyMode(body["mode"]) if body.get("mode") is not None else None
            received_text = str(body["text"])
            message = PartyMessage(
                id=str(body["id"]),
                sent_at=int(body["at"]),
                kind=kind,
                sender=sender,
                sender_name=_clean_name(str(body["name"])),
                recipient=str(body["to"]) if body.get("to") is not None else None,
                text="".join(
                    ch for ch in received_text if ch.isprintable() or ch in "\n\t"
                ),
                mode=mode,
            )
        except PartyProtocolError:
            raise
        except InvalidSignature as error:
            raise PartyProtocolError("party message signature is invalid") from error
        except (KeyError, TypeError, ValueError, UnicodeError) as error:
            raise PartyProtocolError("malformed authenticated party message") from error
        if not re.fullmatch(r"[0-9a-f]{32}", message.id):
            raise PartyProtocolError("invalid party message id")
        if message.recipient is not None and not _MEMBER.fullmatch(message.recipient):
            raise PartyProtocolError("invalid authenticated party recipient")
        if len(message.text) > MAX_TEXT_CHARS:
            raise PartyProtocolError("authenticated party text exceeds its bound")
        if message.sender == self.leader_id and public != self.leader_public:
            raise PartyProtocolError("party leader identity is not the pinned creator key")
        if message.kind in {MessageKind.MODE, MessageKind.ASSIGNMENT}:
            if message.sender != self.leader_id or public != self.leader_public:
                raise PartyProtocolError("only the pinned party leader may set hierarchy")
        return message

    def _publish(
        self,
        kind: MessageKind,
        text: str = "",
        *,
        recipient: str | None = None,
        mode: PartyMode | None = None,
    ) -> str:
        wire = self._encode_message(
            kind=kind, text=text, recipient=recipient, mode=mode
        )
        message_id = self._relay.publish(self.topic, wire)
        audit.record(
            "party.sent",
            {
                "kind": kind.value,
                "recipient": recipient or "all",
                "chars": len(text),
            },
        )
        return message_id

    def say(self, text: str, *, recipient: str | None = None) -> str:
        if self.mode is PartyMode.DELEGATE and not self.is_leader:
            if recipient not in (None, self.leader_id):
                raise PartyPolicyError(
                    "delegate-mode members report to the leader, not sideways"
                )
            recipient = self.leader_id
        return self._publish(MessageKind.CHAT, text, recipient=recipient)

    def question(self, text: str, *, recipient: str | None = None) -> str:
        if self.mode is PartyMode.DELEGATE and not self.is_leader:
            if recipient not in (None, self.leader_id):
                raise PartyPolicyError(
                    "delegate-mode members question the leader, not each other"
                )
            recipient = self.leader_id
        return self._publish(MessageKind.QUESTION, text, recipient=recipient)

    def reply(self, text: str, *, recipient: str) -> str:
        if (
            self.mode is PartyMode.DELEGATE
            and not self.is_leader
            and recipient != self.leader_id
        ):
            raise PartyPolicyError(
                "delegate-mode members reply to the leader, not sideways"
            )
        return self._publish(MessageKind.REPLY, text, recipient=recipient)

    def status(self, text: str) -> str:
        recipient = self.leader_id if not self.is_leader else None
        return self._publish(MessageKind.STATUS, text, recipient=recipient)

    def set_mode(self, mode: PartyMode | str) -> str:
        if not self.is_leader:
            raise PartyPolicyError("only the party leader can set the hierarchy mode")
        selected = PartyMode(mode)
        message_id = self._publish(MessageKind.MODE, selected.value, mode=selected)
        self.mode = selected
        return message_id

    def assign(self, member: str | None, text: str) -> str:
        if not self.is_leader:
            raise PartyPolicyError("only the party leader can delegate assignments")
        return self._publish(MessageKind.ASSIGNMENT, text, recipient=member)

    def poll(self, *, strict: bool = False) -> tuple[PartyMessage, ...]:
        self._require_open()
        accepted: list[PartyMessage] = []
        for record in self._relay.poll(self.topic, self._last_relay_id):
            self._last_relay_id = record.id
            try:
                message = self._decode_message(record.payload)
            except PartyProtocolError:
                if strict:
                    raise
                continue
            if message.id in self._seen:
                continue
            self._seen[message.id] = None
            while len(self._seen) > MAX_REPLAY_IDS:
                self._seen.pop(next(iter(self._seen)))
            if message.sender == self.member_id:
                continue
            if message.recipient not in (None, self.member_id):
                continue
            if (
                self.mode is PartyMode.DELEGATE
                and message.sender != self.leader_id
                and message.kind
                in {
                    MessageKind.CHAT,
                    MessageKind.QUESTION,
                    MessageKind.REPLY,
                    MessageKind.STATUS,
                }
                and message.recipient != self.leader_id
            ):
                # Sender-side routing is convenience, not a trust boundary. A
                # modified member still has a valid signing key, so enforce the
                # hierarchy again when authenticated traffic is received.
                if strict:
                    raise PartyProtocolError(
                        "delegate-mode member message was not addressed to the leader"
                    )
                continue
            if message.kind is MessageKind.HELLO:
                self.members[message.sender] = message.sender_name
            elif message.kind is MessageKind.LEAVE:
                self.members.pop(message.sender, None)
            elif message.kind is MessageKind.MODE and message.mode is not None:
                self.mode = message.mode
            accepted.append(message)
        return tuple(accepted)

    def start(self) -> None:
        """Announce this member and poll the relay in a daemon thread."""
        self._require_open()
        if self._thread is not None:
            return
        self._publish(MessageKind.HELLO, self.name)
        self._thread = threading.Thread(
            target=self._listen, name=f"sleipnir-party-{self.member_id}", daemon=True
        )
        self._thread.start()

    def _listen(self) -> None:
        while not self._stop.is_set():
            try:
                for message in self.poll():
                    self._inbox.put(message)
                self._last_error = None
            except PartyError as error:
                self._last_error = str(error)
            self._stop.wait(POLL_INTERVAL_S)

    def drain(self) -> tuple[PartyMessage, ...]:
        messages: list[PartyMessage] = []
        while True:
            try:
                messages.append(self._inbox.get_nowait())
            except queue.Empty:
                return tuple(messages)

    def close(self) -> None:
        if self._closed:
            return
        self._stop.set()
        try:
            if self._thread is not None:
                # Relay publication and its audit are both best-effort during
                # teardown. Neither may skip local secret destruction.
                with contextlib.suppress(Exception):
                    self._publish(MessageKind.LEAVE, self.name)
            close = getattr(self._relay, "close", None)
            if callable(close):
                with contextlib.suppress(Exception):
                    close()
            if self._thread is not None:
                with contextlib.suppress(Exception):
                    self._thread.join(timeout=2.0)
        finally:
            wipe(self._key)
            wipe(self._signing_key)
            self._closed = True


def copy_join_code(code: JoinCode, *, run: Any = subprocess.run) -> None:
    """Copy a join credential without putting it in argv, stdout, or a file."""
    if sys.platform == "darwin":
        candidates = ("pbcopy",)
    elif sys.platform == "win32":
        candidates = ("clip.exe", "clip")
    else:
        candidates = ("wl-copy", "xclip")
    executable = next((shutil.which(name) for name in candidates if shutil.which(name)), None)
    if executable is None:
        raise PartyError(
            "no clipboard writer is available; install wl-clipboard, pbcopy, or clip.exe"
        )
    encoded = code.export()
    try:
        args = [executable]
        if Path(executable).name == "xclip":
            args += ["-selection", "clipboard"]
        result = run(args, input=encoded, capture_output=True, check=False, timeout=10)
        if result.returncode != 0:
            raise PartyError("could not copy the party join code to the clipboard")
        audit.record("party.join_code_copied", {"bytes": len(encoded)})
    finally:
        wipe(encoded)


__all__ = [
    "DEFAULT_RELAY",
    "MAX_TEXT_CHARS",
    "JoinCode",
    "MessageKind",
    "NtfyRelay",
    "PartyCodeError",
    "PartyDependencyError",
    "PartyError",
    "PartyMessage",
    "PartyMode",
    "PartyPolicyError",
    "PartyProtocolError",
    "PartySession",
    "RelayRecord",
    "copy_join_code",
    "wipe",
]
