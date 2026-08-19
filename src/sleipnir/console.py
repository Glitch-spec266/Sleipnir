"""The Sleipnir console: the window you actually talk to.

What this is, structurally: a full-screen renderer that owns the terminal, plus
a message router.  It is *not* a second Claude.  A message you type is handed
to the real ``claude`` CLI — Sleipnir's job is to decide **who** receives it and
to widen what the receiver can do, not to answer for it.

Routing is the interesting part.  The brain is expensive and context-bound, so
it is not always listening:

* **Brain awake** (no run in flight, or the run has hit a gate): ordinary
  messages pass through a tool-free Haiku capability check. A confident check
  lets Haiku act; anything else fails closed to Sonnet. ``/project`` instead
  launches the planner and routed multi-model orchestration pipeline.
* **Brain asleep** (workers are building): waking the brain for "how's it
  going?" would burn the exact context the whole design protects.  A cheap
  OpenRouter model reads the message instead and either answers it from the
  bounded manifest or files it against a build loop for the brain to see when
  it next wakes.

Rendering runs in raw mode at a fixed frame rate so the border can flicker
while you type.  Input is read byte-by-byte rather than through ``input()``,
because ``input()`` owns the cursor and cannot coexist with a redraw loop.
"""

from __future__ import annotations

import asyncio
import codecs
import contextlib
import os
import re
import shutil
import sys
import termios
import tempfile
import tty
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sleipnir import theme
from sleipnir.process import ProcessRunner

FRAME_INTERVAL_S = 1 / 12  # fast enough for flicker, cheap enough to ignore

# The console is the only place Sleipnir tells the model what host powers it
# has. Workers never see this text — they keep the confined sandbox.
CAPABILITY_BRIEF = """\
You are running inside Sleipnir, a harness that extends you with host control.
These are real shell commands available to you via Bash:

  {exe} computer screenshot <path>     capture the screen to a PNG you can read
  {exe} computer type <text>           type into the focused window
  {exe} computer key <combo>           press a chord, e.g. ctrl+shift+t
  {exe} computer copy                  press ctrl+shift+c; preserves text/image MIME
  {exe} computer paste                 press ctrl+shift+v into the focused app
  {exe} computer click [left|right]    click at the pointer
  {exe} computer move <x> <y>          move the pointer
  {exe} computer scroll <amount>       scroll the focused window
  {exe} browser open <url>             drive a real logged-in Chromium
  {exe} browser text [selector]        read the current page
  {exe} browser click <selector>
  {exe} browser fill <selector> <text>
  {exe} secret prompt "<label>"        ask the operator for a credential

Input is injected at the kernel level, so it reaches every window on this
Wayland desktop exactly as a physical keyboard would. Take a screenshot and
look at it before clicking blind.

The last command matters most: you never see credentials. `secret prompt` opens
a field inside Sleipnir, the operator types the value, and it is injected
straight into the focused window. It is never stored, logged, or shown to you.
When a flow needs a login, call it rather than asking the operator to paste
anything into this conversation.
"""


def capability_brief() -> str:
    """The brief, with this install's real executable path substituted in.

    Hard-coding ``sleipnir`` would be a coin flip: the model's Bash may not
    have the virtualenv on ``PATH``, and a capability that silently resolves to
    "command not found" looks to the model like the feature does not exist.
    """
    executable = shutil.which("sleipnir") or f"{sys.executable} -m sleipnir.cli"
    return CAPABILITY_BRIEF.format(exe=executable)


