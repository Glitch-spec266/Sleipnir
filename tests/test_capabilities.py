"""Capability tests are hermetic by construction.

Nothing here may inject a real keystroke, move the real pointer, or open a real
browser: a test suite that types into whatever window happens to be focused is
a hazard, not a test.  Every host call is intercepted — at the subprocess
boundary for the ydotool backend, at the single ``SendInput`` seam for the
Windows one, and at the backend module itself for the platform-neutral public
layer.

The file is in three parts on purpose, mirroring the package:

* **public layer** — validation and auditing, exercised against a fake backend
  so these run identically on both platforms;
* **``_linux``** — ydotool argv. Runs everywhere: the module has no OS-gated
  imports, so a Windows machine still checks the Linux backend's logic;
* **``_windows``** — SendInput/GDI. Windows only, because importing it needs
  ``user32``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import subprocess

import pytest

from sleipnir import cli
from sleipnir.capabilities import audit, browser, clipboard, computer, ios, secrets
from sleipnir.capabilities.computer import _linux, _png

windows_only = pytest.mark.skipif(
    sys.platform != "win32", reason="Windows SendInput/GDI backend"
)


@pytest.fixture
def audit_log(tmp_path, monkeypatch):
    path = tmp_path / "audit.jsonl"
    monkeypatch.setattr(audit, "DEFAULT_LOG", path)
    return path


class _Recorder:
    """Stand-in for whichever backend this machine has.

    Records the call the public layer decided to make, which is the only
    thing the public layer is responsible for — the injection itself is the
    backends' business and is tested against each backend directly below.
    """

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def type_text(self, text: str, *, key_delay_ms: int) -> None:
        self.calls.append(("type_text", text, key_delay_ms))

    def key_chord(self, codes: list[int]) -> None:
        self.calls.append(("key_chord", list(codes)))

    def move_mouse(self, x: int, y: int) -> None:
        self.calls.append(("move_mouse", x, y))

    def click(self, button: str) -> None:
        self.calls.append(("click", button))

    def scroll(self, amount: int) -> None:
        self.calls.append(("scroll", amount))

    def screenshot(self, destination) -> str:
        destination.write_bytes(b"\x89PNG\r\n\x1a\n")
        self.calls.append(("screenshot", destination))
        return "fake"

    def record_screen(self, destination, *, duration_s: float) -> str:
        destination.write_bytes(b"video")
        self.calls.append(("record_screen", destination, duration_s))
        return "fake-recorder"


@pytest.fixture
def fake_backend(monkeypatch):
    """Intercept the platform backend, keeping validation and audit real."""
    recorder = _Recorder()
    monkeypatch.setattr(computer, "_impl", recorder)
    monkeypatch.setattr(computer, "ensure_daemon", lambda *a, **k: None)
    return recorder


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

    monkeypatch.setattr(_linux.subprocess, "run", _run)
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


def test_typed_text_is_recorded_by_length_not_content(audit_log, fake_backend):
    computer.type_text("my-api-key-value")
    body = audit_log.read_text()
    assert "my-api-key-value" not in body
    assert '"chars": 16' in body


def test_audit_log_never_follows_a_precreated_symlink(tmp_path):
    outside = tmp_path / "outside"
    outside.write_text("keep", encoding="utf-8")
    linked = tmp_path / "audit.jsonl"
    linked.symlink_to(outside)
    with pytest.raises(OSError):
        audit.record("desktop.test", log=linked)
    assert outside.read_text(encoding="utf-8") == "keep"


# --- keyboard / mouse ----------------------------------------------------

def test_every_public_action_is_audited(audit_log, fake_backend, tmp_path):
    # The reason auditing lives in __init__ and not in the backends: one
    # place to forget, and this test notices if it is forgotten there.
    computer.type_text("hi")
    computer.key("ctrl", "c")
    computer.move_mouse(4, 5)
    computer.click("right")
    computer.scroll(-2)
    computer.screenshot(tmp_path / "shot.png")
    computer.record_screen(tmp_path / "recording.mp4", duration_s=3)
    recorded = [entry["action"] for entry in _entries(audit_log)]
    assert recorded == [
        "desktop.type",
        "desktop.key",
        "desktop.move_mouse",
        "desktop.click",
        "desktop.scroll",
        "desktop.screenshot",
        "desktop.screen_record",
    ]


# --- keyboard / mouse: the platform-neutral contract ----------------------


def test_chord_presses_in_order_and_releases_in_reverse(audit_log, fake_backend):
    # The public layer owns the ordering contract; each backend only has to
    # speak it. Codes are this host's — evdev or VK — so the test asserts
    # against the table rather than hard-coded numbers.
    computer.key("ctrl", "shift", "t")
    assert fake_backend.calls == [
        ("key_chord", [computer.KEYCODES[name] for name in ("ctrl", "shift", "t")])
    ]


@windows_only
def test_key_names_are_the_same_vocabulary_on_both_backends():
    # A name that exists on one platform and not the other would make
    # `sleipnir computer key ...` silently platform-specific. Checked where
    # both backends import at once, which is Windows: `_linux` imports
    # anywhere, `_windows` needs `user32`.
    from sleipnir.capabilities.computer import _windows

    assert set(_windows.KEYCODES) == set(_linux.KEYCODES)
    assert set(_windows.BUTTON_CODES) == set(_linux.BUTTON_CODES)


def test_unknown_key_is_refused_rather_than_silently_dropped(audit_log, fake_backend):
    with pytest.raises(computer.CapabilityError, match="unknown key"):
        computer.key("ctrl", "hyperspace")
    assert fake_backend.calls == []


def test_unknown_mouse_button_is_refused(audit_log, fake_backend):
    with pytest.raises(computer.CapabilityError, match="unknown mouse button"):
        computer.click("elbow")
    assert fake_backend.calls == []


def test_screenshot_returns_the_resolved_path_and_makes_its_parent(
    audit_log, fake_backend, tmp_path
):
    destination = computer.screenshot(tmp_path / "nested" / "shot.png")
    assert destination.exists()
    assert _entries(audit_log)[0]["detail"]["tool"] == "fake"


def test_screen_recording_is_bounded_and_audited(audit_log, fake_backend, tmp_path):
    destination = computer.record_screen(tmp_path / "capture.mp4", duration_s=2.5)

    assert destination.read_bytes() == b"video"
    assert fake_backend.calls == [("record_screen", destination, 2.5)]
    assert _entries(audit_log)[0]["detail"] == {
        "path": str(destination),
        "tool": "fake-recorder",
        "duration_s": 2.5,
    }
    with pytest.raises(computer.CapabilityError, match="between 1 and 3600"):
        computer.record_screen(tmp_path / "too-long.mp4", duration_s=3601)


# --- the ydotool backend -------------------------------------------------


def test_chord_releases_modifiers_in_reverse_order(fake_ydotool):
    _linux.key_chord([_linux.KEYCODES[name] for name in ("ctrl", "shift", "t")])
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


def test_public_type_accepts_text_that_looks_like_flags(audit_log, fake_ydotool):
    computer.type_text("--help --socket-path=/tmp/evil")
    assert "--help --socket-path=/tmp/evil" not in fake_ydotool[0]


def test_type_sends_text_over_stdin_never_the_command_line(monkeypatch):
    captured = {}

    class Result:
        returncode = 0
        stderr = ""

    def fake_run(argv, **kwargs):
        captured["argv"] = list(argv)
        captured.update(kwargs)
        return Result()

    monkeypatch.setattr(_linux.subprocess, "run", fake_run)
    value = "not-a-real credential --help"
    _linux.type_text(value, key_delay_ms=12)
    assert value not in captured["argv"]
    assert captured["argv"][-1] == "--file=-"
    assert captured["input"] == value


def test_type_failure_never_echoes_sensitive_stdin_in_the_error(monkeypatch):
    class Result:
        returncode = 9
        stderr = "failed while typing not-a-real-password"

    monkeypatch.setattr(_linux.subprocess, "run", lambda *args, **kwargs: Result())
    with pytest.raises(computer.CapabilityError) as raised:
        _linux.type_text("not-a-real-password", key_delay_ms=12)
    assert "not-a-real-password" not in str(raised.value)
    assert "exit code 9" in str(raised.value)


def test_probe_reports_notes_instead_of_raising(monkeypatch):
    monkeypatch.setattr(_linux.shutil, "which", lambda name: None)
    result = _linux.probe()
    assert result.ready is False
    assert any("ydotool" in note for note in result.notes)


# --- Linux-native iOS development ---------------------------------------


def test_ios_probe_requires_xtool_swiftpm_manifest_and_project_config(tmp_path, monkeypatch):
    monkeypatch.setattr(ios.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        ios.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0),
    )
    (tmp_path / "Package.swift").write_text("// swift-tools-version: 6.0\n")
    result = ios.probe(tmp_path)
    assert result.ready is False
    assert "xtool.yml" in result.notes[0]

    (tmp_path / "xtool.yml").write_text("version: 1\n")
    assert ios.probe(tmp_path).ready is True


def test_ios_argv_uses_xtool_dev_for_build_and_ipa():
    assert ios.argv("build", executable="/opt/xtool") == ["/opt/xtool", "dev", "build"]
    assert ios.argv("ipa", executable="/opt/xtool") == [
        "/opt/xtool", "dev", "build", "--sign", "--ipa",
    ]


def test_ios_runner_never_uses_a_shell_and_keeps_project_cwd(
    audit_log, tmp_path, monkeypatch
):
    (tmp_path / "Package.swift").write_text("// swift-tools-version: 6.0\n")
    (tmp_path / "xtool.yml").write_text("version: 1\n")
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr(ios.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert ios.run("build", root=tmp_path, run=fake_run) == 0
    command, kwargs = calls[0]
    assert len(calls) == 1
    assert command == ["/usr/bin/xtool", "dev", "build"]
    assert kwargs["cwd"] == str(tmp_path)
    assert kwargs["check"] is False
    assert "shell" not in kwargs
    assert "ios.xtool" in audit_log.read_text(encoding="utf-8")


def test_ios_cli_parser_exposes_no_mac_workflow():
    parsed = cli.build_parser().parse_args(["ios", "ipa", "--project", "/work/app"])
    assert parsed.action == "ipa"
    assert parsed.project == "/work/app"


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


def test_clipboard_image_rejects_a_symlinked_destination(audit_log, tmp_path, monkeypatch):
    def fake_run(argv, **kwargs):
        stdout = b"image/png\n" if "--list-types" in argv else b"pixels"
        return type("Result", (), {"returncode": 0, "stdout": stdout, "stderr": b""})()

    outside = tmp_path / "outside"
    outside.mkdir()
    linked = tmp_path / "clipboard"
    linked.symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(clipboard.shutil, "which", lambda name: "/usr/bin/wl-paste")
    monkeypatch.setattr(clipboard.subprocess, "run", fake_run)
    with pytest.raises(clipboard.ClipboardError, match="unsafe"):
        clipboard.read(destination_dir=linked)
    assert list(outside.iterdir()) == []


def test_grim_is_not_selected_on_kde(monkeypatch):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    monkeypatch.setattr(_linux.shutil, "which", lambda name: f"/usr/bin/{name}" if name in ("grim", "spectacle") else None)
    assert _linux._screenshot_tool() == "spectacle"


def test_grim_is_selected_when_it_is_the_only_option_off_kde(monkeypatch):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "sway")
    monkeypatch.setattr(_linux.shutil, "which", lambda name: "/usr/bin/grim" if name == "grim" else None)
    assert _linux._screenshot_tool() == "grim"


# --- the SendInput backend -----------------------------------------------


@pytest.fixture
def fake_send(monkeypatch):
    """Capture INPUT structs instead of injecting them.

    Only requested by ``windows_only`` tests: importing the backend off
    Windows fails at ``ctypes.WinDLL``, which is an ``AttributeError`` rather
    than the ``ImportError`` an ``importorskip`` would catch.
    """
    from sleipnir.capabilities.computer import _windows

    batches: list[list] = []
    monkeypatch.setattr(_windows, "_send", lambda events: batches.append(list(events)))
    return batches


@windows_only
def test_typed_text_never_becomes_an_argument_at_all(fake_send):
    from sleipnir.capabilities.computer import _windows

    _windows.type_text("--help", key_delay_ms=0)
    # The Linux backend needs a `--` guard because text reaches ydotool as
    # argv. Here there is no argv: every character is a KEYEVENTF_UNICODE
    # scan code, so flag injection is not a shape this backend has.
    units = [batch[0].ki.wScan for batch in fake_send]
    assert "".join(chr(unit) for unit in units) == "--help"
    assert all(batch[0].ki.wVk == 0 for batch in fake_send)


@windows_only
def test_newline_is_typed_as_return_not_as_a_literal_character(fake_send):
    from sleipnir.capabilities.computer import _windows

    _windows.type_text("a\nb", key_delay_ms=0)
    return_batch = fake_send[1]
    assert return_batch[0].ki.wVk == _windows.KEYCODES["enter"]
    assert return_batch[0].ki.wScan == 0


@windows_only
def test_astral_characters_are_sent_as_surrogate_pairs(fake_send):
    from sleipnir.capabilities.computer import _windows

    _windows.type_text("\U0001f600", key_delay_ms=0)
    units = [batch[0].ki.wScan for batch in fake_send]
    assert units == [0xD83D, 0xDE00]


@windows_only
def test_windows_chord_is_one_batch_pressed_then_released_in_reverse(fake_send):
    from sleipnir.platform import _win32
    from sleipnir.capabilities.computer import _windows

    codes = [_windows.KEYCODES[name] for name in ("ctrl", "shift", "t")]
    _windows.key_chord(codes)
    # One batch: a chord split across SendInput calls can be interleaved with
    # another process's input and leave a modifier stuck down.
    assert len(fake_send) == 1
    events = fake_send[0]
    assert [event.ki.wVk for event in events] == codes + list(reversed(codes))
    ups = [bool(event.ki.dwFlags & _win32.KEYEVENTF_KEYUP) for event in events]
    assert ups == [False, False, False, True, True, True]


@windows_only
def test_arrow_keys_are_flagged_extended(fake_send):
    from sleipnir.platform import _win32
    from sleipnir.capabilities.computer import _windows

    _windows.key_chord([_windows.KEYCODES["home"]])
    flags = fake_send[0][0].ki.dwFlags
    # Without the extended flag this delivers as the numpad `7`.
    assert flags & _win32.KEYEVENTF_EXTENDEDKEY


@windows_only
def test_mouse_is_normalised_against_the_whole_virtual_desktop(fake_send, monkeypatch):
    from sleipnir.platform import _win32
    from sleipnir.capabilities.computer import _windows

    # A second monitor to the left of the primary one: the origin is
    # negative, and normalising against the primary monitor would send every
    # click to the wrong screen.
    monkeypatch.setattr(_windows, "virtual_screen", lambda: (-1920, 0, 3840, 1080))
    _windows.move_mouse(-1920, 0)
    event = fake_send[0][0].mi
    assert (event.dx, event.dy) == (0, 0)
    assert event.dwFlags & _win32.MOUSEEVENTF_VIRTUALDESK

    _windows.move_mouse(1919, 1079)
    event = fake_send[1][0].mi
    assert (event.dx, event.dy) == (65535, 65535)


@windows_only
def test_scroll_keeps_positive_meaning_up(fake_send):
    from sleipnir.platform import _win32
    from sleipnir.capabilities.computer import _windows

    _windows.scroll(2)
    assert fake_send[0][0].mi.mouseData == 2 * _win32.WHEEL_DELTA
    _windows.scroll(-1)
    # ``mouseData`` is a DWORD, so a scroll down reads back as the unsigned
    # two's complement of -120 -- which is the bit pattern Windows itself
    # interprets as signed. Asserting the raw field keeps that explicit.
    assert fake_send[1][0].mi.mouseData == (-_win32.WHEEL_DELTA) & 0xFFFFFFFF


@windows_only
def test_click_sends_a_down_then_an_up(fake_send):
    from sleipnir.platform import _win32
    from sleipnir.capabilities.computer import _windows

    _windows.click("right")
    down, up = fake_send[0]
    assert down.mi.dwFlags == _win32.MOUSEEVENTF_RIGHTDOWN
    assert up.mi.dwFlags == _win32.MOUSEEVENTF_RIGHTUP


@windows_only
def test_capture_conversion_drops_alpha_and_swaps_channels():
    from sleipnir.capabilities.computer import _windows

    # GDI hands back BGRA; PNG wants RGB.
    assert _windows._bgra_to_rgb(bytes([1, 2, 3, 255, 4, 5, 6, 0])) == bytes(
        [3, 2, 1, 6, 5, 4]
    )


@windows_only
def test_capture_deselects_the_bitmap_before_getdibits(monkeypatch):
    """MSDN requires the HBITMAP not be selected during GetDIBits."""
    from types import SimpleNamespace
    from sleipnir.capabilities.computer import _windows

    selected: list[int] = []
    old_object = 303

    class FakeGDI:
        def CreateCompatibleDC(self, screen):
            return 101

        def CreateCompatibleBitmap(self, screen, width, height):
            return 202

        def SelectObject(self, dc, obj):
            selected.append(obj)
            return old_object if obj == 202 else 202

        def BitBlt(self, *args):
            return 1

        def GetDIBits(self, dc, bitmap, start, height, buffer, info, colours):
            assert selected[-1] == old_object
            return height

        def DeleteObject(self, bitmap):
            return 1

        def DeleteDC(self, dc):
            return 1

    fake_user = SimpleNamespace(GetDC=lambda _: 99, ReleaseDC=lambda *_: 1)
    monkeypatch.setattr(_windows, "gdi32", FakeGDI())
    monkeypatch.setattr(_windows, "user32", fake_user)
    monkeypatch.setattr(_windows, "virtual_screen", lambda: (0, 0, 2, 2))
    raw, width, height = _windows._capture_bgra()
    assert (len(raw), width, height) == (16, 2, 2)
    assert selected[:2] == [202, old_object]


@windows_only
def test_probe_reports_a_windows_shaped_machine():
    from sleipnir.capabilities.computer import _windows

    result = _windows.probe()
    assert result.session_type == "windows"
    assert result.daemon_running is True  # nothing to start
    assert result.screenshot_tool


# --- the PNG encoder -----------------------------------------------------


def test_png_round_trips_through_a_stdlib_decode():
    import struct
    import zlib

    pixels = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 10, 20, 30])
    blob = _png.encode_rgb(pixels, 2, 2)
    assert blob[:8] == b"\x89PNG\r\n\x1a\n"

    chunks = {}
    position = 8
    while position < len(blob):
        length = struct.unpack(">I", blob[position : position + 4])[0]
        tag = blob[position + 4 : position + 8]
        body = blob[position + 8 : position + 8 + length]
        crc = struct.unpack(">I", blob[position + 8 + length : position + 12 + length])[0]
        # A wrong CRC is the one PNG error a viewer reports as "corrupt file"
        # with no hint which chunk, so it is worth asserting per chunk here.
        assert crc == zlib.crc32(tag + body) & 0xFFFFFFFF, tag
        chunks[tag] = body
        position += 12 + length

    assert list(chunks) == [b"IHDR", b"IDAT", b"IEND"]
    assert struct.unpack(">IIBBBBB", chunks[b"IHDR"]) == (2, 2, 8, 2, 0, 0, 0)
    # Each scanline is prefixed with filter type 0.
    assert zlib.decompress(chunks[b"IDAT"]) == b"\x00" + pixels[:6] + b"\x00" + pixels[6:]


def test_png_refuses_a_buffer_that_does_not_match_the_dimensions():
    with pytest.raises(ValueError, match="expected 12 bytes"):
        _png.encode_rgb(b"\x00" * 11, 2, 2)


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


def test_typing_a_secret_wipes_it_and_logs_nothing_sensitive(audit_log, fake_backend):
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


def test_browser_rejects_a_symlinked_profile_before_launch(tmp_path, monkeypatch):
    outside = tmp_path / "outside"
    outside.mkdir()
    linked = tmp_path / "profile"
    linked.symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(browser, "_cdp_alive", lambda: False)
    with pytest.raises(computer.CapabilityError, match="unsafe browser profile"):
        asyncio.run(browser.ensure_browser(linked))


def test_browser_close_does_not_start_a_browser(audit_log, monkeypatch, capsys):
    monkeypatch.setattr(browser, "stop_browser", lambda: False)

    class MustNotStart:
        def __init__(self, **kwargs):
            raise AssertionError("close must not construct or attach a browser")

    monkeypatch.setattr(browser, "Browser", MustNotStart)
    args = argparse.Namespace(action="close", args=[], headless=False)
    assert asyncio.run(cli.cmd_browser(args)) == 0
    assert "not running" in capsys.readouterr().out


def test_bad_browser_arguments_fail_before_browser_start(monkeypatch):
    class MustNotStart:
        def __init__(self, **kwargs):
            raise AssertionError("invalid input must not construct a browser")

    monkeypatch.setattr(browser, "Browser", MustNotStart)
    args = argparse.Namespace(action="fill", args=["#field"], headless=False)
    with pytest.raises(cli.CliError, match="exactly 2"):
        asyncio.run(cli.cmd_browser(args))


def test_ios_probe_resolves_the_working_directory_when_called(tmp_path, monkeypatch):
    """A default of ``Path.cwd()`` binds at import, not at call.

    The console is long-lived and can move its run root, so a default frozen
    when the module loaded answers confidently about the wrong directory.
    """
    (tmp_path / "Package.swift").write_text("// swift-tools-version:5.9\n")
    (tmp_path / "xtool.yml").write_text("version: 1\n")
    monkeypatch.chdir(tmp_path)

    result = ios.probe()

    assert result.package_manifest is True
    assert result.xtool_config is True
    assert not [note for note in result.notes if "xtool.yml" in note]


@pytest.mark.parametrize("action", ["build", "ipa", "run"])
def test_ios_project_commands_refuse_a_directory_that_is_not_an_xtool_app(tmp_path, action):
    """SwiftPM development actions need the manifest and xtool config."""
    with pytest.raises(ios.IOSCapabilityError, match="not an xtool SwiftPM app"):
        ios.run(action, root=tmp_path, executable="/usr/bin/true",
                run=lambda *a, **k: pytest.fail("xtool must not be invoked"))


@pytest.mark.parametrize(
    "action",
    ["doctor", "setup", "auth", "sdk", "new", "devices", "install", "uninstall", "launch"],
)
def test_ios_host_level_commands_do_not_require_a_project(tmp_path, action):
    """A host-level command is not project-scoped and must stay usable."""
    if action == "doctor":
        pytest.skip("doctor reports rather than dispatching")
    calls: list[list[str]] = []

    class Done:
        returncode = 0

    ios.run(action, root=tmp_path, executable="/usr/bin/true",
            run=lambda argv, **k: (calls.append(argv), Done())[1])
    assert calls, "a host-level command must still reach xtool"


def test_xcode_project_generation_refuses_linux_noop(tmp_path, monkeypatch):
    (tmp_path / "Package.swift").write_text("// swift-tools-version:5.9\n")
    (tmp_path / "xtool.yml").write_text("version: 1\n")
    monkeypatch.setattr(ios.platform, "system", lambda: "Linux")
    with pytest.raises(ios.IOSCapabilityError, match="does nothing on Linux"):
        ios.run("xcodeproj", root=tmp_path, executable="/usr/bin/true")


def test_ios_probe_reports_a_missing_darwin_sdk(tmp_path, monkeypatch):
    (tmp_path / "Package.swift").write_text("// swift-tools-version:5.9\n")
    (tmp_path / "xtool.yml").write_text("version: 1\n")
    monkeypatch.setattr(ios.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        ios.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1),
    )
    result = ios.probe(tmp_path)
    assert result.sdk_installed is False
    assert result.ready is False
    assert any("Darwin Swift SDK" in note for note in result.notes)

# ── _darwin ──────────────────────────────────────────────────────────────
#
# Quartz. Runs everywhere: the backend loads CoreGraphics lazily rather than
# at import, so its whole logic — key vocabulary, chord flags, the consent
# gate, capture argv — is testable off a Mac. Only the real CGEventPost is
# not, and that is the one thing a fake cannot honestly stand in for.


class _FakeQuartz:
    """Records what would have been posted instead of posting it.

    Stands in for both CoreGraphics and ApplicationServices, since the
    backend loads them as a pair.
    """

    def __init__(self, *, trusted=True, display=1):
        self.posted: list[list] = []
        self.released = 0
        self._trusted = trusted
        self._display = display
        self._next = 1000
        self._flags: dict[int, int] = {}
        self._unicode: dict[int, tuple[int, ...]] = {}

    def _create(self, kind, payload):
        self._next += 1
        self.posted.append([kind, payload, 0, self._next, False])
        return self._next

    def CGEventCreateKeyboardEvent(self, source, keycode, down):
        return self._create("key", (keycode, bool(down)))

    def CGEventCreateMouseEvent(self, source, kind, point, button):
        return self._create("mouse", (kind, round(point.x), round(point.y), button))

    def CGEventCreateScrollWheelEvent(self, source, unit, count, amount):
        return self._create("scroll", (unit, count, amount))

    def CGEventCreate(self, source):
        return self._create("cursor", ())

    def CGEventSetFlags(self, event, flags):
        self._flags[event] = flags

    def CGEventKeyboardSetUnicodeString(self, event, length, buffer):
        self._unicode[event] = tuple(buffer[i] for i in range(length))

    def CGEventPost(self, tap, event):
        for record in self.posted:
            if record[3] == event:
                record[2] = self._flags.get(event, 0)
                record[4] = True
                if event in self._unicode:
                    record[1] = ("unicode", self._unicode[event])

    def CFRelease(self, event):
        self.released += 1

    def CGEventGetLocation(self, event):
        from sleipnir.capabilities.computer._darwin import _CGPoint

        return _CGPoint(410.0, 320.0)

    def CGMainDisplayID(self):
        return self._display

    def CGDisplayPixelsWide(self, display):
        return 1920

    def CGDisplayPixelsHigh(self, display):
        return 1080

    def AXIsProcessTrusted(self):
        return self._trusted

    def events(self, kind):
        return [(rec[1], rec[2]) for rec in self.posted if rec[0] == kind and rec[4]]


@pytest.fixture
def quartz(monkeypatch):
    from sleipnir.capabilities.computer import _darwin

    fake = _FakeQuartz()
    monkeypatch.setattr(_darwin, "_load", lambda: (fake, fake))
    return fake


def test_darwin_speaks_the_same_key_vocabulary_as_the_other_backends():
    """The names are the cross-platform contract; the numbers are not.

    A plan that says ``key("ctrl", "t")`` has to mean the same thing on
    every host, so this is the one thing that must never drift.
    """
    from sleipnir.capabilities.computer import _darwin

    assert set(_darwin.KEYCODES) == set(_linux.KEYCODES)
    assert set(_darwin.BUTTON_CODES) == set(_linux.BUTTON_CODES)


def test_darwin_super_and_meta_are_the_same_physical_key():
    from sleipnir.capabilities.computer import _darwin

    assert _darwin.KEYCODES["super"] == _darwin.KEYCODES["meta"]


def test_darwin_chord_presses_in_order_and_releases_in_reverse(quartz):
    from sleipnir.capabilities.computer import _darwin

    codes = [_darwin.KEYCODES["ctrl"], _darwin.KEYCODES["shift"], _darwin.KEYCODES["t"]]
    _darwin.key_chord(codes)

    events = quartz.events("key")
    assert [payload[0] for payload, _ in events] == codes + list(reversed(codes))
    assert [payload[1] for payload, _ in events] == [True] * 3 + [False] * 3


def test_darwin_chord_sets_the_modifier_mask_not_just_the_key(quartz):
    """Cmd-T has to open a tab rather than type a "t".

    A modifier posted only as a key event is honoured by some applications
    and ignored by others, so the accumulated flag mask rides along too.
    """
    from sleipnir.capabilities.computer import _darwin

    _darwin.key_chord([_darwin.KEYCODES["super"], _darwin.KEYCODES["t"]])

    command = _darwin.MODIFIER_FLAGS[_darwin.KEYCODES["super"]]
    flags_on_t = quartz.events("key")[1][1]
    assert flags_on_t & command


def test_darwin_every_created_event_is_released(quartz):
    """One retained CGEvent per action is a leak that only shows up late in
    a long run, which is exactly when it is hardest to attribute.

    Every path is exercised, not just typing: ``type_text`` posts and
    releases inline while the others go through ``_post``, so a test that
    only typed would pass with the shared helper leaking on every click.
    """
    from sleipnir.capabilities.computer import _darwin

    _darwin.type_text("hi", key_delay_ms=0)
    _darwin.key_chord([_darwin.KEYCODES["ctrl"], _darwin.KEYCODES["c"]])
    _darwin.click("left")
    _darwin.scroll(2)
    _darwin.move_mouse(10, 10)

    assert quartz.released == len(quartz.posted)


def test_darwin_types_text_as_unicode_not_as_keycodes(quartz):
    """No layout assumption anywhere: a character is delivered as text."""
    from sleipnir.capabilities.computer import _darwin

    _darwin.type_text("é", key_delay_ms=0)
    payloads = [payload for payload, _ in quartz.events("key")]
    assert all(payload[0] == "unicode" for payload in payloads)
    assert payloads[0][1] == (ord("é"),)


def test_darwin_sends_an_astral_character_as_two_surrogates(quartz):
    from sleipnir.capabilities.computer import _darwin

    _darwin.type_text("\U0001f600", key_delay_ms=0)
    assert len(quartz.events("key")[0][0][1]) == 2


def test_darwin_newline_is_the_return_key_not_a_character(quartz):
    from sleipnir.capabilities.computer import _darwin

    _darwin.type_text("a\nb", key_delay_ms=0)
    keycodes = [payload[0] for payload, _ in quartz.events("key") if payload[0] != "unicode"]
    assert _darwin.KEYCODES["enter"] in keycodes


def test_darwin_click_happens_where_the_cursor_already_is(quartz):
    """A Quartz click carries its own coordinates, so failing to read the
    cursor first would teleport the pointer to (0, 0) on every click."""
    from sleipnir.capabilities.computer import _darwin

    _darwin.click("left")
    assert {(p[1], p[2]) for p, _ in quartz.events("mouse")} == {(410, 320)}


def test_darwin_scroll_sign_matches_the_cross_platform_contract(quartz):
    from sleipnir.capabilities.computer import _darwin

    _darwin.scroll(3)
    assert quartz.events("scroll")[0][0][2] == 3


def test_darwin_refuses_to_act_without_the_accessibility_grant(monkeypatch):
    """The failure this backend exists to prevent.

    Without the grant CGEventPost still succeeds and the event goes
    nowhere, so a caller would believe it had typed. Stopping first is the
    reason ensure_daemon is not a no-op here as it is on Windows.
    """
    from sleipnir.capabilities.computer import _darwin

    denied = _FakeQuartz(trusted=False)
    monkeypatch.setattr(_darwin, "_load", lambda: (denied, denied))

    with pytest.raises(computer.CapabilityError, match="Accessibility"):
        _darwin.ensure_daemon()


def test_darwin_refuses_when_there_is_no_window_server(monkeypatch):
    from sleipnir.capabilities.computer import _darwin

    headless = _FakeQuartz(display=0)
    monkeypatch.setattr(_darwin, "_load", lambda: (headless, headless))

    with pytest.raises(computer.CapabilityError, match="window server"):
        _darwin.ensure_daemon()


def test_darwin_probe_is_not_ready_without_accessibility(monkeypatch):
    from sleipnir.capabilities.computer import _darwin

    denied = _FakeQuartz(trusted=False)
    monkeypatch.setattr(_darwin, "_load", lambda: (denied, denied))
    monkeypatch.setattr(_darwin, "_screenshot_tool", lambda: "/usr/sbin/screencapture")

    report = _darwin.probe()
    assert report.input_injection is False
    assert report.ready is False
    assert any("Accessibility" in note for note in report.notes)


def test_darwin_probe_warns_about_the_permission_that_fails_quietly(quartz, monkeypatch):
    """Screen Recording cannot be probed without taking a capture and
    inspecting it, and without it a capture still succeeds while other
    apps' windows come back blank. So it is said out loud."""
    from sleipnir.capabilities.computer import _darwin

    monkeypatch.setattr(_darwin, "_screenshot_tool", lambda: "/usr/sbin/screencapture")
    report = _darwin.probe()

    assert report.ready is True
    assert report.session_type == "aqua"
    assert report.daemon_running is True
    assert any("Screen Recording" in note for note in report.notes)


