"""Capability tests are hermetic by construction.

Nothing here may inject a real keystroke, move the real pointer, or open a real
browser: a test suite that types into whatever window happens to be focused is
a hazard, not a test.  Every host call is intercepted at the subprocess
boundary — the same discipline the executor tests use for provider spawns.
"""

from __future__ import annotations

import json

import pytest

from sleipnir.capabilities import audit, browser, clipboard, computer, secrets


@pytest.fixture
def audit_log(tmp_path, monkeypatch):
    path = tmp_path / "audit.jsonl"
    monkeypatch.setattr(audit, "DEFAULT_LOG", path)
    return path


@pytest.fixture
def fake_ydotool(monkeypatch):
    """Capture ydotool argv instead of running it."""
    calls: list[list[str]] = []

    def _run(argv, **kwargs):
        calls.append(list(argv))

        class Result:
            returncode = 0
            stderr = ""
            stdout = ""

        return Result()

    monkeypatch.setattr(computer.subprocess, "run", _run)
    monkeypatch.setattr(computer, "ensure_daemon", lambda *a, **k: None)
    return calls


def _entries(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


# --- audit ---------------------------------------------------------------


def test_audit_never_writes_a_secret_value(audit_log):
    audit.record("secret.test", {"password": "hunter2", "token": "sk-live-abc", "url": "x"})
    body = audit_log.read_text()
    assert "hunter2" not in body
    assert "sk-live-abc" not in body
    assert "redacted" in body
    assert "x" in body  # non-sensitive detail is kept


def test_typed_text_is_recorded_by_length_not_content(audit_log, fake_ydotool):
    computer.type_text("my-api-key-value")
    body = audit_log.read_text()
    assert "my-api-key-value" not in body
    assert '"chars": 16' in body


# --- keyboard / mouse ----------------------------------------------------


def test_chord_releases_modifiers_in_reverse_order(audit_log, fake_ydotool):
    computer.key("ctrl", "shift", "t")
    argv = fake_ydotool[0]
    assert argv[:2] == ["ydotool", "key"]
    # ctrl(29) shift(42) t(20) down, then released t, shift, ctrl.
    assert argv[2:] == ["29:1", "42:1", "20:1", "20:0", "42:0", "29:0"]


def test_copy_and_paste_use_linux_terminal_chords_without_touching_payload(
    audit_log, fake_ydotool
):
    computer.copy()
    computer.paste()
    assert fake_ydotool[0][2:] == ["29:1", "42:1", "46:1", "46:0", "42:0", "29:0"]
    assert fake_ydotool[1][2:] == ["29:1", "42:1", "47:1", "47:0", "42:0", "29:0"]
    body = audit_log.read_text()
    assert "desktop.clipboard_copy" in body
    assert "desktop.clipboard_paste" in body


def test_unknown_key_is_refused_rather_than_silently_dropped(audit_log, fake_ydotool):
    with pytest.raises(computer.CapabilityError, match="unknown key"):
        computer.key("ctrl", "hyperspace")
    assert fake_ydotool == []


def test_unknown_mouse_button_is_refused(audit_log, fake_ydotool):
    with pytest.raises(computer.CapabilityError, match="unknown mouse button"):
        computer.click("elbow")


def test_type_passes_a_double_dash_so_text_cannot_become_flags(audit_log, fake_ydotool):
    computer.type_text("--help --socket-path=/tmp/evil")
    argv = fake_ydotool[0]
    assert "--" in argv
    assert argv.index("--") < argv.index("--help --socket-path=/tmp/evil")


def test_probe_reports_notes_instead_of_raising(monkeypatch):
    monkeypatch.setattr(computer.shutil, "which", lambda name: None)
    result = computer.probe()
    assert result.ready is False
    assert any("ydotool" in note for note in result.notes)


# --- clipboard -----------------------------------------------------------


def test_wayland_clipboard_reads_text_without_logging_it(audit_log, monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        stdout = b"text/plain;charset=utf-8\n" if "--list-types" in argv else b"private text"
        return type("Result", (), {"returncode": 0, "stdout": stdout, "stderr": b""})()

    monkeypatch.setattr(clipboard.shutil, "which", lambda name: "/usr/bin/wl-paste")
    monkeypatch.setattr(clipboard.subprocess, "run", fake_run)
    payload = clipboard.read()

    assert payload.kind == "text"
    assert payload.text == "private text"
    assert "--no-newline" in calls[1]
    assert "private text" not in audit_log.read_text()


def test_wayland_clipboard_materialises_an_image_privately(audit_log, tmp_path, monkeypatch):
    def fake_run(argv, **kwargs):
        stdout = b"image/png\ntext/plain\n" if "--list-types" in argv else b"\x89PNGpixels"
        return type("Result", (), {"returncode": 0, "stdout": stdout, "stderr": b""})()

    monkeypatch.setattr(clipboard.shutil, "which", lambda name: "/usr/bin/wl-paste")
    monkeypatch.setattr(clipboard.subprocess, "run", fake_run)
    payload = clipboard.read(destination_dir=tmp_path)

    assert payload.kind == "image"
    assert payload.mime_type == "image/png"
    assert payload.path is not None and payload.path.read_bytes() == b"\x89PNGpixels"
    assert payload.path.stat().st_mode & 0o777 == 0o600


def test_grim_is_not_selected_on_kde(monkeypatch):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    monkeypatch.setattr(computer.shutil, "which", lambda name: f"/usr/bin/{name}" if name in ("grim", "spectacle") else None)
    assert computer._screenshot_tool() == "spectacle"


def test_grim_is_selected_when_it_is_the_only_option_off_kde(monkeypatch):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "sway")
    monkeypatch.setattr(computer.shutil, "which", lambda name: "/usr/bin/grim" if name == "grim" else None)
    assert computer._screenshot_tool() == "grim"


# --- secrets -------------------------------------------------------------


def test_secret_never_renders_its_value():
    secret = secrets.Secret("openrouter", bytearray(b"sk-or-v1-topsecret"))
    for rendering in (repr(secret), str(secret), f"{secret}", f"{secret!r}", f"{secret!s}"):
        assert "topsecret" not in rendering
    assert "openrouter" in repr(secret)


def test_secret_is_wiped_after_one_use():
    secret = secrets.Secret("token", bytearray(b"abc123"))
    assert secret.consume() == "abc123"
    assert len(secret) == 0
    assert bool(secret) is False
    with pytest.raises(secrets.SecretConsumed):
        secret.consume()


def test_secret_context_manager_wipes_even_when_unused():
    with secrets.Secret("pin", bytearray(b"0000")) as secret:
        assert len(secret) == 4
    assert len(secret) == 0


def test_capture_records_only_the_label_and_length(audit_log, monkeypatch):
    monkeypatch.setattr(secrets.getpass, "getpass", lambda *a, **k: "correct horse")
    secret = secrets.capture("github password")
    entry = _entries(audit_log)[0]
    assert entry["action"] == "secret.captured"
    assert entry["detail"] == {"label": "github password", "length": 13}
    assert "correct horse" not in audit_log.read_text()
    assert secret.consume() == "correct horse"


def test_typing_a_secret_wipes_it_and_logs_nothing_sensitive(audit_log, fake_ydotool):
    secret = secrets.Secret("aws key", bytearray(b"AKIAsecretvalue"))
    secrets.type_into_focused_window(secret, submit=True)
    assert len(secret) == 0
    body = audit_log.read_text()
    assert "AKIAsecretvalue" not in body
    assert '"submitted": true' in body


# --- browser -------------------------------------------------------------


def test_browser_refuses_to_act_before_start():
    with pytest.raises(computer.CapabilityError, match="not started"):
        _ = browser.Browser().page


def test_browser_profile_defaults_outside_the_repo():
    # A logged-in browser profile in the working tree would be committed by
    # accident sooner or later; keep it in the user's home.
    assert "Sleipnir" not in str(browser.DEFAULT_PROFILE)
    assert browser.DEFAULT_PROFILE.name == "browser-profile"


def test_browser_pid_is_published_without_following_an_old_symlink(tmp_path):
    pid_file = tmp_path / "browser.pid"
    outside = tmp_path / "outside"
    outside.write_text("do not overwrite", encoding="utf-8")
    pid_file.symlink_to(outside)
    browser._publish_pid(1234, pid_file)
    assert pid_file.is_symlink() is False
    assert pid_file.read_text(encoding="ascii") == "1234"
    assert outside.read_text(encoding="utf-8") == "do not overwrite"


def test_browser_pid_reader_rejects_symlink_and_implausible_pid(tmp_path):
    real = tmp_path / "real"
    real.write_text("1234", encoding="ascii")
    linked = tmp_path / "linked"
    linked.symlink_to(real)
    assert browser._read_pid(linked) is None
    real.write_text("1", encoding="ascii")
    assert browser._read_pid(real) is None


def test_browser_pid_must_match_the_expected_port_and_profile(tmp_path):
    proc = tmp_path / "proc"
    cmdline = proc / "4321" / "cmdline"
    cmdline.parent.mkdir(parents=True)
    profile = tmp_path / "profile"
    cmdline.write_bytes(
        b"/chromium\0--remote-debugging-port=9333\0"
        + f"--user-data-dir={profile}".encode()
        + b"\0"
    )
    assert browser._pid_matches_browser(4321, profile, proc_root=proc)
    assert not browser._pid_matches_browser(4321, tmp_path / "other", proc_root=proc)

    cmdline.write_bytes(b"/unrelated\0--remote-debugging-port=9333\0")
    assert not browser._pid_matches_browser(4321, profile, proc_root=proc)
