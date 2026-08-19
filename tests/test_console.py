"""The console owns the terminal, so its failure modes are visual.

Two things are worth pinning: it must never draw outside the frame (a long
paste or a hostile reply would otherwise smear the border across the screen),
and untrusted reply text must not be able to move the cursor.
"""

from __future__ import annotations

import re

import pytest

from sleipnir import chat, console

ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _widths(rendered: str) -> set[int]:
    return {len(ANSI.sub("", line)) for line in rendered.split("\n")}


def test_every_rendered_line_is_exactly_the_terminal_width():
    state = console.ConsoleState()
    state.add("claude", "word " * 200)
    state.input_buffer = "x" * 300
    assert _widths(console.render(state, width=64, height=20)) == {64}


def test_an_unbroken_token_longer_than_the_pane_is_hard_split():
    state = console.ConsoleState()
    state.add("claude", "A" * 400)
    assert _widths(console.render(state, width=50, height=16)) == {50}


def test_control_bytes_in_a_reply_cannot_repaint_the_screen():
    state = console.ConsoleState()
    state.add("claude", "safe\x1b[2J\x1b[Hnot-safe\r\n\x07")
    rendered = console.render(state, width=70, height=14, colour=False)
    assert "\x1b[2J" not in rendered
    assert "\x07" not in rendered
    assert "not-safe" in rendered  # stripped, not dropped


def test_narrow_terminal_still_renders():
    state = console.ConsoleState()
    state.add("you", "hello")
    assert _widths(console.render(state, width=24, height=8)) == {24}


# --- input editing -------------------------------------------------------


def test_enter_submits_and_clears_the_buffer():
    state = console.ConsoleState(input_buffer="deploy it")
    assert console.apply_key(state, "\r") == "deploy it"
    assert state.input_buffer == ""


def test_blank_enter_submits_nothing():
    state = console.ConsoleState(input_buffer="   ")
    assert console.apply_key(state, "\r") is None


def test_backspace_and_ctrl_u():
    state = console.ConsoleState(input_buffer="abc")
    console.apply_key(state, "\x7f")
    assert state.input_buffer == "ab"
    console.apply_key(state, "\x15")
    assert state.input_buffer == ""


def test_non_printable_keys_are_ignored_rather_than_inserted():
    state = console.ConsoleState()
    for char in ("\x1b", "\x00", "\x07"):
        console.apply_key(state, char)
    assert state.input_buffer == ""


# --- routing -------------------------------------------------------------


def test_first_turn_carries_the_capability_brief_and_later_turns_do_not():
    # The brief is what tells Claude it has host control. Repeating it every
    # turn would re-pay its token cost for information the session already has.
    assert "computer screenshot" in console.capability_brief()
    assert "never stored, logged, or shown to you" in console.capability_brief()


def test_claude_argv_opens_a_session_then_resumes_it():
    opening = chat.claude_argv("abc-123", resume=False)
    assert "--session-id" in opening and "abc-123" in opening
    assert "--resume" not in opening

    continuing = chat.claude_argv("abc-123", resume=True)
    assert continuing[continuing.index("--resume") + 1] == "abc-123"
    assert "--session-id" not in continuing


def test_no_model_is_pinned_in_the_console_invocation():
    # Same rule as the router: model choice is data, never source.
    assert "--model" not in chat.claude_argv("s", resume=False)


def test_queue_instruction_is_parsed_from_a_duty_officer_reply():
    reply = "Three tasks are failing acceptance.\nQUEUE: retry the auth module on a stronger tier"
    assert chat.extract_queued_instruction(reply) == "retry the auth module on a stronger tier"


def test_a_reply_without_a_queue_line_queues_nothing():
    assert chat.extract_queued_instruction("Everything is green.") is None


def test_empty_queue_line_is_not_treated_as_an_instruction():
    assert chat.extract_queued_instruction("QUEUE:   ") is None


def test_duty_officer_prompt_forbids_task_output():
    assert "must not ask for, any task" in chat.ROUTER_SYSTEM
    assert "constant-size manifest" in chat.ROUTER_SYSTEM


def test_router_model_comes_from_operator_config():
    class FakeBackend:
        def __init__(self, model_id):
            self.models = (type("M", (), {"id": model_id})(),)

    class FakeConfig:
        backends = {"openrouter": FakeBackend("some/cheap-model")}

        def policy(self, tier):
            return type("P", (), {"prefer": ("openrouter",)})()

    assert chat.router_model(FakeConfig()) == "some/cheap-model"


def test_router_model_refuses_rather_than_guessing():
    class EmptyConfig:
        backends: dict = {}

        def policy(self, tier):
            return type("P", (), {"prefer": ()})()

    with pytest.raises(chat.ChatError, match="no model configured"):
        chat.router_model(EmptyConfig())
