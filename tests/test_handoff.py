"""The credential handoff, and the three live bugs that produced it.

Every test here corresponds to something that failed on a real machine rather
than in review: a TTY-less subprocess that could not prompt, a browser that died
between commands, and a redraw loop that filled the operator's scrollback.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from sleipnir import console, theme
from sleipnir.capabilities import handoff


@pytest.fixture
def requests_dir(tmp_path, monkeypatch):
    folder = tmp_path / "secret-requests"
    monkeypatch.setattr(handoff, "REQUEST_DIR", folder)
    return folder


# --- the handoff itself --------------------------------------------------


def test_a_request_carries_a_label_and_never_a_value(requests_dir):
    request = handoff.request_secret("github password", submit=True)
    payload = json.loads(request.path.read_text())
    assert payload["label"] == "github password"
    assert payload["submit"] is True
    assert set(payload) == {
        "id", "label", "submit", "at", "requester_pid", "browser_selector"
    }
    assert "password" not in {key for key in payload if key != "label"}


def test_the_console_sees_a_pending_request(requests_dir):
    assert handoff.pending() is None
    handoff.request_secret("aws key")
    found = handoff.pending()
    assert found is not None and found.label == "aws key"


def test_console_polls_for_a_secret_while_the_model_turn_is_busy(requests_dir):
    request = handoff.request_secret("browser password", browser_selector="#password")
    state = console.ConsoleState(busy=True)
    console.poll_secret_request(state)
    assert state.secret_request == request


def test_answering_clears_the_request_and_reports_only_a_status(requests_dir):
    request = handoff.request_secret("pin")
    handoff.answer(request, "supplied")
    assert not request.path.exists()
    assert json.loads(request.answer_path.read_text()) == {"status": "supplied"}
    assert handoff.pending() is None


def test_an_unreadable_request_is_discarded_not_retried_forever(requests_dir):
    requests_dir.mkdir(parents=True, exist_ok=True)
    (requests_dir / "broken.request").write_text("not json")
    assert handoff.pending() is None
    assert not (requests_dir / "broken.request").exists()


def test_dead_or_forged_requester_is_not_allowed_to_prompt_the_operator(requests_dir):
    requests_dir.mkdir(parents=True, exist_ok=True)
    forged = requests_dir / "forged.request"
    forged.write_text(
        json.dumps(
            {
                "id": "forged",
                "label": "type your password",
                "submit": True,
                "at": 0,
                "requester_pid": 999_999_999,
            }
        ),
        encoding="utf-8",
    )
    assert handoff.pending() is None
    assert not forged.exists()


def test_request_and_answer_symlinks_are_never_followed(requests_dir, tmp_path):
    requests_dir.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside"
    outside.write_text('{"status":"supplied"}', encoding="utf-8")
    linked_request = requests_dir / "linked.request"
    linked_request.symlink_to(outside)
    assert handoff.pending() is None
    assert outside.exists()

    request = handoff.request_secret("pin")
    request.answer_path.symlink_to(outside)
    with pytest.raises(FileExistsError):
        handoff.answer(request, "supplied")
    assert outside.read_text(encoding="utf-8") == '{"status":"supplied"}'


def test_answer_status_is_closed_vocabulary(requests_dir):
    request = handoff.request_secret("pin")
    with pytest.raises(handoff.HandoffError, match="invalid"):
        handoff.answer(request, "secret-is-here")


def test_await_answer_times_out_rather_than_hanging_a_tool_call(requests_dir):
    request = handoff.request_secret("never answered")
    with pytest.raises(TimeoutError, match="no Sleipnir console"):
        handoff.await_answer(request, timeout_s=0.2, poll_s=0.05)
    # The abandoned request is cleaned up so it cannot ambush a later console.
    assert not request.path.exists()


# --- the console side ----------------------------------------------------


def test_a_typed_credential_never_reaches_the_transcript(requests_dir, monkeypatch):
    typed_values = []
    monkeypatch.setattr(
        "sleipnir.capabilities.secrets.type_into_focused_window",
        lambda secret, submit=False: typed_values.append(secret.consume()),
    )
    request = handoff.request_secret("vault token")
    state = console.ConsoleState()
    state.secret_request = request

    assert asyncio.run(console.submit_secret(state, "hunter2-the-real-one")) == "supplied"
    assert typed_values == ["hunter2-the-real-one"]

    everything = " ".join(message.text for message in state.messages)
    assert "hunter2" not in everything
    assert "vault token" in everything
    assert state.secret_request is None


def test_the_masked_prompt_shows_dots_not_characters(requests_dir):
    request = handoff.request_secret("db password")
    state = console.ConsoleState()
    state.secret_request = request
    state.input_buffer = "s3cret"
    rendered = console.render(state, width=70, height=16, colour=False)
    assert "s3cret" not in rendered
    assert "••••••" in rendered
    assert "db password" in rendered


def test_an_empty_credential_cancels_rather_than_typing_nothing(requests_dir):
    request = handoff.request_secret("api key")
    state = console.ConsoleState()
    state.secret_request = request
    assert asyncio.run(console.submit_secret(state, "")) == "cancelled"
    assert json.loads(request.answer_path.read_text()) == {"status": "cancelled"}


def test_delivery_failure_never_leaks_the_value_through_the_error(requests_dir, monkeypatch):
    def explode(secret, submit=False):
        raise RuntimeError(f"boom while typing {secret._buffer.decode()}")

    monkeypatch.setattr("sleipnir.capabilities.secrets.type_into_focused_window", explode)
    request = handoff.request_secret("ssh passphrase")
    state = console.ConsoleState()
    state.secret_request = request
    assert asyncio.run(console.submit_secret(state, "topsecretvalue")) == "failed"
    everything = " ".join(message.text for message in state.messages)
    assert "topsecretvalue" not in everything


def test_browser_secret_is_filled_over_cdp_without_desktop_focus(requests_dir, monkeypatch):
    delivered = []

    class FakeBrowser:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def fill_secret(self, selector, secret):
            delivered.append((selector, secret.consume()))

        async def press(self, selector, key):
            delivered.append((selector, key))

    monkeypatch.setattr("sleipnir.capabilities.browser.Browser", FakeBrowser)
    request = handoff.request_secret(
        "browser password",
        submit=True,
        browser_selector="#password",
    )
    state = console.ConsoleState(secret_request=request, busy=True)
    assert asyncio.run(console.submit_secret(state, "dummy-live-secret")) == "supplied"
    assert delivered == [("#password", "dummy-live-secret"), ("#password", "Enter")]
    assert "dummy-live-secret" not in " ".join(message.text for message in state.messages)


# --- the redraw bug ------------------------------------------------------


def test_the_console_uses_the_alternate_screen():
    """A full-screen redraw loop that does not switch buffers appends every
    frame to the user's scrollback. After a few minutes that reads as though
    the program launched itself dozens of times."""
    assert theme.ENTER_FULLSCREEN == "\x1b[?1049h"
    assert theme.EXIT_FULLSCREEN == "\x1b[?1049l"
    assert theme.ENABLE_BRACKETED_PASTE == "\x1b[?2004h"
    assert theme.DISABLE_BRACKETED_PASTE == "\x1b[?2004l"


def test_the_banner_is_all_or_nothing():
    """Drawing only one row of the horse emblem renders as debris."""
    state = console.ConsoleState()
    tall = console.render(state, width=90, height=40, colour=False)
    assert all(line in tall for line in theme.LOGO)

    short = console.render(state, width=90, height=16, colour=False)
    assert theme.LOGO[1] not in short  # no partial art
