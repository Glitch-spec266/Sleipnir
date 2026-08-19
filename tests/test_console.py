"""The console owns the terminal, so its failure modes are visual.

Two things are worth pinning: it must never draw outside the frame (a long
paste or a hostile reply would otherwise smear the border across the screen),
and untrusted reply text must not be able to move the cursor.
"""

from __future__ import annotations

import asyncio
import re

import pytest
from fakes import fake_spawner

from sleipnir import chat, console
from sleipnir.capabilities import clipboard
from sleipnir.process import ProcessRunner

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


def test_bracketed_multiline_paste_is_one_atomic_event_even_when_split():
    decoder = console.TerminalInputDecoder()
    assert decoder.feed(b"\x1b[20") == []
    assert decoder.feed(b"0~first\nsecond\x1b[20") == []
    events = decoder.feed(b"1~")
    assert events == [console.PastedText("first\nsecond")]


def test_terminal_escape_keys_are_discarded_not_inserted_as_text():
    decoder = console.TerminalInputDecoder()
    assert decoder.feed(b"\x1b[") == []
    assert decoder.feed(b"A") == []  # up arrow
    assert decoder.feed("é".encode()) == ["é"]


def test_clipboard_text_is_inserted_without_submitting(monkeypatch):
    monkeypatch.setattr(
        clipboard,
        "read",
        lambda: clipboard.ClipboardPayload(
            kind="text", mime_type="text/plain", text="line one\nline two"
        ),
    )
    state = console.ConsoleState()
    assert console.paste_system_clipboard(state) == "text"
    assert state.input_buffer == "line one\nline two"
    assert state.messages == []


def test_clipboard_image_becomes_an_allowed_attachment(tmp_path, monkeypatch):
    image = tmp_path / "clipboard.png"
    image.write_bytes(b"pixels")
    monkeypatch.setattr(
        clipboard,
        "read",
        lambda: clipboard.ClipboardPayload(
            kind="image", mime_type="image/png", path=image
        ),
    )
    state = console.ConsoleState()
    assert console.paste_system_clipboard(state) == "image"
    assert str(image) in state.input_buffer
    assert tmp_path in state.attachment_dirs


def test_clipboard_image_is_refused_in_a_secret_field(tmp_path, monkeypatch):
    image = tmp_path / "clipboard.png"
    monkeypatch.setattr(
        clipboard,
        "read",
        lambda: clipboard.ClipboardPayload(
            kind="image", mime_type="image/png", path=image
        ),
    )
    state = console.ConsoleState(secret_request=object())
    assert console.paste_system_clipboard(state, allow_images=False) == "failed"
    assert state.input_buffer == ""
    assert state.messages[-1].role == "error"


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


def test_console_model_alias_is_passed_to_the_cli():
    argv = chat.claude_argv("s", resume=False, model="operator-fast")
    assert argv[argv.index("--model") + 1] == "operator-fast"


def test_capability_check_can_be_physically_denied_all_tools():
    argv = chat.claude_argv("s", resume=False, model="fast", tools=())
    assert argv[argv.index("--tools") + 1] == ""


def test_chat_turn_uses_guarded_process_runner_and_stdin():
    calls: list = []
    processes: list = []
    payload = b'{"result":"hello","session_id":"s","num_turns":1}'
    runner = ProcessRunner(
        spawn=fake_spawner(stdout=payload, calls=calls, processes=processes)
    )
    reply = asyncio.run(
        chat.ask_claude("private prompt", "s", resume=False, runner=runner)
    )
    assert reply.text == "hello"
    assert processes[0].stdin.text == "private prompt"
    assert calls[0]["kwargs"]["start_new_session"] is True


def test_chat_timeout_terminates_the_process_group():
    processes: list = []
    runner = ProcessRunner(
        spawn=fake_spawner(never_exits=True, processes=processes)
    )
    with pytest.raises(chat.ChatError, match="did not reply"):
        asyncio.run(
            chat.ask_claude(
                "prompt", "s", resume=False, timeout_s=0.01, runner=runner
            )
        )
    assert processes[0].killed


def test_chat_rejects_an_unbounded_response_without_loading_it(monkeypatch):
    payload = b'{"result":"ok"}'
    runner = ProcessRunner(spawn=fake_spawner(stdout=payload))
    monkeypatch.setattr(chat, "MAX_CHAT_RESPONSE_BYTES", len(payload) - 1)
    with pytest.raises(chat.ChatError, match="response exceeded"):
        asyncio.run(chat.ask_claude("prompt", "s", resume=False, runner=runner))


def test_only_an_exact_one_turn_capability_verdict_opens_the_fast_lane():
    assert chat.fast_lane_capable(
        chat.Reply(text=chat.CAPABLE, speaker="claude", turns=1)
    )
    assert not chat.fast_lane_capable(
        chat.Reply(text=f"Sure. {chat.CAPABLE}", speaker="claude", turns=1)
    )
    assert not chat.fast_lane_capable(
        chat.Reply(text=chat.CAPABLE, speaker="claude", turns=2)
    )
    assert not chat.fast_lane_capable(
        chat.Reply(text=chat.CAPABLE, speaker="claude", turns=None)
    )


