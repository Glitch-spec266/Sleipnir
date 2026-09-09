from __future__ import annotations

from sleipnir.gui_history import EncryptedHistory


def test_history_is_encrypted_at_rest_and_round_trips(tmp_path):
    history = EncryptedHistory(tmp_path / "history.enc.jsonl", tmp_path / "history.key")
    history.append({"role": "operator", "text": "private project instruction"})
    history.append({"role": "sleipnir", "text": "finished safely"})

    raw = (tmp_path / "history.enc.jsonl").read_bytes()
    assert b"private project instruction" not in raw
    assert history.read() == [
        {"role": "operator", "text": "private project instruction"},
        {"role": "sleipnir", "text": "finished safely"},
    ]
    assert (tmp_path / "history.key").stat().st_mode & 0o077 == 0


def test_history_tolerates_one_torn_trailing_record(tmp_path):
    history = EncryptedHistory(tmp_path / "history.enc.jsonl", tmp_path / "history.key")
    history.append({"role": "operator", "text": "keep this"})
    with (tmp_path / "history.enc.jsonl").open("ab") as handle:
        handle.write(b"torn")

    assert history.read() == [{"role": "operator", "text": "keep this"}]