@dataclass
class Message:
    role: str
    text: str
    at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class ConsoleState:
    """Everything the renderer needs, and nothing it does not.

    Notably absent: any artifact content or worker transcript.  The console
    obeys the same rule as the dashboard — it renders plan-level state and the
    operator's own conversation, never subtask output.
    """

    messages: list[Message] = field(default_factory=list)
    input_buffer: str = ""
    brain_awake: bool = True
    status: str = "ready"
    busy: bool = False
    run_dir: Path | None = None
    #: Base under which a bare console allocates one fresh run per `/project`.
    project_base: Path | None = None
    #: An operator-supplied --run-root is exact and must not be silently nested.
    run_root_explicit: bool = False
    config_path: Path | None = None
    cache_read_weight: float = 1.0
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    frame: int = 0
    #: Host control is the product, so the console does not stop to ask before
    #: every click and keystroke.  Narrowing this to ``acceptEdits`` turns
    #: Sleipnir back into an ordinary headless Claude with no reach outside the
    #: repository — correct for a cautious session, useless for the desk robot.
    permission_mode: str = "bypassPermissions"
    #: Instructions the duty officer took while the brain slept. Text only —
    #: handed to the brain on its next turn, never executed here.
    queued_for_brain: list[str] = field(default_factory=list)
    #: Directories containing clipboard images explicitly attached by the
    #: operator. Added to Claude's allowed roots; never available to workers.
    attachment_dirs: set[Path] = field(default_factory=set)
    #: Default alias passed to `claude --model` for conversation and judgement.
    #: The operator can replace it per session.
    model: str | None = "sonnet"
    #: Alias for ordinary requests after a separate tool-free capability check.
    #: A false negative costs a stronger turn; a false positive can act
    #: incorrectly on the live desktop, so uncertainty falls back to ``model``.
    fast_model: str | None = "haiku"
    #: Set while a credential is being typed: the buffer is not echoed and is
    #: never added to the transcript.
    secret_request: object | None = None

    def add(self, role: str, text: str) -> None:
        self.messages.append(Message(role=role, text=text))


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_ROLE_LEVEL = {
    "you": theme.BRIGHT,
    "sleipnir": theme.NORMAL,
    "claude": theme.NORMAL + 1,
    "router": theme.DIM + 1,
    "error": theme.NORMAL,
}


