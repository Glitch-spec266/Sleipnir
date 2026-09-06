"""Chat transport tests.

The fake sits at the *spawn* boundary — ``spawn=`` receives a scripted
process whose stdout carries real protocol bytes — so all of the parsing,
streaming, session bookkeeping and relaunch logic runs for real.

The Claude stream shape below reflects a live multi-turn probe against CLI
2.1.241 (persistent process, deltas via stream_event/text_delta, terminal
result event). The Codex shapes are verbatim captures from
`codex exec --json` (CLI 0.149.1): thread.started / turn.* are real; the
item.completed assistant_message shape is the documented success event.
Testing against remembered shapes is how you ship a parser reading the wrong
field for a year.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from sleipnir.chat import (
    ChatError,
    ChatSession,
    ClaudeTransport,
    CodexTransport,
    claude_stream_argv,
    codex_exec_argv,
    extract_codex_thread,
    user_envelope,
)


class ScriptedStdin:
    def __init__(self) -> None:
        self.buffer = bytearray()
        self.closed = False

    def write(self, data: bytes) -> None:
        self.buffer.extend(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class ScriptedProcess:
    """Implements enough of the subprocess surface for the transports."""

    def __init__(self) -> None:
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stdin = ScriptedStdin()
        self.pid = -1  # never a live pid; kill paths fall back to proc.kill()
        self.returncode: int | None = None

    def feed(self, payload: dict | str) -> None:
        line = payload if isinstance(payload, str) else json.dumps(payload)
        self.stdout.feed_data((line + "\n").encode("utf-8"))

    def fail(self, text: str) -> None:
        self.stderr.feed_data(text.encode("utf-8"))

    def end(self, code: int = 0) -> None:
        self.stdout.feed_eof()
        self.stderr.feed_eof()
        if self.returncode is None:
            self.returncode = code

    async def wait(self) -> int:
        return self.returncode if self.returncode is not None else 0

    def kill(self) -> None:
        self.returncode = -9


def claude_events() -> list[dict]:
    return [
        {"type": "system", "subtype": "init", "session_id": "s-1"},
        {"type": "stream_event", "event": {"delta": {"type": "text_delta", "text": "hel"}}},
        {"type": "stream_event", "event": {"delta": {"type": "text_delta", "text": "lo"}}},
        {
            "type": "result",
            "subtype": "success",
            "result": "hello",
            "session_id": "s-1",
            "total_cost_usd": 0.01,
        },
    ]


async def collect(iterator) -> list:
    return [event async for event in iterator]


# ---------------------------------------------------------------------------
# Claude transport
# ---------------------------------------------------------------------------


def test_claude_first_turn_opens_and_streams(monkeypatch, tmp_path):
    # Any directory that is not the repo will do; `/tmp` resolved to `C:\tmp`
    # on Windows, which exists on some machines and not on a CI runner.
    monkeypatch.chdir(tmp_path)
    procs: list[ScriptedProcess] = []
    argvs: list[list[str]] = []

    async def spawn(*argv, **kwargs):
        argvs.append(list(argv))
        proc = ScriptedProcess()
        procs.append(proc)
        for event in claude_events():
            proc.feed(event)
        proc.end()
        return proc

    session = ChatSession(provider="claude", session_id="abc-123")
    transport = ClaudeTransport(session, spawn=spawn, permission_mode="bypassPermissions")
    events = asyncio.run(collect(transport.turn("say hi")))

    assert [e.kind for e in events] == ["delta", "delta", "final"]
    assert events[0].text == "hel" and events[2].text == "hello"
    assert events[2].session_id == "s-1" and events[2].cost_usd == 0.01
    assert "--session-id abc-123".split() == argvs[0][argvs[0].index("--session-id"):][:2]
    assert session.opened is True
    envelope = json.loads(procs[0].stdin.buffer.decode())
    assert envelope["type"] == "user"
    assert envelope["message"]["content"][0]["text"] == "say hi"


def test_claude_second_turn_reuses_the_same_process():
    procs: list[ScriptedProcess] = []

    async def spawn(*argv, **kwargs):
        proc = ScriptedProcess()
        procs.append(proc)
        # Turn one's answer is ready at launch; a real CLI starts producing
        # immediately. Turn two's answer is fed by the test between turns.
        for event in claude_events():
            proc.feed(event)
        return proc  # left running: the persistent process must not exit

    session = ChatSession(provider="claude", session_id="abc-123")
    transport = ClaudeTransport(session, spawn=spawn)

    async def two_turns() -> None:
        await collect(transport.turn("one"))
        assert len(procs) == 1, "the persistent process must survive across turns"
        for event in claude_events():
            procs[0].feed(event)
        await collect(transport.turn("two"))

    asyncio.run(two_turns())
    assert len(procs) == 1
    envelopes = procs[0].stdin.buffer.decode().strip().splitlines()
    assert len(envelopes) == 2, "both turns went over the one stdin"


def test_claude_crash_relaunches_with_resume_not_a_new_session():
    argvs: list[list[str]] = []

    def make_spawn(events):
        async def spawn(*argv, **kwargs):
            argvs.append(list(argv))
            proc = ScriptedProcess()
            for event in events:
                proc.feed(event)
            proc.end()
            return proc
        return spawn

    session = ChatSession(provider="claude", session_id="abc-123")
    transport = ClaudeTransport(session, spawn=make_spawn(claude_events()))
    asyncio.run(collect(transport.turn("one")))

    transport._spawn = make_spawn([])  # next launch emits nothing: EOF mid-turn
    with pytest.raises(ChatError):
        asyncio.run(collect(transport.turn("two")))

    resumed = argvs[-1]
    assert "--resume" in resumed and "--session-id" not in resumed
    assert resumed[resumed.index("--resume") + 1] == "abc-123"


def test_claude_timeout_kills_the_wedge_and_raises():
    async def spawn(*argv, **kwargs):
        return ScriptedProcess()  # never emits anything

    session = ChatSession(provider="claude")
    transport = ClaudeTransport(session, spawn=spawn, timeout_s=0.05)
    with pytest.raises(ChatError, match="did not finish"):
        asyncio.run(collect(transport.turn("hello")))


def test_the_user_envelope_is_json_with_a_text_block():
    envelope = json.loads(user_envelope("hi there"))
    assert envelope["type"] == "user"
    assert envelope["message"]["role"] == "user"
    assert envelope["message"]["content"][0] == {"type": "text", "text": "hi there"}


def test_claude_stream_argv_carries_streaming_flags():
    argv = claude_stream_argv("x", resume=False, model="haiku")
    for flag in ("--input-format", "stream-json", "--output-format", "stream-json",
                 "--include-partial-messages", "--permission-mode"):
        assert flag in argv


# ---------------------------------------------------------------------------
# Codex transport
# ---------------------------------------------------------------------------


def codex_success_events() -> list[dict]:
    """Verbatim capture from a real `codex exec --json` run (CLI 0.149.1),
    trimmed of nothing but the prompt echo."""
    return [
        {"type": "thread.started", "thread_id": "01a03bc8-7a58-7c32-86b8-823d1c36e68e"},
        {"type": "turn.started"},
        {"type": "item.completed",
         "item": {"id": "item_0", "type": "agent_message", "text": "gamma"}},
        {"type": "turn.completed",
         "usage": {"input_tokens": 13983, "cached_input_tokens": 9984,
                    "cache_write_input_tokens": 0, "output_tokens": 5,
                    "reasoning_output_tokens": 0}},
    ]


def test_codex_first_turn_captures_thread_and_final_text():
    argvs: list[list[str]] = []

    async def spawn(*argv, **kwargs):
        argvs.append(list(argv))
        proc = ScriptedProcess()
        for event in codex_success_events():
            proc.feed(event)
        proc.end()
        return proc

    session = ChatSession(provider="codex")
    transport = CodexTransport(session, spawn=spawn, permission_mode="acceptEdits")
    events = asyncio.run(collect(transport.turn("reply gamma")))

    assert events[-1].kind == "final" and events[-1].text == "gamma"
    assert session.session_id == "01a03bc8-7a58-7c32-86b8-823d1c36e68e"
    assert session.opened is True
    assert "resume" not in argvs[0], "a fresh conversation must not claim a thread"
    assert argvs[0][-1] == "-", "the prompt travels over stdin"


def test_codex_second_turn_resumes_the_thread():
    argvs: list[list[str]] = []

    async def spawn(*argv, **kwargs):
        argvs.append(list(argv))
        proc = ScriptedProcess()
        for event in codex_success_events():
            proc.feed(event)
        proc.end()
        return proc

    session = ChatSession(provider="codex")
    transport = CodexTransport(session, spawn=spawn)
    asyncio.run(collect(transport.turn("one")))
    asyncio.run(collect(transport.turn("two")))
    resumed = argvs[1]
    # Live finding: resume takes its options BEFORE the session id.
    assert resumed.index("resume") < resumed.index("--json")
    assert resumed[-2] == "01a03bc8-7a58-7c32-86b8-823d1c36e68e"
    assert resumed[-1] == "-"


def test_codex_item_updates_stream_as_incremental_deltas():
    async def spawn(*argv, **kwargs):
        proc = ScriptedProcess()
        proc.feed({"type": "thread.started", "thread_id": "t-1"})
        proc.feed({"type": "item.started", "item": {"id": "i0", "item_type": "assistant_message"}})
        proc.feed({"type": "item.updated",
                   "item": {"id": "i0", "item_type": "assistant_message", "text": "par"}})
        proc.feed({"type": "item.updated",
                   "item": {"id": "i0", "item_type": "assistant_message", "text": "partial"}})
        proc.feed({"type": "item.completed",
                   "item": {"id": "i0", "item_type": "assistant_message", "text": "partial"}})
        proc.feed({"type": "turn.completed"})
        proc.end()
        return proc

    transport = CodexTransport(ChatSession(provider="codex"), spawn=spawn)
    events = asyncio.run(collect(transport.turn("go")))
    kinds = [e.kind for e in events]
    # Only growth streams: an unchanged item.completed emits nothing.
    assert kinds == ["delta", "delta", "final"]
    assert [e.text for e in events[:2]] == ["par", "tial"]
    assert events[-1].text == "partial"


def test_codex_failure_shapes_raise_chat_error_with_the_provider_message():
    for event in (
        {"type": "error", "message": "usage limit hit"},
        {"type": "turn.failed", "error": {"message": "usage limit hit"}},
    ):
        async def spawn(*argv, _event=event, **kwargs):
            proc = ScriptedProcess()
            proc.feed({"type": "thread.started", "thread_id": "t-9"})
            proc.feed(_event)
            proc.end()
            return proc

        transport = CodexTransport(ChatSession(provider="codex"), spawn=spawn)
        with pytest.raises(ChatError, match="usage limit hit"):
            asyncio.run(collect(transport.turn("hi")))


def test_codex_exit_without_a_completed_turn_is_an_error_not_an_empty_reply():
    async def spawn(*argv, **kwargs):
        proc = ScriptedProcess()
        proc.fail("boom: model overloaded")
        proc.end(code=1)
        return proc

    transport = CodexTransport(ChatSession(provider="codex"), spawn=spawn)
    with pytest.raises(ChatError, match="exited 1.*boom"):
        asyncio.run(collect(transport.turn("hi")))


def test_codex_sandbox_follows_the_console_posture():
    bypass = codex_exec_argv(permission_mode="bypassPermissions")
    cautious = codex_exec_argv(permission_mode="acceptEdits")
    assert bypass[bypass.index("--sandbox") + 1] == "danger-full-access"
    assert cautious[cautious.index("--sandbox") + 1] == "workspace-write"


def test_codex_resume_carries_the_posture_through_config_overrides():
    """Live finding: `exec resume` has no --sandbox flag. The posture must
    still hold, so it travels as a -c config override instead."""
    argv = codex_exec_argv(resume_thread="t-1", permission_mode="bypassPermissions")
    assert "--sandbox" not in argv
    override_index = argv.index("-c")
    assert 'sandbox_mode="danger-full-access"' in argv[override_index + 1]
    assert argv[-2] == "t-1" and argv[-1] == "-"


def test_codex_legacy_item_type_shape_still_parses():
    async def spawn(*argv, **kwargs):
        proc = ScriptedProcess()
        proc.feed({"type": "thread.started", "thread_id": "t-legacy"})
        proc.feed({"type": "item.completed",
                   "item": {"id": "i0", "item_type": "assistant_message", "text": "pong"}})
        proc.feed({"type": "turn.completed"})
        proc.end()
        return proc

    transport = CodexTransport(ChatSession(provider="codex"), spawn=spawn)
    events = asyncio.run(collect(transport.turn("hi")))
    assert events[-1].kind == "final" and events[-1].text == "pong"


def test_extract_codex_thread_reads_only_the_real_shape():
    captured = "".join(
        json.dumps(event) + "\n" for event in codex_success_events()[:1]
    )
    assert extract_codex_thread(captured) == "01a03bc8-7a58-7c32-86b8-823d1c36e68e"
    assert extract_codex_thread("{}\nnot json\n") is None


# ---------------------------------------------------------------------------
# Session identity
# ---------------------------------------------------------------------------


def test_unknown_providers_are_refused_at_session_construction():
    with pytest.raises(ChatError, match="unknown provider"):
        ChatSession(provider="gemini")


def test_codex_survives_an_event_line_longer_than_the_stream_limit():
    """Live, 2026-08-26: this killed a real handoff turn outright.

    `asyncio.StreamReader.readline` raises ValueError when a line exceeds its
    limit, and a Codex event carrying a read file easily does. The reader has
    already consumed past the separator by then, so the only sane response is
    to drop that one event and keep reading — the same thing already done with
    a line that will not parse as JSON.
    """
    async def spawn(*argv, **kwargs):
        proc = ScriptedProcess()
        events = codex_success_events()
        proc.feed(events[0])
        proc.feed('{"type": "item.completed", "junk": "' + "x" * 200_000 + '"}')
        for event in events[1:]:
            proc.feed(event)
        proc.end()
        return proc

    session = ChatSession(provider="codex")
    transport = CodexTransport(session, spawn=spawn)
    events = asyncio.run(collect(transport.turn("go")))

    assert events[-1].kind == "final" and events[-1].text == "gamma"


def test_claude_survives_an_event_line_longer_than_the_stream_limit():
    async def spawn(*argv, **kwargs):
        proc = ScriptedProcess()
        proc.feed('{"type": "stream_event", "junk": "' + "x" * 200_000 + '"}')
        for event in claude_events():
            proc.feed(event)
        return proc

    session = ChatSession(provider="claude")
    transport = ClaudeTransport(session, spawn=spawn, permission_mode="acceptEdits")
    events = asyncio.run(collect(transport.turn("go")))

    assert events[-1].kind == "final"


def test_a_real_spawn_asks_for_a_stream_limit_the_default_would_not_give():
    """The skip above is the backstop, not the plan.

    A dropped event is lost information — a final message, a thread id. The
    limit is raised at the spawn so that ordinary large events never reach the
    backstop at all.
    """
    seen: list[dict] = []

    async def spawn(*argv, **kwargs):
        seen.append(kwargs)
        proc = ScriptedProcess()
        for event in codex_success_events():
            proc.feed(event)
        proc.end()
        return proc

    session = ChatSession(provider="codex")
    asyncio.run(collect(CodexTransport(session, spawn=spawn).turn("go")))
    assert seen[0]["limit"] >= 8 * 1024 * 1024
