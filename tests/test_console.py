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
    opening = chat.claude_stream_argv("abc-123", resume=False)
    assert "--session-id" in opening and "abc-123" in opening
    assert "--resume" not in opening
    assert "--input-format" in opening and "stream-json" in opening

    continuing = chat.claude_stream_argv("abc-123", resume=True)
    assert continuing[continuing.index("--resume") + 1] == "abc-123"
    assert "--session-id" not in continuing


def test_no_model_is_pinned_in_the_console_invocation():
    # Same rule as the router: model choice is data, never source.
    argv = chat.claude_stream_argv("s", resume=False)
    assert "--model" not in argv
    assert "--model" not in chat.codex_exec_argv()


# --- provider switching ---------------------------------------------------


def test_use_switches_the_provider_and_keeps_sessions_separate():
    state = console.ConsoleState()
    assert console.apply_slash(state, "/use codex") is True
    assert state.provider == "codex"

    claude_session = state.session_for("claude")
    codex_session = state.session_for("codex")
    assert claude_session is not codex_session
    assert claude_session.session_id != codex_session.session_id


def test_console_shutdown_closes_a_codex_session_without_a_live_process():
    import asyncio

    state = console.ConsoleState()
    state.transport_for("codex")
    asyncio.run(state.aclose())


def test_model_command_targets_the_active_provider():
    state = console.ConsoleState()
    console.apply_slash(state, "/model opus")
    assert state.models["claude"] == "opus"
    console.apply_slash(state, "/use codex")
    console.apply_slash(state, "/model @default")
    assert state.models["codex"] is None
    assert state.models["claude"] == "opus"


def test_local_commands_are_consumed_not_dispatched():
    state = console.ConsoleState()
    for line in ("/help", "/use codex", "/model haiku", "/frobnicate"):
        assert console.apply_slash(state, line) is True
    assert state.provider == "codex"


def test_plain_text_is_never_consumed_by_the_slash_handler():
    assert console.apply_slash(console.ConsoleState(), "build the thing") is False


# --- submission routing ----------------------------------------------------


def test_input_typed_while_busy_is_queued_and_never_dropped():
    state = console.ConsoleState()
    state.busy = True
    sent: list[str] = []
    console.handle_submitted(state, "first", sent.append)
    assert sent == [] and list(state.pending_submissions) == ["first"]

    state.busy = False
    console.drain_pending(state, sent.append)
    assert sent == ["first"] and not state.pending_submissions


def test_queued_lines_show_in_the_prompt_rather_than_vanishing():
    state = console.ConsoleState()
    state.pending_submissions.append("x")
    rendered = console.render(state, width=60, height=14, colour=False)
    assert "(+1 queued)" in rendered


# --- streaming --------------------------------------------------------------


class FakeTransport:
    def __init__(self, events):
        self.events = list(events)
        self.prompts: list[str] = []

    async def turn(self, prompt):
        self.prompts.append(prompt)
        for event in self.events:
            yield event

    async def close(self):
        return None


async def _stream_into_state(events, opened=False):
    from sleipnir.chat import ChatEvent

    state = console.ConsoleState()
    session = state.session_for("claude")
    session.opened = opened
    transport = FakeTransport([ChatEvent(kind=k, text=t) for k, t in events])
    session._transport = transport  # noqa: SLF001 - test seam
    await console._handle(state, "hello")
    return state, transport


def test_deltas_render_into_one_growing_message_then_final_replaces_them():
    import asyncio

    state, transport = asyncio.run(
        _stream_into_state([("delta", "hel"), ("delta", "lo"), ("final", "hello world")])
    )
    replies = [m for m in state.messages if m.role == "claude"]
    assert len(replies) == 1, "deltas must fold into one message, not one per chunk"
    assert replies[0].text == "hello world"


def test_the_capability_brief_is_prepended_once_per_provider_session():
    import asyncio

    _, first = asyncio.run(_stream_into_state([("final", "ok")], opened=False))
    assert "computer screenshot" in first.prompts[0]
    _, second = asyncio.run(_stream_into_state([("final", "ok")], opened=True))
    assert "computer screenshot" not in second.prompts[0]


def test_a_direct_conversation_writes_nothing_into_the_run_directory(tmp_path):
    """The invariant, executable: direct-mode chat never touches project
    state — no results.jsonl append, no artifact workspace, nothing."""
    import asyncio
    from sleipnir.runlog import ResultLog

    (tmp_path / "results.jsonl").write_text("", encoding="utf-8")
    state = console.ConsoleState(run_dir=tmp_path)
    session = state.session_for("claude")
    session._transport = FakeTransport([__import__("sleipnir").chat.ChatEvent(kind="final", text="hi")])  # noqa: SLF001
    asyncio.run(console._handle(state, "hello"))

    assert ResultLog(tmp_path / "results.jsonl").read() == []
    assert not (tmp_path / "artifacts").exists()


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
