from __future__ import annotations

import json

from sleipnir import platform
from sleipnir.gui_history import EncryptedHistory, main


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
    assert platform.path_is_private(tmp_path / "history.key")


def test_history_tolerates_one_torn_trailing_record(tmp_path):
    history = EncryptedHistory(tmp_path / "history.enc.jsonl", tmp_path / "history.key")
    history.append({"role": "operator", "text": "keep this"})
    with (tmp_path / "history.enc.jsonl").open("ab") as handle:
        handle.write(b"torn")

    assert history.read() == [{"role": "operator", "text": "keep this"}]


def test_history_cli_returns_decrypted_entries_only_to_native_stdout(tmp_path, capsys):
    path = tmp_path / "history.enc.jsonl"
    key = tmp_path / "history.key"
    EncryptedHistory(path, key).append({"role": "operator", "text": "resume safely"})

    assert main(["--history", str(path), "--history-key", str(key)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "status": "complete",
        "entries": [{"role": "operator", "text": "resume safely"}],
    }