def test_darwin_screenshot_runs_screencapture_without_the_shutter(monkeypatch, tmp_path):
    from sleipnir.capabilities.computer import _darwin

    destination = tmp_path / "shot.png"
    seen: list[list[str]] = []

    def fake_run(argv, **kwargs):
        seen.append(argv)
        destination.write_bytes(b"\x89PNG\r\n\x1a\n")
        return type("R", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr(_darwin, "_screenshot_tool", lambda: "/usr/sbin/screencapture")
    monkeypatch.setattr(_darwin.subprocess, "run", fake_run)

    assert _darwin.screenshot(destination) == "screencapture"
    assert "-x" in seen[0]


def test_darwin_screenshot_raises_rather_than_returning_a_missing_file(monkeypatch, tmp_path):
    from sleipnir.capabilities.computer import _darwin

    monkeypatch.setattr(_darwin, "_screenshot_tool", lambda: "/usr/sbin/screencapture")
    monkeypatch.setattr(
        _darwin.subprocess,
        "run",
        lambda argv, **kw: type("R", (), {"returncode": 1, "stderr": "denied"})(),
    )

    with pytest.raises(computer.CapabilityError, match="screencapture failed"):
        _darwin.screenshot(tmp_path / "nope.png")


# --------------------------------------------------------------------------
# xtool 1.19.0's real CLI surface (verified against the installed binary)
# --------------------------------------------------------------------------


def test_ios_sdk_action_uses_a_subcommand_that_exists():
    """`xtool sdk list` does not exist and never did.

    The real subcommands are install / remove / build / status. Every
    `sleipnir ios sdk` call failed with a usage error, which reads to the
    operator as their project being wrong rather than Sleipnir being wrong.
    """
    assert ios.argv("sdk", executable="/opt/xtool") == ["/opt/xtool", "sdk", "status"]


def test_ios_devices_does_not_inherit_xtools_blocking_default():
    """`xtool devices` defaults to `--wait`: with no device it never returns.

    A capability that hangs forever is worse than one that reports nothing,
    because the caller has no way to tell the two apart.
    """
    argv = ios.argv("devices", executable="/opt/xtool")
    assert argv == ["/opt/xtool", "devices", "--no-wait"]


def test_ios_devices_lets_the_operator_ask_to_wait():
    assert "--no-wait" not in ios.argv("devices", ["--wait"], executable="/opt/xtool")


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ("uninstall", ["uninstall"]),
        ("logout", ["auth", "logout"]),
        ("sdk-remove", ["sdk", "remove"]),
        ("xcodeproj", ["dev", "generate-xcode-project"]),
    ],
)
def test_ios_exposes_the_remaining_xtool_verbs(action, expected):
    assert ios.argv(action, executable="/opt/xtool") == ["/opt/xtool", *expected]


