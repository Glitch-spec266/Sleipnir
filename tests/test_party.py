"""Encrypted cross-machine party transport and hierarchy policy."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from sleipnir import party


class MemoryRelay:
    """The relay boundary, with no network and no knowledge of plaintext."""

    def __init__(self) -> None:
        self.records: list[party.RelayRecord] = []

    def publish(self, topic: str, payload: str) -> str:
        message_id = f"m{len(self.records) + 1}"
        self.records.append(party.RelayRecord(message_id, payload))
        return message_id

    def poll(self, topic: str, since: str | None) -> tuple[party.RelayRecord, ...]:
        start = 0
        if since is not None:
            ids = [record.id for record in self.records]
            start = ids.index(since) + 1 if since in ids else 0
        return tuple(self.records[start:])


def _pair() -> tuple[party.PartySession, party.PartySession, MemoryRelay]:
    relay = MemoryRelay()
    leader, code = party.PartySession.create("lead", relay=relay)
    joiner = party.PartySession.join(code.consume(), "worker", relay=relay)
    return leader, joiner, relay


def test_join_code_is_redacted_and_round_trips() -> None:
    leader, code = party.PartySession.create("lead", relay=MemoryRelay())
    encoded = code.export()
    try:
        assert b"ntfy.sh" not in repr(code).encode()
        parsed = party.JoinCode.decode(encoded)
        assert parsed.topic == leader.topic
        assert parsed.leader_id == leader.member_id
    finally:
        party.wipe(encoded)
        code.wipe()
        leader.close()


def test_join_consumes_a_mutable_join_credential() -> None:
    relay = MemoryRelay()
    leader, code = party.PartySession.create("lead", relay=relay)
    encoded = code.consume()
    joiner = party.PartySession.join(encoded, "worker", relay=relay)
    try:
        assert encoded == bytearray()
    finally:
        leader.close()
        joiner.close()


def test_join_code_rejects_an_unapproved_relay() -> None:
    _, code = party.PartySession.create(
        "lead", relay=MemoryRelay(), relay_url="https://relay.example"
    )
    encoded = code.export()
    try:
        with pytest.raises(party.PartyCodeError, match="relay"):
            party.JoinCode.decode(encoded)
        assert party.JoinCode.decode(
            encoded, allowed_relays=("https://relay.example",)
        ).relay_url == "https://relay.example"
    finally:
        party.wipe(encoded)
        code.wipe()


def test_relay_only_receives_authenticated_ciphertext() -> None:
    leader, joiner, relay = _pair()
    try:
        leader.say("a private coordination sentence")
        wire = relay.records[-1].payload
        assert "private coordination" not in wire
        assert wire.startswith("sp1.")
        assert joiner.poll()[-1].text == "a private coordination sentence"
    finally:
        leader.close()
        joiner.close()


def test_ciphertext_tampering_is_rejected() -> None:
    leader, joiner, relay = _pair()
    try:
        leader.say("unchanged")
        original = relay.records[-1]
        packed = bytearray(party._unb64(original.payload.removeprefix("sp1.")))
        packed[-1] ^= 1
        relay.records[-1] = replace(original, payload="sp1." + party._b64(packed))
        with pytest.raises(party.PartyProtocolError, match="authenticate"):
            joiner.poll(strict=True)
    finally:
        leader.close()
        joiner.close()


def test_messages_are_deduplicated_and_targeted() -> None:
    leader, joiner, relay = _pair()
    third_code = leader.join_code()
    third = party.PartySession.join(third_code.consume(), "third", relay=relay)
    try:
        leader.say("only worker", recipient=joiner.member_id)
        assert [message.text for message in joiner.poll()] == ["only worker"]
        assert joiner.poll() == ()
        assert third.poll() == ()
    finally:
        leader.close()
        joiner.close()
        third.close()


def test_only_the_cryptographically_pinned_leader_can_set_hierarchy() -> None:
    leader, joiner, _ = _pair()
    try:
        leader.set_mode(party.PartyMode.DELEGATE)
        assert joiner.poll()[-1].mode is party.PartyMode.DELEGATE
        assert joiner.mode is party.PartyMode.DELEGATE
        with pytest.raises(party.PartyPolicyError, match="leader"):
            joiner.set_mode(party.PartyMode.COLLABORATE)
        with pytest.raises(party.PartyPolicyError, match="leader"):
            joiner.assign(leader.member_id, "pretend to lead")
    finally:
        leader.close()
        joiner.close()


def test_leader_can_delegate_one_task_to_one_member() -> None:
    leader, joiner, _ = _pair()
    try:
        leader.set_mode(party.PartyMode.DELEGATE)
        joiner.poll()
        leader.assign(joiner.member_id, "review the Windows backend")
        assignment = joiner.poll()[-1]
        assert assignment.kind is party.MessageKind.ASSIGNMENT
        assert assignment.recipient == joiner.member_id
        assert assignment.text == "review the Windows backend"
    finally:
        leader.close()
        joiner.close()


def test_delegate_mode_routes_member_chat_up_to_the_leader() -> None:
    leader, joiner, _ = _pair()
    try:
        leader.set_mode(party.PartyMode.DELEGATE)
        joiner.poll()
        joiner.say("finished my part")
        received = leader.poll()[-1]
        assert received.recipient == leader.member_id
        assert received.text == "finished my part"
    finally:
        leader.close()
        joiner.close()


def test_delegate_mode_routes_questions_up_and_refuses_sideways_replies() -> None:
    leader, joiner, relay = _pair()
    third = party.PartySession.join(leader.join_code().consume(), "third", relay=relay)
    try:
        leader.set_mode(party.PartyMode.DELEGATE)
        joiner.poll()
        third.poll()
        joiner.question("what next?")
        assert leader.poll()[-1].recipient == leader.member_id
        with pytest.raises(party.PartyPolicyError, match="sideways"):
            joiner.reply("peer reply", recipient=third.member_id)
    finally:
        leader.close()
        joiner.close()
        third.close()


def test_delegate_mode_rejects_a_signed_but_sideways_member_message() -> None:
    leader, joiner, relay = _pair()
    third = party.PartySession.join(leader.join_code().consume(), "third", relay=relay)
    try:
        leader.set_mode(party.PartyMode.DELEGATE)
        joiner.poll()
        third.poll()
        forged_route = joiner._encode_message(
            kind=party.MessageKind.CHAT,
            text="sideways",
            recipient=None,
        )
        relay.publish(leader.topic, forged_route)
        with pytest.raises(party.PartyProtocolError, match="delegate-mode"):
            third.poll(strict=True)
    finally:
        leader.close()
        joiner.close()
        third.close()


def test_failed_mode_publish_does_not_change_local_hierarchy() -> None:
    leader, _, relay = _pair()
    try:
        def fail_publish(topic: str, payload: str) -> str:
            raise party.PartyError("offline")

        relay.publish = fail_publish  # type: ignore[method-assign]
        with pytest.raises(party.PartyError, match="offline"):
            leader.set_mode(party.PartyMode.DELEGATE)
        assert leader.mode is party.PartyMode.COLLABORATE
    finally:
        leader.close()


def test_leader_can_broadcast_one_assignment_to_all_delegates() -> None:
    leader, joiner, _ = _pair()
    try:
        leader.assign(None, "all agents inspect the same boundary")
        assignment = joiner.poll()[-1]
        assert assignment.kind is party.MessageKind.ASSIGNMENT
        assert assignment.recipient is None
    finally:
        leader.close()
        joiner.close()


def test_a_member_cannot_spoof_the_leader_even_with_the_shared_aead_key() -> None:
    leader, joiner, relay = _pair()
    try:
        forged = joiner._encode_message(
            kind=party.MessageKind.MODE,
            text="delegate",
            recipient=None,
            claimed_sender=leader.member_id,
        )
        relay.publish(leader.topic, forged)
        with pytest.raises(party.PartyProtocolError, match="identity"):
            leader.poll(strict=True)
    finally:
        leader.close()
        joiner.close()


def test_message_shape_has_no_plan_or_artifact_channel() -> None:
    fields = set(party.PartyMessage.__dataclass_fields__)
    assert "plan" not in fields
    assert "artifacts" not in fields
    assert "transcript" not in fields
    assert fields == {
        "id", "sent_at", "kind", "sender", "sender_name", "recipient", "text", "mode"
    }


def test_ntfy_relay_uses_polling_and_never_places_payload_in_a_url() -> None:
    calls: list[tuple[str, str, object]] = []

    class Response:
        status_code = 200
        content = b'{"id":"n1","event":"message","message":"sp1.abc"}\n'

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {"id": "n2"}

    class Client:
        def post(self, url, **kwargs):
            calls.append(("POST", url, kwargs))
            return Response()

        def get(self, url, **kwargs):
            calls.append(("GET", url, kwargs))
            return Response()

    relay = party.NtfyRelay("https://ntfy.sh", client=Client())
    topic = "sleipnir-" + "a" * 32
    assert relay.publish(topic, "sp1.secret-wire") == "n2"
    records = relay.poll(topic, "n0")
    assert records == (party.RelayRecord("n1", "sp1.abc"),)
    assert calls[0][1] == f"https://ntfy.sh/{topic}"
    assert "secret-wire" not in calls[0][1]
    assert calls[1][2]["params"] == {"poll": "1", "since": "n0"}


def test_wire_payload_is_bounded() -> None:
    leader, _, _ = _pair()
    try:
        with pytest.raises(party.PartyPolicyError, match="too long"):
            leader.say("x" * (party.MAX_TEXT_CHARS + 1))
    finally:
        leader.close()


def test_close_wipes_keys_even_when_leave_audit_fails(monkeypatch) -> None:
    leader, joiner, _ = _pair()

    class Thread:
        def join(self, *, timeout):
            return None

    leader._thread = Thread()  # type: ignore[assignment]
    monkeypatch.setattr(
        party.audit,
        "record",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("audit unavailable")),
    )
    try:
        leader.close()
        assert leader._key == bytearray()
        assert leader._signing_key == bytearray()
        assert leader._closed is True
    finally:
        joiner.close()
