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

import json
import sys

import pytest

from sleipnir.capabilities import audit, browser, computer, secrets
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


def test_every_public_action_is_audited(audit_log, fake_backend, tmp_path):
    # The reason auditing lives in __init__ and not in the backends: one
    # place to forget, and this test notices if it is forgotten there.
    computer.type_text("hi")
    computer.key("ctrl", "c")
    computer.move_mouse(4, 5)
    computer.click("right")
    computer.scroll(-2)
    computer.screenshot(tmp_path / "shot.png")
    recorded = [entry["action"] for entry in _entries(audit_log)]
    assert recorded == [
        "desktop.type",
        "desktop.key",
        "desktop.move_mouse",
        "desktop.click",
        "desktop.scroll",
        "desktop.screenshot",
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


# --- the ydotool backend -------------------------------------------------


def test_chord_releases_modifiers_in_reverse_order(fake_ydotool):
    _linux.key_chord([_linux.KEYCODES[name] for name in ("ctrl", "shift", "t")])
    argv = fake_ydotool[0]
    assert argv[:2] == ["ydotool", "key"]
    # ctrl(29) shift(42) t(20) down, then released t, shift, ctrl.
    assert argv[2:] == ["29:1", "42:1", "20:1", "20:0", "42:0", "29:0"]


def test_type_passes_a_double_dash_so_text_cannot_become_flags(fake_ydotool):
    _linux.type_text("--help --socket-path=/tmp/evil", key_delay_ms=12)
    argv = fake_ydotool[0]
    assert "--" in argv
    assert argv.index("--") < argv.index("--help --socket-path=/tmp/evil")


def test_probe_reports_notes_instead_of_raising(monkeypatch):
    monkeypatch.setattr(_linux.shutil, "which", lambda name: None)
    result = _linux.probe()
    assert result.ready is False
    assert any("ydotool" in note for note in result.notes)


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