def test_ios_run_gives_the_child_a_pollable_stdin(tmp_path, monkeypatch):
    """xtool is SwiftNIO-based and calls epoll_ctl on stdin.

    When stdin is /dev/null -- which is exactly what a tool subprocess gets --
    epoll_ctl returns EPERM and xtool aborts with a 20-frame unsymbolicated
    stack trace that reads nothing like "your stdin is wrong". Measured on
    xtool 1.19.0.
    """
    seen = {}

    def fake_run(argv, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(argv, 0)

    (tmp_path / "Package.swift").write_text("// swift-tools-version:5.9\n", encoding="utf-8")
    (tmp_path / "xtool.yml").write_text("version: 1\n", encoding="utf-8")
    monkeypatch.setattr(ios.audit, "DEFAULT_LOG", tmp_path / "audit.jsonl")
    ios.run("build", root=tmp_path, executable="/usr/bin/true", run=fake_run)
    assert seen.get("stdin") is not None, "stdin must not be inherited from a tool subprocess"


def test_grim_captures_only_the_focused_output(monkeypatch, tmp_path):
    """Two monitors composite into one 3840x1080 frame without `-o`.

    Measured on this machine: the model then reads each screen at 640 px wide
    after the 1280 px downscale, which is illegible.  The operator's attention
    is on the focused output, so that is the screen to capture.
    """
    from sleipnir.capabilities.computer import _linux

    monkeypatch.setattr(_linux.shutil, "which", lambda name: "/usr/bin/grim" if name == "grim" else None)
    monkeypatch.setattr(_linux, "_focused_output", lambda: "HDMI-A-3")
    spawned: list[list[str]] = []

    def fake_run(argv, **_kwargs):
        spawned.append(argv)
        (tmp_path / "shot.png").write_bytes(b"png")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(_linux.subprocess, "run", fake_run)
    assert _linux.screenshot(tmp_path / "shot.png") == "grim"
    assert spawned[0][:3] == ["grim", "-o", "HDMI-A-3"]


def test_grim_captures_everything_when_no_output_is_focused(monkeypatch, tmp_path):
    """A single-monitor or non-Hyprland session must still be captured."""
    from sleipnir.capabilities.computer import _linux

    monkeypatch.setattr(_linux.shutil, "which", lambda name: "/usr/bin/grim" if name == "grim" else None)
    monkeypatch.setattr(_linux, "_focused_output", lambda: None)
    spawned: list[list[str]] = []

    def fake_run(argv, **_kwargs):
        spawned.append(argv)
        (tmp_path / "shot.png").write_bytes(b"png")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(_linux.subprocess, "run", fake_run)
    _linux.screenshot(tmp_path / "shot.png")
    assert spawned[0] == ["grim", str(tmp_path / "shot.png")]


def test_focused_output_is_read_from_the_compositor(monkeypatch):
    from sleipnir.capabilities.computer import _linux

    monkeypatch.setattr(_linux.shutil, "which", lambda name: "/usr/bin/hyprctl" if name == "hyprctl" else None)
    monkeypatch.setattr(
        _linux.subprocess,
        "run",
        lambda *_a, **_k: subprocess.CompletedProcess(
            [], 0, json.dumps([{"name": "eDP-1", "focused": False}, {"name": "HDMI-A-3", "focused": True}]), ""
        ),
    )
    assert _linux._focused_output() == "HDMI-A-3"


def test_focused_output_survives_a_broken_compositor_reply(monkeypatch):
    """A capture must never fail because the window manager answered oddly."""
    from sleipnir.capabilities.computer import _linux

    monkeypatch.setattr(_linux.shutil, "which", lambda name: "/usr/bin/hyprctl" if name == "hyprctl" else None)
    monkeypatch.setattr(
        _linux.subprocess,
        "run",
        lambda *_a, **_k: subprocess.CompletedProcess([], 0, "not json", ""),
    )
    assert _linux._focused_output() is None