def test_capable_request_is_checked_without_tools_then_run_on_fast_model(monkeypatch):
    calls = []
    replies = iter(
        [
            chat.Reply(text=chat.CAPABLE, speaker="claude", turns=1),
            chat.Reply(text="done", speaker="claude", turns=2),
        ]
    )

    async def fake_ask(prompt, session_id, **kwargs):
        calls.append((prompt, kwargs))
        return next(replies)

    monkeypatch.setattr(chat, "ask_claude", fake_ask)
    state = console.ConsoleState(model="strong", fast_model="fast")
    first_turn = [True]
    asyncio.run(console._handle(state, "take a screenshot", first_turn=first_turn))

    assert [kwargs["model"] for _, kwargs in calls] == ["fast", "fast"]
    assert calls[0][1]["tools"] == ()
    assert "tools" not in calls[1][1]
    assert state.messages[-1].text == "done"
    assert first_turn == [False]


@pytest.mark.parametrize("verdict", [f"{chat.DECLINE_PREFIX} too risky", "maybe"])
def test_decline_or_malformed_check_routes_to_strong_model(monkeypatch, verdict):
    calls = []
    replies = iter(
        [
            chat.Reply(text=verdict, speaker="claude", turns=1),
            chat.Reply(text="handled safely", speaker="claude", turns=2),
        ]
    )

    async def fake_ask(prompt, session_id, **kwargs):
        calls.append(kwargs)
        return next(replies)

    monkeypatch.setattr(chat, "ask_claude", fake_ask)
    state = console.ConsoleState(model="strong", fast_model="fast")
    asyncio.run(console._handle(state, "do the thing", first_turn=[True]))

    assert [call["model"] for call in calls] == ["fast", "strong"]
    assert calls[0]["tools"] == ()
    assert state.messages[-1].text == "handled safely"


def test_failed_fast_action_is_not_replayed_on_strong_model(monkeypatch):
    calls = []

    async def fake_ask(prompt, session_id, **kwargs):
        calls.append(kwargs["model"])
        if len(calls) == 1:
            return chat.Reply(text=chat.CAPABLE, speaker="claude", turns=1)
        raise chat.ChatError("fast action failed after it may have changed the host")

    monkeypatch.setattr(chat, "ask_claude", fake_ask)
    state = console.ConsoleState(model="strong", fast_model="fast")
    asyncio.run(console._handle(state, "type hello", first_turn=[True]))

    assert calls == ["fast", "fast"]
    assert state.messages[-1].role == "error"
    assert "fast action failed" in state.messages[-1].text


def test_project_command_has_an_explicit_boundary():
    assert console.project_goal("/project build a widget") == "build a widget"
    assert console.project_goal("/project") == ""
    assert console.project_goal("/projector build a widget") is None
    assert console.project_goal("tell me about /project") is None


def test_project_command_bypasses_chat_and_starts_the_workflow(monkeypatch):
    goals = []

    async def fake_project(state, goal):
        goals.append(goal)

    async def forbidden_chat(*args, **kwargs):
        raise AssertionError("/project must not enter ordinary chat")

    monkeypatch.setattr(console, "_run_project", fake_project)
    monkeypatch.setattr(chat, "ask_claude", forbidden_chat)
    state = console.ConsoleState()
    asyncio.run(console._handle(state, "/project build a widget", first_turn=[True]))
    assert goals == ["build a widget"]


def test_project_workflow_runs_the_real_plan_then_orchestrate_stages(monkeypatch, tmp_path):
    stages = []

    async def fake_stage(state, *command):
        stages.append(command)
        return "ok"

    monkeypatch.setattr(console, "_run_project_stage", fake_stage)
    state = console.ConsoleState(project_base=tmp_path)
    asyncio.run(console._run_project(state, "build a widget"))

    assert stages == [("plan", "build a widget"), ("orchestrate",)]
    assert state.messages[-1].text.startswith("Project workflow finished.")
    assert state.run_dir is not None
    assert state.run_dir.parent == tmp_path / "runs"
    assert "build-a-widget" in state.run_dir.name


def test_each_bare_console_project_gets_a_fresh_sibling_workspace(monkeypatch, tmp_path):
    async def fake_stage(state, *command):
        return "ok"

    monkeypatch.setattr(console, "_run_project_stage", fake_stage)
    state = console.ConsoleState(project_base=tmp_path)
    asyncio.run(console._run_project(state, "first project"))
    first = state.run_dir
    asyncio.run(console._run_project(state, "second project"))
    second = state.run_dir
    assert first is not None and second is not None and first != second
    assert first.parent == second.parent == tmp_path / "runs"


def test_explicit_console_run_root_is_used_exactly(tmp_path):
    run_root = tmp_path / "not-created-yet"
    state = console.ConsoleState(
        run_dir=run_root,
        project_base=tmp_path.parent,
        run_root_explicit=True,
    )
    assert console._allocate_project_run(state, "do not nest me") == run_root
    assert run_root.is_dir()


def test_project_child_inherits_console_workspace_and_config(tmp_path):
    config = tmp_path / "sleipnir.toml"
    state = console.ConsoleState(
        run_dir=tmp_path,
        config_path=config,
        cache_read_weight=0.5,
    )
    argv = console._project_argv(state, "orchestrate")

    assert argv[-1] == "orchestrate"
    assert argv[argv.index("--run-root") + 1] == str(tmp_path)
    assert argv[argv.index("--config") + 1] == str(config)
    assert argv[argv.index("--cache-read-weight") + 1] == "0.5"


def test_project_stage_uses_guarded_process_runner(tmp_path):
    calls: list = []
    runner = ProcessRunner(spawn=fake_spawner(stdout=b"stage complete\n", calls=calls))
    state = console.ConsoleState(run_dir=tmp_path)
    output = asyncio.run(
        console._run_project_stage(state, "orchestrate", runner=runner)
    )
    assert output == "stage complete"
    assert calls[0]["kwargs"]["start_new_session"] is True
    assert calls[0]["kwargs"]["cwd"] == str(tmp_path)


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
