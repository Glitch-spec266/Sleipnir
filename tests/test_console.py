"""The console owns the terminal, so its failure modes are visual.

Two things are worth pinning: it must never draw outside the frame (a long
paste or a hostile reply would otherwise smear the border across the screen),
and untrusted reply text must not be able to move the cursor.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest
from fakes import fake_spawner

from sleipnir import platform
from sleipnir import chat, console
from sleipnir.capabilities import clipboard
from sleipnir.process import ProcessRunner
from sleipnir.schema import Tier

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
    def __init__(self, events, *, error=None):
        self.events = list(events)
        self.prompts: list[str] = []
        self.models: list[str | None] = []
        self.model: str | None = None
        self.add_dirs = ()
        self.error = error

    async def turn(self, prompt):
        self.prompts.append(prompt)
        self.models.append(self.model)
        if self.error is not None:
            raise self.error
        for event in self.events:
            yield event

    async def close(self):
        return None


async def _stream_into_state(events, opened=False):
    from sleipnir.chat import ChatEvent

    state = console.ConsoleState(fast_model=None)
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
    state = console.ConsoleState(run_dir=tmp_path, fast_model=None)
    session = state.session_for("claude")
    session._transport = FakeTransport([__import__("sleipnir").chat.ChatEvent(kind="final", text="hi")])  # noqa: SLF001
    asyncio.run(console._handle(state, "hello"))

    assert ResultLog(tmp_path / "results.jsonl").read() == []
    assert not (tmp_path / "artifacts").exists()


def test_console_model_alias_is_passed_to_the_cli():
    argv = chat.claude_argv("s", resume=False, model="operator-fast")
    assert argv[argv.index("--model") + 1] == "operator-fast"


def test_capability_check_can_be_physically_denied_all_tools():
    argv = chat.claude_argv("s", resume=False, model="fast", tools=())
    assert argv[argv.index("--tools") + 1] == ""
    assert "--strict-mcp-config" in argv
    assert argv[argv.index("--mcp-config") + 1] == '{"mcpServers":{}}'


def test_nonempty_claude_tools_preserve_operator_mcp_configuration():
    argv = chat.claude_argv("s", resume=False, tools=("Read",))
    assert argv[argv.index("--tools") + 1] == "Read"
    assert "--strict-mcp-config" not in argv
    assert "--mcp-config" not in argv


def test_classifier_can_replace_the_default_agent_prompt():
    argv = chat.claude_argv(
        "s",
        resume=False,
        system_prompt="classify only",
    )
    assert argv[argv.index("--system-prompt") + 1] == "classify only"


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
    for key, value in platform.CHILD_SPAWN_KWARGS.items():
        assert calls[0]["kwargs"][key] == value


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

    async def fake_ask(prompt, session_id, **kwargs):
        calls.append((prompt, session_id, kwargs))
        return chat.Reply(text=chat.CAPABLE, speaker="claude", turns=1)

    monkeypatch.setattr(chat, "ask_claude", fake_ask)
    state = console.ConsoleState(
        models={"claude": "strong", "codex": None}, fast_model="fast"
    )
    session = state.session_for("claude")
    transport = FakeTransport([chat.ChatEvent(kind="final", text="done")])
    transport.model = "strong"
    session._transport = transport  # noqa: SLF001 - test seam
    asyncio.run(console._handle(state, "take a screenshot"))

    assert [kwargs["model"] for _, _, kwargs in calls] == ["fast"]
    assert calls[0][2]["tools"] == ()
    assert calls[0][2]["system_prompt"] == chat.FAST_LANE_ASSESSMENT
    assert calls[0][1] != state.session_id
    assert calls[0][2]["resume"] is False
    assert transport.models == ["fast"]
    assert "take a screenshot" in transport.prompts[0]
    assert transport.model == "strong"
    assert state.messages[-1].text == "done"
    assert any("Fast lane approved" in message.text for message in state.messages)
    assert session.opened is True


@pytest.mark.parametrize("verdict", [f"{chat.DECLINE_PREFIX} too risky", "maybe"])
def test_decline_or_malformed_check_routes_to_strong_model(monkeypatch, verdict):
    calls = []

    async def fake_ask(prompt, session_id, **kwargs):
        calls.append((prompt, session_id, kwargs))
        return chat.Reply(text=verdict, speaker="claude", turns=1)

    monkeypatch.setattr(chat, "ask_claude", fake_ask)
    state = console.ConsoleState(
        models={"claude": "strong", "codex": None}, fast_model="fast"
    )
    session = state.session_for("claude")
    transport = FakeTransport([chat.ChatEvent(kind="final", text="handled safely")])
    transport.model = "strong"
    session._transport = transport  # noqa: SLF001 - test seam
    asyncio.run(console._handle(state, "do the thing"))

    assert [call[2]["model"] for call in calls] == ["fast"]
    assert calls[0][2]["tools"] == ()
    assert calls[0][1] != state.session_id
    assert transport.models == ["strong"]
    assert "do the thing" in transport.prompts[0]
    assert state.messages[-1].text == "handled safely"
    assert any("routing the untouched request" in message.text for message in state.messages)


def test_failed_fast_action_is_not_replayed_on_strong_model(monkeypatch):
    calls = []

    async def fake_ask(prompt, session_id, **kwargs):
        calls.append(kwargs["model"])
        return chat.Reply(text=chat.CAPABLE, speaker="claude", turns=1)

    monkeypatch.setattr(chat, "ask_claude", fake_ask)
    state = console.ConsoleState(
        models={"claude": "strong", "codex": None}, fast_model="fast"
    )
    session = state.session_for("claude")
    transport = FakeTransport(
        [], error=chat.ChatError("fast action failed after it may have changed the host")
    )
    transport.model = "strong"
    session._transport = transport  # noqa: SLF001 - test seam
    asyncio.run(console._handle(state, "type hello"))

    assert calls == ["fast"]
    assert transport.models == ["fast"]
    assert transport.model == "strong"
    assert state.messages[-1].role == "error"
    assert "fast action failed" in state.messages[-1].text


def test_failed_tool_free_assessment_falls_closed_to_strong_model(monkeypatch):
    calls = []
    original_session = "assessment-session"

    async def fake_ask(prompt, session_id, **kwargs):
        calls.append((prompt, session_id, kwargs))
        if len(calls) == 1:
            raise chat.ChatError("Haiku assessment unavailable")
        return chat.Reply(text="handled by Sonnet", speaker="claude", turns=1)

    monkeypatch.setattr(chat, "ask_claude", fake_ask)
    state = console.ConsoleState(
        session_id=original_session,
        models={"claude": "sonnet", "codex": None},
        fast_model="haiku",
    )
    session = state.session_for("claude")
    transport = FakeTransport([chat.ChatEvent(kind="final", text="handled by Sonnet")])
    transport.model = "sonnet"
    session._transport = transport  # noqa: SLF001 - test seam
    asyncio.run(console._handle(state, "explain this screenshot"))

    assert [call[2]["model"] for call in calls] == ["haiku"]
    assert calls[0][2]["tools"] == ()
    assert calls[0][1] != original_session
    assert transport.models == ["sonnet"]
    assert "explain this screenshot" in transport.prompts[0]
    assert state.messages[-1].text == "handled by Sonnet"
    assert session.opened is True


def test_failed_assessment_reserves_session_before_strong_action(monkeypatch):
    calls = []

    async def fake_ask(prompt, session_id, **kwargs):
        calls.append((session_id, kwargs))
        raise chat.ChatError("assessment unavailable")

    monkeypatch.setattr(chat, "ask_claude", fake_ask)
    state = console.ConsoleState(
        session_id="durable",
        models={"claude": "sonnet", "codex": None},
        fast_model="haiku",
    )
    session = state.session_for("claude")
    transport = FakeTransport(
        [], error=chat.ChatError("Sonnet failed after it may have changed the host")
    )
    transport.model = "sonnet"
    session._transport = transport  # noqa: SLF001 - test seam
    asyncio.run(console._handle(state, "perform an action"))

    assert calls[0][0] != state.session_id
    assert transport.models == ["sonnet"]
    assert session.opened is False
    assert state.messages[-1].role == "error"
    assert "may have changed the host" in state.messages[-1].text


def test_each_gate_is_ephemeral_while_action_chat_resumes(monkeypatch):
    calls = []

    async def fake_ask(prompt, session_id, **kwargs):
        calls.append((prompt, session_id, kwargs))
        return chat.Reply(text=chat.CAPABLE, speaker="claude", turns=1)

    monkeypatch.setattr(chat, "ask_claude", fake_ask)
    state = console.ConsoleState(
        session_id="durable",
        models={"claude": "strong", "codex": None},
        fast_model="fast",
    )
    session = state.session_for("claude")
    transport = FakeTransport([chat.ChatEvent(kind="final", text="ok")])
    transport.model = "strong"
    session._transport = transport  # noqa: SLF001 - test seam
    asyncio.run(console._handle(state, "first request"))
    asyncio.run(console._handle(state, "second request"))

    assert calls[0][1] != calls[1][1]
    assert all(call[1] != state.session_id for call in calls)
    assert [call[2]["resume"] for call in calls] == [False, False]
    assert "first request" in transport.prompts[0]
    assert transport.prompts[1] == "second request"
    assert transport.models == ["fast", "fast"]


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
    asyncio.run(console._handle(state, "/project build a widget"))
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
    for key, value in platform.CHILD_SPAWN_KWARGS.items():
        assert calls[0]["kwargs"][key] == value
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


# ---------------------------------------------------------------------------
# Phase A: the slash command registry, the / menu, /effort and /ask
# ---------------------------------------------------------------------------


def test_every_registered_command_documents_itself():
    """/help and the menu both render from the registry, so a command with no
    summary would render a blank row rather than fail loudly."""
    assert console.COMMANDS
    for command in console.COMMANDS:
        assert command.name.startswith("/")
        assert command.summary.strip()
        assert command.usage.strip()


def test_help_lists_every_registered_command():
    state = console.ConsoleState()
    assert console.apply_slash(state, "/help") is True
    printed = state.messages[-1].text
    for command in console.COMMANDS:
        assert command.name in printed


def test_menu_opens_on_a_bare_slash_and_lists_everything():
    state = console.ConsoleState(input_buffer="/")
    assert console.menu_rows(state) == console.COMMANDS


def test_menu_filters_by_prefix_as_you_type():
    state = console.ConsoleState(input_buffer="/mod")
    rows = console.menu_rows(state)
    assert [row.name for row in rows] == ["/model"]


def test_menu_closes_once_the_command_is_complete():
    """A space means the operator is typing arguments, not choosing."""
    state = console.ConsoleState(input_buffer="/model ")
    assert console.menu_rows(state) == ()


def test_menu_is_closed_for_ordinary_text():
    state = console.ConsoleState(input_buffer="build the thing")
    assert console.menu_rows(state) == ()


def test_tab_cycles_the_menu_selection_and_wraps():
    state = console.ConsoleState(input_buffer="/")
    console.apply_key(state, "\t")
    assert state.menu_index == 1
    for _ in range(len(console.COMMANDS)):
        console.apply_key(state, "\t")
    assert state.menu_index == 1


def test_enter_completes_the_highlighted_command_instead_of_submitting():
    state = console.ConsoleState(input_buffer="/mod")
    assert console.apply_key(state, "\r") is None
    assert state.input_buffer == "/model "


def test_enter_submits_when_the_command_is_already_exact():
    state = console.ConsoleState(input_buffer="/help")
    assert console.apply_key(state, "\r") == "/help"


def test_typing_resets_the_menu_selection():
    state = console.ConsoleState(input_buffer="/")
    console.apply_key(state, "\t")
    console.apply_key(state, "m")
    assert state.menu_index == 0


def test_effort_accepts_a_documented_level():
    state = console.ConsoleState()
    assert console.apply_slash(state, "/effort high") is True
    assert state.effort == "high"


def test_effort_refuses_an_undocumented_level():
    """An ignored effort flag is worse than a refusal: it reads as applied."""
    state = console.ConsoleState()
    state.effort = "low"
    console.apply_slash(state, "/effort turbo")
    assert state.effort == "low"
    assert "turbo" in state.messages[-1].text


def test_ask_toggles_the_permission_mode_both_ways():
    state = console.ConsoleState()
    console.apply_slash(state, "/ask on")
    assert state.permission_mode != "bypassPermissions"
    console.apply_slash(state, "/ask off")
    assert state.permission_mode == "bypassPermissions"


def test_claude_argv_carries_the_effort_level():
    argv = chat.claude_stream_argv("s1", resume=False, model="sonnet", effort="max")
    assert "--effort" in argv
    assert argv[argv.index("--effort") + 1] == "max"


def test_claude_argv_omits_effort_when_unset():
    argv = chat.claude_stream_argv("s1", resume=False, model="sonnet")
    assert "--effort" not in argv


def test_model_change_reaches_an_already_built_transport():
    """The transport is cached per provider, so a later /model has to be
    pushed onto it — otherwise the footer reports a model the spawn never uses."""
    state = console.ConsoleState()
    transport = state.transport_for("claude")
    console.apply_slash(state, "/model opus")
    assert transport.model == "opus"


def test_effort_change_reaches_an_already_built_transport():
    state = console.ConsoleState()
    transport = state.transport_for("claude")
    console.apply_slash(state, "/effort xhigh")
    assert transport.effort == "xhigh"


def test_the_menu_is_drawn_while_a_command_is_being_typed():
    state = console.ConsoleState(input_buffer="/mod")
    drawn = console.render(state, width=80, height=24, colour=False)
    assert "/model <alias|default>" in drawn
    assert "/use" not in drawn.split("›")[0].split("/model")[-1]


def test_the_menu_marks_the_highlighted_row():
    state = console.ConsoleState(input_buffer="/")
    first = console.render(state, width=80, height=24, colour=False)
    console.apply_key(state, "\t")
    second = console.render(state, width=80, height=24, colour=False)
    assert first != second


def test_no_menu_is_drawn_for_ordinary_text():
    state = console.ConsoleState(input_buffer="build the thing")
    assert "/model" not in console.render(state, width=80, height=24, colour=False)


def test_launch_effort_is_validated_against_the_documented_levels():
    """Refused at launch for the same reason /effort refuses it: an unknown
    level would reach the CLI and be rejected there, mid-spawn."""
    import asyncio, argparse
    from sleipnir.cli import CliError, cmd_console

    args = argparse.Namespace(provider="claude", model="sonnet", effort="turbo", no_splash=True)
    with pytest.raises(CliError):
        asyncio.run(cmd_console(args))


# ---------------------------------------------------------------------------
# Phase B: live project routing controls
# ---------------------------------------------------------------------------


def _routing_state(tmp_path):
    from sleipnir.config import SleipnirConfig

    cfg = SleipnirConfig.load(Path(__file__).resolve().parents[1] / "sleipnir.example.toml")
    return console.ConsoleState(project_base=tmp_path, routing_config=cfg)


def test_router_command_selects_a_configured_model_for_the_session(tmp_path):
    from sleipnir.config import SleipnirConfig

    state = _routing_state(tmp_path)
    backend = next(iter(state.routing_config.backends.values()))
    model = backend.models[-1].id

    console.apply_slash(state, f"/router code {model}")

    assert state.routing_config.policy(Tier.CODE).prefer[0] == backend.name
    assert state.routing_config.backends[backend.name].models[0].id == model
    assert state.config_path is not None
    assert SleipnirConfig.load(state.config_path).policy(Tier.CODE).prefer[0] == backend.name


def test_provider_add_uses_only_an_environment_variable_reference(tmp_path):
    state = _routing_state(tmp_path)

    console.apply_slash(
        state,
        "/provider add nim openai vendor/model https://nim.example/v1 NIM_API_KEY 128000 1.25",
    )

    backend = state.routing_config.backends["nim"]
    assert backend.api_key_env == "NIM_API_KEY"
    assert backend.base_url == "https://nim.example/v1"
    assert "NIM_API_KEY" in state.messages[-1].text
    assert "API key" not in state.config_path.read_text(encoding="utf-8")


def test_router_can_qualify_a_model_shared_by_two_backends(tmp_path):
    state = _routing_state(tmp_path)
    existing = next(iter(state.routing_config.backends.values())).models[0].id
    console.apply_slash(
        state,
        f"/provider add mirror openai {existing} https://mirror.example/v1 MIRROR_KEY 128000 1.0",
    )

    console.apply_slash(state, f"/router code mirror {existing}")

    assert state.routing_config.policy(Tier.CODE).prefer[0] == "mirror"


def test_provider_command_refuses_a_raw_secret_flag(tmp_path):
    state = _routing_state(tmp_path)
    console.apply_slash(
        state,
        "/provider add nim openai vendor/model https://nim.example/v1 sk-secret-value",
    )
    assert "nim" not in state.routing_config.backends
    assert "environment variable" in state.messages[-1].text


def test_provider_command_refuses_url_embedded_credentials(tmp_path):
    state = _routing_state(tmp_path)
    console.apply_slash(
        state,
        "/provider add nim openai vendor/model https://secret@nim.example/v1 NIM_KEY",
    )
    assert "nim" not in state.routing_config.backends
    assert "base URL" in state.messages[-1].text


def test_run_root_cannot_change_while_executor_owns_current_root(tmp_path, monkeypatch):
    state = console.ConsoleState(run_dir=tmp_path)
    monkeypatch.setattr("sleipnir.runlog.run_is_active", lambda path: True)

    console.apply_slash(state, f"/run-root {tmp_path / 'elsewhere'}")

    assert state.run_dir == tmp_path
    assert "active" in state.messages[-1].text


def test_cache_read_weight_accepts_zero_and_rejects_non_finite():
    state = console.ConsoleState(cache_read_weight=1.0)
    console.apply_slash(state, "/cache-read-weight 0")
    assert state.cache_read_weight == 0
    console.apply_slash(state, "/cache-read-weight nan")
    assert state.cache_read_weight == 0