def _wrap(text: str, width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for word in paragraph.split(" "):
            candidate = f"{current} {word}".strip()
            if len(candidate) <= width:
                current = candidate
                continue
            if current:
                lines.append(current)
            # A single word longer than the pane is hard-split rather than
            # allowed to overflow and break the border.
            while len(word) > width:
                lines.append(word[:width])
                word = word[width:]
            current = word
        lines.append(current)
    return lines


def _clip(value: str) -> str:
    """Model and provider text is untrusted; strip anything non-printable.

    Same trust boundary as the dashboard: a reply containing raw escape bytes
    must not be able to repaint the screen or move the cursor.
    """
    return "".join(character if character.isprintable() else " " for character in value)


def render(state: ConsoleState, *, width: int, height: int, colour: bool = True) -> str:
    inner = max(20, width - 4)
    body_height = max(6, height - 6)
    lines: list[str] = []

    # The banner is all-or-nothing. Drawing one row of a multi-row emblem
    # renders as broken debris; `art[:1]` looks like tidy truncation and is not.
    art = theme.logo_lines(width)
    if height >= len(art) + 12:
        lines.extend(theme.paint(line, theme.NORMAL + 1, colour=colour) for line in art)
        lines.append("")
    elif height > 12:
        lines.append(theme.paint(theme.COMPACT_LOGO[0], theme.NORMAL + 1, colour=colour))
        lines.append("")

    rendered: list[str] = []
    for message in state.messages:
        level = _ROLE_LEVEL.get(message.role, theme.NORMAL)
        prefix = f"{message.at:%H:%M} {message.role} ▸ "
        wrapped = _wrap(_clip(message.text), inner - len(prefix))
        for index, chunk in enumerate(wrapped):
            head = prefix if index == 0 else " " * len(prefix)
            rendered.append(theme.paint(head + chunk, level, colour=colour))

    # Newest content wins the available space; scrollback lives in the log.
    visible = rendered[-(body_height - len(lines)):] if rendered else []
    lines.extend(visible)
    lines.extend([""] * max(0, body_height - len(lines)))

    lines.append(theme.paint("─" * inner, theme.DIM, colour=colour))
    caret = "…" if state.busy else "▌" if state.frame % 8 < 4 else " "
    if state.secret_request is not None:
        # Masked. The buffer is never echoed, never wrapped into the transcript,
        # and never leaves this process.
        label = _clip(str(getattr(state.secret_request, "label", "credential")))
        prompt = f"🔒 {label}: {'•' * len(state.input_buffer)}{caret}"
    else:
        prompt = f"› {_clip(state.input_buffer)}{caret}"
    lines.append(theme.paint(prompt[-inner:], theme.BRIGHT, colour=colour))

    where = "brain awake" if state.brain_awake else "brain asleep · routed"
    # Full host control is the point of this tool, and it is also the most
    # consequential fact about the session — so it is stated on screen for as
    # long as it is true, rather than behind a prompt that gets clicked through
    # once and forgotten.
    reach = "FULL HOST CONTROL" if state.permission_mode == "bypassPermissions" else "ask-first"
    footer = f"{where} · {reach} · {state.status} · ctrl-c to exit"
    return theme.frame(
        "\n".join(lines),
        width=width,
        frame_number=state.frame,
        title="SLEIPNIR",
        footer=footer[: max(4, width - 8)],
        colour=colour,
    )


# ---------------------------------------------------------------------------
# Terminal ownership
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def raw_terminal():
    """Own the terminal, and give it back whatever happens.

    Restoring in a ``finally`` is not optional: leaving cbreak mode set after a
    crash leaves the user's shell with no echo, which looks like a hung
    machine.
    """
    stream = sys.stdin
    if not stream.isatty():
        yield False
        return
    saved = termios.tcgetattr(stream)
    try:
        tty.setcbreak(stream.fileno())
        sys.stdout.write(
            theme.ENTER_FULLSCREEN + theme.ENABLE_BRACKETED_PASTE + theme.HIDE_CURSOR
        )
        sys.stdout.flush()
        yield True
    finally:
        termios.tcsetattr(stream, termios.TCSADRAIN, saved)
        sys.stdout.write(
            theme.DISABLE_BRACKETED_PASTE
            + theme.SHOW_CURSOR
            + theme.RESET
            + theme.EXIT_FULLSCREEN
        )
        sys.stdout.flush()


def _paint(text: str) -> None:
    sys.stdout.write(theme.CLEAR + text)
    sys.stdout.flush()


async def play_splash(*, colour: bool = True) -> None:
    width, height = shutil.get_terminal_size((90, 26))
    for index in range(theme.SPLASH_FRAMES):
        _paint(theme.splash_frame(index, width=width, height=height, colour=colour))
        await asyncio.sleep(0.035)


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------

BACKSPACE = ("\x7f", "\x08")
INTERRUPT = "\x03"
ENTER = ("\r", "\n")
CLIPBOARD_PASTE = "\x16"  # Ctrl+V when the terminal forwards Ctrl+Shift+V
BRACKETED_PASTE_START = "\x1b[200~"
BRACKETED_PASTE_END = "\x1b[201~"
_CSI = re.compile(r"^\x1b\[[0-?]*[ -/]*[@-~]")


@dataclass(frozen=True)
class PastedText:
    text: str


class TerminalInputDecoder:
    """Turn a byte stream into keys and atomic bracketed-paste events."""

    def __init__(self) -> None:
        self._utf8 = codecs.getincrementaldecoder("utf-8")("ignore")
        self._buffer = ""
        self._paste: list[str] | None = None

    @staticmethod
    def _partial_suffix(value: str, marker: str) -> int:
        return max(
            (length for length in range(1, min(len(value), len(marker) - 1) + 1)
             if marker.startswith(value[-length:])),
            default=0,
        )

    def feed(self, data: bytes) -> list[str | PastedText]:
        self._buffer += self._utf8.decode(data)
        events: list[str | PastedText] = []
        while self._buffer:
            if self._paste is not None:
                end = self._buffer.find(BRACKETED_PASTE_END)
                if end >= 0:
                    self._paste.append(self._buffer[:end])
                    events.append(PastedText("".join(self._paste)))
                    self._paste = None
                    self._buffer = self._buffer[end + len(BRACKETED_PASTE_END):]
                    continue
                held = self._partial_suffix(self._buffer, BRACKETED_PASTE_END)
                self._paste.append(self._buffer[:-held] if held else self._buffer)
                self._buffer = self._buffer[-held:] if held else ""
                break

            if self._buffer.startswith(BRACKETED_PASTE_START):
                self._buffer = self._buffer[len(BRACKETED_PASTE_START):]
                self._paste = []
                continue
            if BRACKETED_PASTE_START.startswith(self._buffer):
                break
            if self._buffer.startswith("\x1b"):
                match = _CSI.match(self._buffer)
                if match:
                    self._buffer = self._buffer[match.end():]
                    continue
                # Hold a split CSI sequence, but discard an unsupported escape
                # once another complete byte proves it is not bracketed paste.
                if self._buffer.startswith("\x1b[") and not re.search(
                    r"[@-~]$", self._buffer[2:]
                ):
                    break
                self._buffer = self._buffer[1:]
                continue
            events.append(self._buffer[0])
            self._buffer = self._buffer[1:]
        return events


def _clean_paste(text: str) -> str:
    """Keep human text and line structure; drop terminal control bytes."""
    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    return "".join(char for char in normalised if char in "\n\t" or char.isprintable())


def paste_system_clipboard(state: ConsoleState, *, allow_images: bool = True) -> str:
    """Insert clipboard text, or attach an image by private filesystem path."""
    from sleipnir.capabilities import clipboard

    try:
        payload = clipboard.read()
    except clipboard.ClipboardError as error:
        state.add("error", str(error))
        return "failed"
    if payload.kind == "text":
        state.input_buffer += _clean_paste(payload.text or "")
        return "text"
    if not allow_images or payload.path is None:
        state.add("error", "An image cannot be pasted into a credential field.")
        return "failed"
    state.attachment_dirs.add(payload.path.parent)
    spacer = "\n" if state.input_buffer else ""
    state.input_buffer += f"{spacer}[Attached clipboard image: {payload.path}]"
    return "image"


def apply_key(state: ConsoleState, char: str) -> str | None:
    """Fold one keypress into the buffer; return a submitted line, if any.

    Split out as a pure function so the whole editing surface is testable
    without a terminal — the loop below then has nothing in it but I/O.
    """
    if char in ENTER:
        line = state.input_buffer.strip()
        state.input_buffer = ""
        return line or None
    if char in BACKSPACE:
        state.input_buffer = state.input_buffer[:-1]
        return None
    if char == "\x15":  # ctrl-u, clear line
        state.input_buffer = ""
        return None
    if char.isprintable():
        state.input_buffer += char
    return None


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------


def refresh_brain_state(state: ConsoleState) -> None:
    """The brain is asleep exactly when a run owns the directory.

    Derived, never stored — the same rule as task status. An owned run lock
    means an executor is mid-build, which is precisely when waking the reason
    tier for a status question is most expensive and least useful.
    """
    from sleipnir.runlog import run_is_active

    state.brain_awake = not (state.run_dir is not None and run_is_active(state.run_dir))


def run_digest(run_dir: Path) -> str:
    """A constant-size picture of the run, for the duty officer.

    This is the whole reason a cheap model can stand in for the brain: the
    verdict is per-group counts and failed ids, so it neither grows with the
    plan nor carries a single byte a worker wrote.
    """
    import json

    from sleipnir.gate import evaluate_gate
    from sleipnir.projection import fold_results
    from sleipnir.revisions import read_staleness
    from sleipnir.runlog import ResultLog
    from sleipnir.schema import Plan

    plan = Plan.model_validate_json((run_dir / "plan.json").read_text(encoding="utf-8"))
    records = ResultLog(run_dir / "results.jsonl").read()
    states = fold_results(plan, records, staled_at=read_staleness(run_dir / "revisions.jsonl"))
    verdict = evaluate_gate(plan, states)
    return json.dumps(
        {
            "goal": plan.goal,
            "revision": plan.revision,
            "quiescent": verdict.quiescent,
            "groups": [
                {
                    "group": group.group,
                    "state": group.state.value,
                    "total": group.total,
                    "done": group.done,
                    "failed": group.failed,
                    "running": group.running,
                    "failed_task_ids": list(group.failed_task_ids[:8]),
                }
                for group in verdict.groups
            ],
        },
        separators=(",", ":"),
    )


def project_goal(text: str) -> str | None:
    """Return the goal for an exact ``/project`` command, else ``None``."""
    command, separator, remainder = text.strip().partition(" ")
    if command != "/project":
        return None
    return remainder.strip() if separator else ""


def _project_argv(state: ConsoleState, *command: str) -> list[str]:
    """Build a child CLI invocation using the console's own workspace policy."""
    run_root = state.run_dir or Path.cwd()
    argv = [
        sys.executable,
        "-m",
        "sleipnir.cli",
        "--run-root",
        str(run_root),
        "--cache-read-weight",
        str(state.cache_read_weight),
    ]
    if state.config_path is not None:
        argv += ["--config", str(state.config_path)]
    return [*argv, *command]


def _allocate_project_run(state: ConsoleState, goal: str) -> Path:
    """Choose a collision-resistant workspace for one `/project` invocation."""
    if state.run_root_explicit:
        if state.run_dir is None:  # pragma: no cover - cmd_console establishes it
            raise RuntimeError("explicit project run root is unavailable")
        state.run_dir.mkdir(parents=True, exist_ok=True)
        return state.run_dir
    base = state.project_base or Path.cwd()
    slug = re.sub(r"[^a-z0-9]+", "-", goal.lower()).strip("-")[:40] or "project"
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    run_dir = base / "runs" / f"{stamp}-{slug}-{uuid.uuid4().hex[:6]}"
    run_dir.mkdir(parents=True)
    state.run_dir = run_dir
    return run_dir


async def _run_project_stage(
    state: ConsoleState,
    *command: str,
    runner: ProcessRunner | None = None,
) -> str:
    """Run one project stage without letting its output corrupt the console."""
    process_runner = runner or ProcessRunner()
    with tempfile.TemporaryDirectory(prefix="sleipnir-project-") as temporary:
        directory = Path(temporary)
        stdout_path = directory / "stdout.log"
        stderr_path = directory / "stderr.log"
        result = await process_runner.run(
            _project_argv(state, *command),
            cwd=state.run_dir or Path.cwd(),
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            timeout_s=None,
        )
        out = stdout_path.read_text(encoding="utf-8", errors="replace").strip()
        err = stderr_path.read_text(encoding="utf-8", errors="replace").strip()
        if result.exit_code != 0:
            detail = (err or out or "no diagnostic output")[-2_000:]
            raise RuntimeError(
                f"project stage {command[0]!r} exited {result.exit_code}: {detail}"
            )
        return "\n".join(part for part in (out, err) if part)


async def _run_project(state: ConsoleState, goal: str) -> None:
    """Plan and execute a goal through Sleipnir's real multi-model pipeline."""
    _allocate_project_run(state, goal)
    state.status = "project · planning"
    plan_output = await _run_project_stage(state, "plan", goal)
    state.add(
        "sleipnir",
        f"Project plan created. Starting routed execution.\n{plan_output[-2_000:]}",
    )
    state.status = "project · orchestrating"
    run_output = await _run_project_stage(state, "orchestrate")
    state.add("sleipnir", f"Project workflow finished.\n{run_output[-4_000:]}")


async def _ask_duty_officer(state: ConsoleState, text: str) -> None:
    """Answer from bounded run state without spending a reason-tier spawn."""
    from sleipnir import chat
    from sleipnir.config import SleipnirConfig

    if state.run_dir is None or not (state.run_dir / "plan.json").exists():
        state.add("sleipnir", "A run holds the lock, but there is no plan here to report on.")
        return
    digest = run_digest(state.run_dir)
    config_path = SleipnirConfig.discover(state.run_dir)
    if config_path is None:
        state.add("sleipnir", "No sleipnir.toml here, so there is no duty-officer model to ask.")
        return
    config = SleipnirConfig.load(config_path)
    reply = await chat.ask_router(text, digest, chat.router_model(config))
    state.add("router", reply.text)
    queued = chat.extract_queued_instruction(reply.text)
    if queued:
        # Recorded as text for the brain's next cycle, never executed. Plan
        # changes still go only through revisions.apply_revision.
        state.queued_for_brain.append(queued)
        state.add("sleipnir", f"Queued for the orchestrator: {queued}")


def _claude_dirs(state: ConsoleState) -> tuple[Path, ...]:
    directories = set(state.attachment_dirs)
    if state.run_dir is not None:
        directories.add(state.run_dir)
    return tuple(sorted(directories))


async def _handle(state: ConsoleState, text: str, *, first_turn: list[bool]) -> None:
    """Send one operator message to whoever is on duty."""
    from sleipnir import chat

    refresh_brain_state(state)
    state.busy = True
    state.status = "thinking" if state.brain_awake else "routing"
    try:
        goal = project_goal(text)
        if goal is not None:
            if not goal:
                state.add("error", "Usage: /project <goal>")
                return
            await _run_project(state, goal)
            return
        if state.brain_awake:
            queued = ""
            if state.queued_for_brain:
                queued = (
                    "\n\nQueued while you were asleep:\n"
                    + "\n".join(f"- {item}" for item in state.queued_for_brain)
                )
                state.queued_for_brain.clear()
            base_prompt = f"{capability_brief()}\n\n{text}" if first_turn[0] else text
            if state.fast_model:
                state.status = "checking · fast lane"
                assessment_error: chat.ChatError | None = None
                try:
                    assessment = await chat.ask_claude(
                        f"{chat.FAST_LANE_ASSESSMENT}\n\n{base_prompt}{queued}",
                        state.session_id,
                        resume=not first_turn[0],
                        permission_mode=state.permission_mode,
                        model=state.fast_model,
                        tools=(),
                        add_dirs=_claude_dirs(state),
                    )
                except chat.ChatError as error:
                    # This turn had physically no tools, so retrying the original
                    # request cannot duplicate a side effect. A first-turn CLI
                    # failure may have reserved its session id without creating
                    # resumable state; rotate before opening the strong lane.
                    assessment_error = error
                    assessment = None
                    if first_turn[0]:
                        state.session_id = str(uuid.uuid4())
                if assessment is None:
                    state.status = "escalating · strong lane"
                    reply = await chat.ask_claude(
                        base_prompt + queued,
                        state.session_id,
                        resume=not first_turn[0],
                        permission_mode=state.permission_mode,
                        model=state.model,
                        add_dirs=_claude_dirs(state),
                    )
                    first_turn[0] = False
                    if assessment_error is not None:
                        state.add(
                            "sleipnir",
                            "The tool-free Haiku check was unavailable; Sonnet handled "
                            "the original request without replaying any action.",
                        )
                    state.add("claude", reply.text)
                    return
                first_turn[0] = False
                if chat.fast_lane_capable(assessment):
                    state.status = "acting · fast lane"
                    state.add(
                        "sleipnir",
                        f"Fast lane approved; {state.fast_model or 'fast model'} is acting.",
                    )
                    reply = await chat.ask_claude(
                        "The tool-free capability check passed. Complete the operator's "
                        "preceding request now.",
                        state.session_id,
                        resume=True,
                        permission_mode=state.permission_mode,
                        model=state.fast_model,
                        add_dirs=_claude_dirs(state),
                    )
                else:
                    state.status = "escalating · strong lane"
                    state.add(
                        "sleipnir",
                        "Fast lane declined or failed closed; routing the untouched "
                        f"request to {state.model or 'the strong model'}.",
                    )
                    reply = await chat.ask_claude(
                        "The tool-free fast-lane check declined or failed closed. "
                        "Complete the operator's preceding request now.",
                        state.session_id,
                        resume=True,
                        permission_mode=state.permission_mode,
                        model=state.model,
                        add_dirs=_claude_dirs(state),
                    )
            else:
                reply = await chat.ask_claude(
                    base_prompt + queued,
                    state.session_id,
                    resume=not first_turn[0],
                    permission_mode=state.permission_mode,
                    model=state.model,
                    add_dirs=_claude_dirs(state),
                )
                first_turn[0] = False
            state.add("claude", reply.text)
        else:
            await _ask_duty_officer(state, text)
    except Exception as error:  # noqa: BLE001 - the console must never die on a reply
        state.add("error", f"{type(error).__name__}: {error}")
    finally:
        state.busy = False
        state.status = "ready"


def submit_secret(state: ConsoleState, typed: str) -> str:
    """Fulfil a pending credential request from the console's own input.

    The plaintext lives in a byte buffer for the duration of one injection and
    is wiped. Nothing about it is added to the transcript — only the fact that
    it happened.
    """
    from sleipnir.capabilities import handoff, secrets

    request = state.secret_request
    state.secret_request = None
    if request is None:  # pragma: no cover - defensive
        return "cancelled"
    if not typed:
        handoff.answer(request, "cancelled")
        state.add("sleipnir", f"Credential request for {request.label!r} cancelled.")
        return "cancelled"
    secret = secrets.Secret(label=request.label, _buffer=bytearray(typed.encode("utf-8")))
    try:
        secrets.type_into_focused_window(secret, submit=request.submit)
        handoff.answer(request, "supplied")
        state.add("sleipnir", f"Credential for {request.label!r} typed into the focused window.")
        return "supplied"
    except Exception as error:  # noqa: BLE001 - never leak a value through a traceback
        secret.wipe()
        handoff.answer(request, "failed")
        state.add("error", f"could not deliver the credential: {type(error).__name__}")
        return "failed"


def poll_secret_request(state: ConsoleState) -> None:
    """Notice a tool subprocess asking for a credential."""
    from sleipnir.capabilities import handoff

    if state.secret_request is not None or state.busy:
        return
    request = handoff.pending()
    if request is not None:
        state.secret_request = request
        state.add(
            "sleipnir",
            f"A credential is needed: {request.label}. Type it below — it is masked, "
            "never stored, and never shown to the model that asked.",
        )


async def run_console(state: ConsoleState | None = None, *, splash: bool = True) -> int:
    """Own the terminal until the operator leaves."""
    state = state or ConsoleState()
    colour = theme.supports_colour()
    first_turn = [True]
    pending: set[asyncio.Task[None]] = set()

    with raw_terminal() as interactive:
        if splash:
            await play_splash(colour=colour)
        if not interactive:
            return 0

        loop = asyncio.get_running_loop()
        keys: asyncio.Queue[str | PastedText] = asyncio.Queue()
        decoder = TerminalInputDecoder()

        def _on_readable() -> None:
            data = os.read(sys.stdin.fileno(), 8192)
            for event in decoder.feed(data):
                keys.put_nowait(event)

        loop.add_reader(sys.stdin.fileno(), _on_readable)
        state.add(
            "sleipnir",
            "Ready. Ordinary requests use the guarded fast lane; /project <goal> "
            "starts the multi-model workflow. Claude Code has keyboard, mouse, "
            "screen, browser and shell. Run with --ask-first to confirm each action."
            if state.permission_mode == "bypassPermissions"
            else "Ready. Host actions will be confirmed with you before they run; "
            "/project <goal> starts the multi-model workflow.",
        )
        try:
            while True:
                width, height = shutil.get_terminal_size((90, 26))
                _paint(render(state, width=width, height=height, colour=colour))
                state.frame += 1
                if state.frame % 8 == 0:
                    poll_secret_request(state)
                try:
                    event = await asyncio.wait_for(keys.get(), timeout=FRAME_INTERVAL_S)
                except TimeoutError:
                    continue  # no key this frame; the border still flickers
                if isinstance(event, PastedText):
                    if event.text:
                        state.input_buffer += _clean_paste(event.text)
                    else:
                        # Some terminals emit an empty bracketed paste when the
                        # clipboard owns an image rather than text.
                        paste_system_clipboard(
                            state, allow_images=state.secret_request is None
                        )
                    continue
                char = event
                if char == INTERRUPT:
                    return 0
                if char == CLIPBOARD_PASTE:
                    paste_system_clipboard(
                        state, allow_images=state.secret_request is None
                    )
                    continue
                if state.secret_request is not None:
                    # While a credential is being typed the buffer is a secret,
                    # not a message: it must not reach the transcript or a model.
                    if char in ENTER:
                        typed = state.input_buffer
                        state.input_buffer = ""
                        submit_secret(state, typed)
                    else:
                        apply_key(state, char)
                    continue
                submitted = apply_key(state, char)
                if submitted and not state.busy:
                    state.add("you", submitted)
                    task = asyncio.create_task(_handle(state, submitted, first_turn=first_turn))
                    pending.add(task)
                    task.add_done_callback(pending.discard)
        finally:
            loop.remove_reader(sys.stdin.fileno())
            for task in pending:
                task.cancel()


__all__ = [
    "CAPABILITY_BRIEF",
    "ConsoleState",
    "FRAME_INTERVAL_S",
    "Message",
    "PastedText",
    "TerminalInputDecoder",
    "apply_key",
    "capability_brief",
    "play_splash",
    "paste_system_clipboard",
    "project_goal",
    "raw_terminal",
    "render",
    "run_console",
]
