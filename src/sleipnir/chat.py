"""Where a typed message goes, and how it comes back.

Sleipnir is a harness, not a model.  This module is the whole of its opinion
about conversation: pick the recipient, hand over the text, and stream the
reply back as it is generated.

Two providers share one event contract.  A turn yields :class:`ChatEvent`
objects — ``delta`` chunks as tokens arrive, then one ``final`` event carrying
the authoritative reply text.  The console renders deltas into a growing
message, so time-to-first-visible-token is the model's first token rather than
the whole turn.

Latency design, measured before built:

* **Claude** keeps **one persistent process** for the whole conversation
  (``--input-format stream-json``).  Verified live on CLI 2.1.241: after a
  ``result`` event the process stays alive, accepts another user envelope over
  stdin, and continues the same session.  Every turn therefore skips the CLI
  start-up and the ~30k cache-creation spawn overhead entirely; only a crash
  pays a relaunch (with ``--resume``, so no context is lost).
* **Codex** is one ``codex exec --json`` subprocess per turn, resumed against
  the thread id the first turn returned.  Its JSONL events are parsed as they
  arrive, so replies still render incrementally even though the process is
  fresh.

No model name appears in source.  Model aliases are operator data supplied per
session; omitting one lets the authenticated account pick.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sleipnir.schema import Tier

#: Interactive providers selectable with ``/use`` in the console.
PROVIDERS: tuple[str, ...] = ("claude", "codex")

Spawner = Callable[..., Awaitable[Any]]


class ChatError(RuntimeError):
    """The recipient could not be reached or did not answer usefully."""


@dataclass(frozen=True)
class Reply:
    text: str
    speaker: str
    session_id: str | None = None
    cost_usd: float | None = None


@dataclass(frozen=True)
class ChatEvent:
    kind: str  # "delta" | "final"
    text: str = ""
    session_id: str | None = None
    cost_usd: float | None = None


@dataclass
class ChatSession:
    """One conversation with one provider.

    ``opened`` flips only once the provider has confirmed a live session —
    a failed first turn must not make the next turn send ``--resume`` for a
    session that was never created (the exact bug the old local
    ``first_turn`` flag could produce on timeouts).
    """

    provider: str
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    opened: bool = False

    def __post_init__(self) -> None:
        if self.provider not in PROVIDERS:
            raise ChatError(f"unknown provider {self.provider!r}")


#: Stream buffer for one provider event line. asyncio defaults to 64 KiB, and a
#: single JSONL event carrying a file the agent read goes past that easily —
#: observed live, where it ended the turn with
#: "Separator is found, but chunk is longer than limit".
STREAM_LIMIT = 16 * 1024 * 1024


async def _default_spawn(*argv: str, **kwargs: Any) -> Any:
    return await asyncio.create_subprocess_exec(*argv, **kwargs)


async def _readline(stream: Any) -> bytes | None:
    """One event line, or None when an oversized one had to be dropped.

    ``readline`` has already consumed past the separator when it raises, so
    continuing reads the next event cleanly. Dropping one unreadable event is
    what already happens to a line that will not parse as JSON; ending the
    operator's turn is not.
    """
    try:
        return await stream.readline()  # type: ignore[no-any-return]
    except ValueError:
        return None


async def _terminate_group(proc: Any, grace_s: float = 3.0) -> None:
    """TERM the process group, wait briefly, then KILL.

    The same contract as ProcessRunner: provider CLIs spawn children that would
    otherwise survive a bare SIGTERM to the parent and keep burning tokens.
    """
    if proc.returncode is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        with contextlib.suppress(Exception):
            proc.kill()
    with contextlib.suppress(TimeoutError, asyncio.CancelledError, ProcessLookupError):
        await asyncio.wait_for(proc.wait(), grace_s)
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        with contextlib.suppress(Exception):
            proc.kill()


# ---------------------------------------------------------------------------
# Claude — one persistent process, many turns
# ---------------------------------------------------------------------------


def claude_stream_argv(
    session_id: str,
    *,
    resume: bool,
    executable: str = "claude",
    permission_mode: str = "acceptEdits",
    model: str | None = None,
    add_dirs: tuple[Path, ...] = (),
) -> list[str]:
    """Build the headless multi-turn invocation.

    The prompt travels over stdin as JSON envelopes, never argv: argv is
    world-readable in ``/proc`` and a pasted file would blow past ``ARG_MAX``.
    ``model`` is an operator-supplied alias; omitted means the account chooses.
    """
    argv = [
        executable, "-p",
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--verbose",
        "--include-partial-messages",
    ]
    argv += ["--resume", session_id] if resume else ["--session-id", session_id]
    argv += ["--permission-mode", permission_mode]
    if model:
        argv += ["--model", model]
    for directory in add_dirs:
        argv += ["--add-dir", str(directory)]
    return argv


def user_envelope(prompt: str) -> bytes:
    """One user turn in the stream-json input protocol."""
    message = {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": prompt}]},
    }
    return json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"


class ClaudeTransport:
    """Owns the long-lived ``claude -p`` process for one session."""

    def __init__(
        self,
        session: ChatSession,
        *,
        permission_mode: str = "acceptEdits",
        model: str | None = None,
        add_dirs: tuple[Path, ...] = (),
        executable: str = "claude",
        spawn: Spawner | None = None,
        timeout_s: float = 900.0,
    ) -> None:
        self.session = session
        self.permission_mode = permission_mode
        self.model = model
        self.add_dirs = add_dirs
        self.executable = executable
        self.timeout_s = timeout_s
        self._spawn: Spawner = spawn or _default_spawn
        self._proc: Any | None = None
        self._stderr_tail = ""

    async def _ensure_process(self) -> Any:
        if self._proc is not None and self._proc.returncode is None:
            return self._proc
        argv = claude_stream_argv(
            self.session.session_id,
            # Resume whenever the session was ever opened, including across a
            # crash of our own persistent process: context lives provider-side.
            resume=self.session.opened,
            executable=self.executable,
            permission_mode=self.permission_mode,
            model=self.model,
            add_dirs=self.add_dirs,
        )
        self._proc = await self._spawn(
            *argv,
            limit=STREAM_LIMIT,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        self._stderr_tail = ""
        asyncio.ensure_future(self._drain_stderr(self._proc))
        return self._proc

    @staticmethod
    async def _drain_stderr(proc: Any) -> None:
        """Keep stderr empty so the CLI never blocks writing it.

        Retained tail explains a crash; everything else is discarded. The
        pump dies with the reader when the process exits.
        """
        tail_bytes = 8_192
        buffer = bytearray()
        try:
            while True:
                chunk = await proc.stderr.read(4_096)
                if not chunk:
                    return
                buffer.extend(chunk)
                if len(buffer) > tail_bytes:
                    del buffer[: len(buffer) - tail_bytes]
        except Exception:  # noqa: BLE001 - a closed pipe is not an error here
            return
        finally:
            proc._sleipnir_stderr_tail = buffer.decode("utf-8", "replace")

    async def turn(self, prompt: str) -> AsyncIterator[ChatEvent]:
        proc = await self._ensure_process()
        if proc.stdin is None or proc.stdout is None:
            raise ChatError("the claude process has no standard streams")
        try:
            proc.stdin.write(user_envelope(prompt))
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as error:
            await self._crash()
            raise ChatError("the claude session process had already exited") from error

        deltas: list[str] = []
        try:
            async with asyncio.timeout(self.timeout_s):
                while True:
                    line = await _readline(proc.stdout)
                    if line is None:
                        continue
                    if not line:
                        raise ChatError(
                            "claude closed its output before finishing the turn"
                            + self._tail_suffix()
                        )
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    kind = event.get("type")
                    if kind == "stream_event":
                        delta = event.get("event", {}).get("delta", {})
                        if delta.get("type") == "text_delta":
                            piece = delta.get("text", "")
                            deltas.append(piece)
                            yield ChatEvent(kind="delta", text=piece)
                    elif kind == "result":
                        text = event.get("result")
                        if not isinstance(text, str):
                            text = "".join(deltas)
                        self.session.opened = True
                        yield ChatEvent(
                            kind="final",
                            text=text,
                            session_id=event.get("session_id"),
                            cost_usd=event.get("total_cost_usd"),
                        )
                        return
        except TimeoutError as error:
            await self._crash()
            raise ChatError(
                f"claude did not finish the turn within {self.timeout_s:.0f}s"
            ) from error

    def _tail_suffix(self) -> str:
        tail = getattr(self._proc, "_sleipnir_stderr_tail", "") or self._stderr_tail
        trimmed = tail.strip()[:400]
        return f": {trimmed}" if trimmed else ""

    async def _crash(self) -> None:
        """Tear down a wedged process so the next turn relaunches cleanly."""
        if self._proc is not None:
            await _terminate_group(self._proc)
            self._proc = None

    async def close(self) -> None:
        if self._proc is not None:
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                if self._proc.stdin is not None:
                    self._proc.stdin.close()
            await _terminate_group(self._proc)
            self._proc = None


# ---------------------------------------------------------------------------
# Codex — exec per turn, resumed against the thread id
# ---------------------------------------------------------------------------


def _codex_sandbox_for(permission_mode: str) -> str:
    """Map the console posture onto Codex's own sandbox tiers.

    Full host control maps to full access; anything narrower keeps writes
    confined to the workspace until the unified policy layer replaces both
    mappings. Enforcement beats intention: Codex's sandbox is kernel-real.
    """
    return "danger-full-access" if permission_mode == "bypassPermissions" else "workspace-write"


def codex_exec_argv(
    *,
    resume_thread: str | None = None,
    executable: str = "codex",
    permission_mode: str = "acceptEdits",
    model: str | None = None,
) -> list[str]:
    """One non-interactive Codex invocation; the prompt arrives over stdin.

    ``-`` reads the prompt from stdin, keeping potentially long instructions
    out of world-readable argv. Verified against CLI 0.149.1, where the two
    entry points differ in surface: a fresh ``exec`` takes ``--sandbox``, but
    ``resume`` does not — its posture goes through ``-c sandbox_mode=…`` and
    its options come before the session id. Both found live.
    """
    sandbox = _codex_sandbox_for(permission_mode)
    argv = [executable, "exec"]
    if resume_thread:
        argv += ["resume", "--json", "--skip-git-repo-check"]
        argv += ["-c", f'sandbox_mode="{sandbox}"']
        if model:
            argv += ["--model", model]
        argv += [resume_thread, "-"]
    else:
        argv += ["--json", "--skip-git-repo-check"]
        argv += ["--sandbox", sandbox]
        if model:
            argv += ["--model", model]
        argv += ["-"]
    return argv


def extract_codex_thread(events_jsonl: str) -> str | None:
    """Pull the thread id out of a ``thread.started`` event."""
    for line in events_jsonl.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "thread.started":
            thread_id = event.get("thread_id")
            if isinstance(thread_id, str):
                return thread_id
    return None


class CodexTransport:
    """Runs ``codex exec`` once per turn, resuming the thread each time."""

    def __init__(
        self,
        session: ChatSession,
        *,
        permission_mode: str = "acceptEdits",
        model: str | None = None,
        executable: str = "codex",
        spawn: Spawner | None = None,
        timeout_s: float = 900.0,
    ) -> None:
        self.session = session
        self.permission_mode = permission_mode
        self.model = model
        self.executable = executable
        self.spawn = spawn or _default_spawn
        self.timeout_s = timeout_s

    async def turn(self, prompt: str) -> AsyncIterator[ChatEvent]:
        argv = codex_exec_argv(
            # The thread id only exists after the first successful turn;
            # resuming before that fails identically every time.
            resume_thread=self.session.session_id if self.session.opened else None,
            executable=self.executable,
            permission_mode=self.permission_mode,
            model=self.model,
        )
        proc = await self.spawn(
            *argv,
            limit=STREAM_LIMIT,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        if proc.stdin is None or proc.stdout is None:
            raise ChatError("the codex process has no standard streams")

        stderr_task = asyncio.ensure_future(_read_stream(proc.stderr))
        seen_text: dict[str, str] = {}
        assembled: list[str] = []
        failure: str | None = None
        finished = False
        try:
            proc.stdin.write(prompt.encode("utf-8"))
            await proc.stdin.drain()
            proc.stdin.close()
        except (BrokenPipeError, ConnectionResetError) as error:
            await _terminate_group(proc)
            raise ChatError("codex exited before reading its prompt") from error

        try:
            async with asyncio.timeout(self.timeout_s):
                while True:
                    line = await _readline(proc.stdout)
                    if line is None:
                        continue
                    if not line:
                        break
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    kind = event.get("type")
                    if kind == "thread.started":
                        thread_id = event.get("thread_id")
                        if isinstance(thread_id, str):
                            self.session.session_id = thread_id
                            self.session.opened = True
                    elif kind in ("item.started", "item.updated", "item.completed"):
                        item = event.get("item") or {}
                        if _is_assistant_item(item):
                            item_id = str(item.get("id", ""))
                            text = item.get("text", "") or ""
                            previous = seen_text.get(item_id, "")
                            if len(text) > len(previous):
                                piece = text[len(previous):]
                                seen_text[item_id] = text
                                assembled.append(piece)
                                yield ChatEvent(kind="delta", text=piece)
                    elif kind == "error":
                        failure = str(event.get("message", "codex reported an error"))
                    elif kind == "turn.failed":
                        detail = event.get("error") or {}
                        failure = str(detail.get("message") or "codex turn failed")
                    elif kind == "turn.completed":
                        finished = True
        except TimeoutError as error:
            await _terminate_group(proc)
            raise ChatError(
                f"codex did not finish the turn within {self.timeout_s:.0f}s"
            ) from error

        stderr_tail = (await stderr_task)[:400].strip()
        code = await proc.wait()
        if failure:
            raise ChatError(failure)
        if not finished:
            raise ChatError(
                f"codex exited {code} before completing the turn"
                + (f": {stderr_tail}" if stderr_tail else "")
            )
        yield ChatEvent(
            kind="final",
            text="".join(assembled),
            session_id=self.session.session_id,
        )

    async def close(self) -> None:
        """Match the shared transport lifecycle; Codex has no persistent process."""
        return None


def _is_assistant_item(item: dict[str, Any]) -> bool:
    # Two shapes exist across CLI versions: the documented
    # {"item_type": "assistant_message"} and the live-captured (0.149.1)
    # {"type": "agent_message"}. Accept both; text is the payload either way.
    return (item.get("item_type") or item.get("type")) in (
        "assistant_message",
        "agent_message",
    )


async def _read_stream(reader: Any, limit: int = 8_192) -> str:
    buffer = bytearray()
    with contextlib.suppress(Exception):  # stderr shape is advisory only
        while True:
            chunk = await reader.read(4_096)
            if not chunk:
                break
            buffer.extend(chunk)
            if len(buffer) > limit:
                del buffer[: limit - 4096]
    return buffer.decode("utf-8", "replace")


def transport_for(
    session: ChatSession,
    *,
    permission_mode: str,
    model: str | None,
    add_dirs: tuple[Path, ...] = (),
    spawn: Spawner | None = None,
) -> ClaudeTransport | CodexTransport:
    match session.provider:
        case "claude":
            return ClaudeTransport(
                session,
                permission_mode=permission_mode,
                model=model,
                add_dirs=add_dirs,
                spawn=spawn,
            )
        case "codex":
            return CodexTransport(
                session,
                permission_mode=permission_mode,
                model=model,
                spawn=spawn,
            )
    raise ChatError(f"no transport for provider {session.provider!r}")


# ---------------------------------------------------------------------------
# The stand-in: a cheap model answering from bounded state
# ---------------------------------------------------------------------------

ROUTER_SYSTEM = """\
You are Sleipnir's duty officer while the orchestrator is asleep mid-build.
You are given a constant-size manifest of run state — counts, group rollups and
failing task ids. You have NOT been given, and must not ask for, any task
output, file content or transcript.

