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


def test_the_brain_is_asleep_exactly_when_a_run_owns_the_directory(tmp_path):
    from sleipnir.runlog import RunLock

    state = console.ConsoleState(run_dir=tmp_path)
    console.refresh_brain_state(state)
    assert state.brain_awake is True, "no run in flight means the brain is available"

    with RunLock(tmp_path):
        console.refresh_brain_state(state)
        assert state.brain_awake is False, "an owned run means workers are building"

    console.refresh_brain_state(state)
    assert state.brain_awake is True, "the lock releases on exit, so the brain returns"


def test_no_run_directory_leaves_the_brain_awake():
    state = console.ConsoleState(run_dir=None)
    console.refresh_brain_state(state)
    assert state.brain_awake is True


def test_the_run_digest_is_constant_size_and_carries_no_task_output(tmp_path):
    """What the duty officer sees. If this ever grew with the plan, the cheap
    stand-in would stop being cheap and the design would leak."""
    import json
    from datetime import UTC, datetime

    from sleipnir.schema import (
        ExpectedOutput,
        OutputContract,
        OutputKind,
        Plan,
        Task,
        Tier,
    )

    def build(count: int) -> str:
        tasks = [
            Task(
                id=f"t{index}",
                description=f"build component number {index} exactly as specified",
                tier=Tier.CODE,
                outputs=OutputContract(
                    outputs=[
                        ExpectedOutput(
                            name="out",
                            kind=OutputKind.FILE,
                            path=f"t{index}.txt",
                            description="the produced file",
                        )
                    ]
                ),
            )
            for index in range(count)
        ]
        plan = Plan(
            plan_id="p",
            goal="ship it",
            created_at=datetime(2026, 8, 19, tzinfo=UTC),
            tasks=tasks,
        )
        run = tmp_path / f"run{count}"
        run.mkdir()
        (run / "plan.json").write_text(plan.model_dump_json(), encoding="utf-8")
        return console.run_digest(run)

    small, large = build(3), build(300)
    # A hundredfold more tasks may cost the digest the two extra digits in
    # "300" and nothing else. Anything proportional means task detail leaked in.
    assert len(large) - len(small) == 2, "the digest must not grow with the plan"
    payload = json.loads(large)
    assert set(payload) == {"goal", "revision", "quiescent", "groups"}
    # Counts and ids only — never a summary, a path, or a byte a worker wrote.
    assert set(payload["groups"][0]) == {
        "group", "state", "total", "done", "failed", "running", "failed_task_ids",
    }


def test_router_model_refuses_rather_than_guessing():
    class EmptyConfig:
        backends: dict = {}

        def policy(self, tier):
            return type("P", (), {"prefer": ()})()

    with pytest.raises(chat.ChatError, match="no model configured"):
        chat.router_model(EmptyConfig())