Answer the operator's message in at most four sentences using only the manifest.
If the message asks for a change to the plan rather than information, do not
attempt it: reply that it has been queued for the orchestrator, and end your
reply with a line of the form QUEUE: <one-line instruction>.
"""


def router_model(config: object, tier: Tier = Tier.EXTRACT) -> str:
    """Pick the duty-officer model from operator policy, never from source."""
    policy = config.policy(tier)  # type: ignore[attr-defined]
    for backend_name in policy.prefer:
        backend = config.backends.get(backend_name)  # type: ignore[attr-defined]
        if backend and backend.models:
            return backend.models[0].id
    raise ChatError(
        f"no model configured for the {tier.value} tier; the console needs one "
        "to answer while the orchestrator is asleep"
    )


async def ask_router(
    prompt: str,
    manifest_json: str,
    model: str,
    *,
    api_key: str | None = None,
    timeout_s: float = 60.0,
) -> Reply:
    """Ask the cheap model, giving it the manifest and nothing else."""
    import httpx

    key = api_key or os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise ChatError("OPENROUTER_API_KEY is not set; cannot answer while the brain sleeps")
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        response = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": ROUTER_SYSTEM},
                    {"role": "user", "content": f"RUN MANIFEST:\n{manifest_json}\n\nOPERATOR: {prompt}"},
                ],
                "max_tokens": 400,
            },
        )
    if response.status_code != 200:
        raise ChatError(f"router model returned HTTP {response.status_code}")
    payload = response.json()
    try:
        text = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise ChatError("router model returned no message") from error
    return Reply(text=text, speaker="router")


def extract_queued_instruction(text: str) -> str | None:
    """Pull the ``QUEUE:`` line out of a duty-officer reply, if there is one.

    Parsed here rather than trusted as an action: the returned string is only
    ever shown to the operator and handed to the brain as text.  It is never
    executed and never mutates the plan — plan changes go only through the
    revision applier in ``revisions`` and its operator-review gate, unchanged.
    """
    for line in reversed(text.splitlines()):
        stripped = line.strip()
        if stripped.upper().startswith("QUEUE:"):
            instruction = stripped[6:].strip()
            return instruction or None
    return None


__all__ = [
    "PROVIDERS",
    "ChatError",
    "ChatEvent",
    "ChatSession",
    "ClaudeTransport",
    "CodexTransport",
    "Reply",
    "ROUTER_SYSTEM",
    "ask_router",
    "claude_stream_argv",
    "codex_exec_argv",
    "extract_codex_thread",
    "extract_queued_instruction",
    "router_model",
    "transport_for",
    "user_envelope",
]
