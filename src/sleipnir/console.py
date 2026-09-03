"""The Sleipnir console: the window you actually talk to.

What this is, structurally: a full-screen renderer that owns the terminal, plus
a message router.  It is *not* a model.  A message you type is handed to a real
provider CLI — Claude Code or Codex, switchable with ``/use`` mid-conversation
— and Sleipnir's job is to decide **who** receives it and to widen what the
receiver can do, never to answer for it.

Routing has two axes:

* **Provider** (your choice): an awake conversation goes to the selected
  provider with per-provider session continuity.  Switching providers keeps
  each conversation separate, so ``claude → codex → claude`` resumes two
  independent threads.
* **Wakefulness** (derived): while a run owns the lock there is no conversation
  to have — waking the reason tier for "how's it going?" would burn the exact
  context the whole design protects.  A cheap OpenRouter duty officer answers
  from the bounded manifest instead, or files the message for the brain.

Replies stream.  Tokens render into a growing message at the frame rate, so
the wait ends when the model's first token lands rather than when its last one
does.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import shutil
import sys
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sleipnir import chat, platform, theme

FRAME_INTERVAL_S = 1 / 12  # fast enough for flicker, cheap enough to ignore

# The console is the only place Sleipnir tells the model what host powers it
# has. Workers never see this text — they keep the confined sandbox.
CAPABILITY_BRIEF = """\
You are running inside Sleipnir, a harness that extends you with host control.
These are real shell commands available to you via {shell}:

  {exe} computer screenshot <path>     capture the screen to a PNG you can read
  {exe} computer type <text>           type into the focused window
  {exe} computer key <combo>           press a chord, e.g. ctrl+shift+t
  {exe} computer click [left|right]    click at the pointer
  {exe} computer move <x> <y>          move the pointer
  {exe} computer scroll <amount>       scroll the focused window
  {exe} browser open <url>             drive a real logged-in Chromium
  {exe} browser text [selector]        read the current page
  {exe} browser click <selector>
  {exe} browser fill <selector> <text>
  {exe} secret prompt "<label>"        ask the operator for a credential

{injection}Take a screenshot and look at it before clicking blind.

The last command matters most: you never see credentials. `secret prompt` opens
a field inside Sleipnir, the operator types the value, and it is injected
straight into the focused window. It is never stored, logged, or shown to you.
When a flow needs a login, call it rather than asking the operator to paste
anything into this conversation.
"""


#: What the injection actually is, per platform. This is prompt content the
#: model plans around, so it has to be true: told "kernel level, reaches every
#: window" on Windows, a model retries a click that UIPI will never deliver
#: instead of reporting that it cannot reach an elevated window.
_INJECTION_LINUX = """\
Input is injected at the kernel level, so it reaches every window on this
Wayland desktop exactly as a physical keyboard would.
"""

_INJECTION_WINDOWS = """\
Input is injected through the OS's own SendInput API, so it reaches ordinary
windows on this Windows desktop as a physical keyboard would. It cannot reach
a window belonging to an elevated process, and never reaches the UAC secure
desktop — if input there appears to do nothing, say so rather than retrying.
"""


def capability_brief() -> str:
    """The brief, with this install's real executable path substituted in.

    Hard-coding ``sleipnir`` would be a coin flip: the model's Bash may not
    have the virtualenv on ``PATH``, and a capability that silently resolves to
    "command not found" looks to the model like the feature does not exist.
    """
    executable = shutil.which("sleipnir") or f"{sys.executable} -m sleipnir.cli"
    return CAPABILITY_BRIEF.format(
        exe=executable,
        shell="your shell (PowerShell or cmd)" if platform.IS_WINDOWS else "Bash",
        injection=_INJECTION_WINDOWS if platform.IS_WINDOWS else _INJECTION_LINUX,
    )


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
    frame: int = 0
    #: Host control is the product, so the console does not stop to ask before
    #: every click and keystroke.  Narrowing this to ``acceptEdits`` turns
    #: Sleipnir back into an ordinary headless agent with no reach outside the
    #: repository — correct for a cautious session, useless for the desk robot.
    permission_mode: str = "bypassPermissions"
    #: Instructions the duty officer took while the brain slept. Text only —
    #: handed to the brain on its next turn, never executed here.
    queued_for_brain: list[str] = field(default_factory=list)
    #: Model alias per provider. Operator data; ``None`` lets the account pick.
    models: dict[str, str | None] = field(
        default_factory=lambda: {provider: None for provider in chat.PROVIDERS}
    )
    #: The provider the next awake message goes to. Switched with /use;
    #: conversations stay separate per provider.
    provider: str = "claude"
    sessions: dict[str, chat.ChatSession] = field(default_factory=dict)
    #: Lines typed while a reply was streaming. Nothing typed here is ever
    #: dropped: each one dispatches the moment the turn in flight finishes.
    pending_submissions: deque[str] = field(default_factory=deque)
    #: Set while a credential is being typed: the buffer is not echoed and is
    #: never added to the transcript.
    secret_request: object | None = None

    def add(self, role: str, text: str) -> Message:
        message = Message(role=role, text=text)
        self.messages.append(message)
        return message

    # -- per-provider session plumbing --------------------------------------

    @property
    def model(self) -> str | None:
        return self.models.get(self.provider)

    @model.setter
    def model(self, value: str | None) -> None:
        self.models[self.provider] = value

    def session_for(self, provider: str) -> chat.ChatSession:
        if provider not in self.sessions:
            self.sessions[provider] = chat.ChatSession(provider=provider)
        return self.sessions[provider]

    def transport_for(self, provider: str) -> chat.ClaudeTransport | chat.CodexTransport:
        session = self.session_for(provider)
        if getattr(session, "_transport", None) is None:
            session._transport = chat.transport_for(  # noqa: SLF001 - owned here
                session,
                permission_mode=self.permission_mode,
                model=self.models.get(provider),
                add_dirs=(self.run_dir,) if self.run_dir else (),
            )
        return session._transport  # type: ignore[no-any-return]

    async def aclose(self) -> None:
        for session in self.sessions.values():
            transport = getattr(session, "_transport", None)
            if transport is not None:
                await transport.close()


# ---------------------------------------------------------------------------
# Local commands — intercepted before anything is dispatched to a provider
# ---------------------------------------------------------------------------

_SLASH_USE = re.compile(r"^/use\s+(claude|codex)\s*$")
_SLASH_MODEL = re.compile(r"^/model\s+(\S+)\s*$")


def apply_slash(state: ConsoleState, line: str) -> bool:
    """Handle a local command. True means consumed — send nothing anywhere."""
    if not line.startswith("/"):
        return False
    use = _SLASH_USE.match(line)
    if use:
        target = use.group(1)
        if target != state.provider:
            state.provider = target
            state.add("sleipnir", f"Now talking to {target}. Conversations stay separate.")
        else:
            state.add("sleipnir", f"Already talking to {target}.")
        return True
    picked = _SLASH_MODEL.match(line)
    if picked:
        alias = picked.group(1)
        state.model = None if alias in ("default", "@default") else alias
        shown = state.model or "account default"
        state.add("sleipnir", f"{state.provider} will use {shown}.")
        return True
    if re.match(r"^/help\s*$", line):
        state.add(
            "sleipnir",
            "/use claude|codex — switch provider · /model <alias|default> — "
            "pick this provider's model · everything else goes to the provider.",
        )
        return True
    state.add("sleipnir", "Unknown command. Try /help.")
    return True


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_ROLE_LEVEL = {
    "you": theme.BRIGHT,
    "sleipnir": theme.NORMAL,
    "claude": theme.NORMAL + 1,
    "codex": theme.NORMAL + 1,
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

    # The banner is all-or-nothing. Drawing the top row of a five-row wordmark
    # renders as broken debris, which is what shipped: `art[:1]` looked like a
    # tidy truncation and is not one.
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
        prompt_line = f"🔒 {label}: {'•' * len(state.input_buffer)}{caret}"
    else:
        suffix = f" (+{len(state.pending_submissions)} queued)" if state.pending_submissions else ""
        prompt_line = f"› {_clip(state.input_buffer)}{caret}{suffix}"
    lines.append(theme.paint(prompt_line[-inner:], theme.BRIGHT, colour=colour))

    where = "brain awake" if state.brain_awake else "brain asleep · routed"
    # Full host control is the point of this tool, and it is also the most
    # consequential fact about the session — so it is stated on screen for as
    # long as it is true, rather than behind a prompt that gets clicked through
    # once and forgotten.
    reach = "FULL HOST CONTROL" if state.permission_mode == "bypassPermissions" else "ask-first"
    model = state.model or "default"
    footer = f"{state.provider}:{model} · {where} · {reach} · {state.status} · ctrl-c to exit"
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
    machine. The raw-mode mechanics themselves are platform's job
    (termios/tty on POSIX, console mode bits on Windows) -- this function
    only owns the part both platforms share: painting and clearing the
    alt-screen around whatever `platform.raw_console()` does.
    """
    with platform.raw_console() as interactive:
        if not interactive:
            yield False
            return
        sys.stdout.write(theme.ENTER_FULLSCREEN + theme.HIDE_CURSOR)
        sys.stdout.flush()
        try:
            yield True
        finally:
            sys.stdout.write(theme.SHOW_CURSOR + theme.RESET + theme.EXIT_FULLSCREEN)
            sys.stdout.flush()


def _paint(text: str) -> None:
    sys.stdout.write(theme.CLEAR + text)
    sys.stdout.flush()


async def play_splash(*, colour: bool = True, skip_requested=None) -> None:
    """Boot animation, interruptible by any keypress.

    A splash you must sit through on every launch is a tax on the ten launches
    a day where you just want to type. ``skip_requested`` is a zero-arg probe
    checked between frames.
    """
    width, height = shutil.get_terminal_size((90, 26))
    for index in range(theme.SPLASH_FRAMES):
        if skip_requested is not None and skip_requested():
            return
        _paint(theme.splash_frame(index, width=width, height=height, colour=colour))
        await asyncio.sleep(0.035)


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------

BACKSPACE = ("\x7f", "\x08")
INTERRUPT = "\x03"
ENTER = ("\r", "\n")


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
    if len(char) > 1:
        # A named token from platform.key_reader for an arrow/home/end/...
        # key (e.g. "<up>"), not literal text. The buffer has no
        # cursor-motion or history support yet, so the correct behaviour is
        # to drop it -- not type its characters into the prompt, which is
        # what an unhandled arrow key used to do (an ESC "[" "A" sequence
        # decoded one char at a time inserted a literal "[A").
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


async def _ask_duty_officer(state: ConsoleState, text: str) -> None:
    """Answer from bounded run state without spending a reason-tier spawn."""
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
        # changes still go only through the revision applier and its
        # operator-review gate.
        state.queued_for_brain.append(queued)
        state.add("sleipnir", f"Queued for the orchestrator: {queued}")


async def _handle(state: ConsoleState, text: str) -> None:
    """Send one operator message to whoever is on duty, streaming the reply."""
    refresh_brain_state(state)
    state.busy = True
    state.status = "thinking" if state.brain_awake else "routing"
    try:
        if not state.brain_awake:
            await _ask_duty_officer(state, text)
            return
        session = state.session_for(state.provider)
        transport = state.transport_for(state.provider)
        first_turn = not session.opened
        queued = ""
        if state.queued_for_brain:
            queued = (
                "\n\nQueued while you were asleep:\n"
                + "\n".join(f"- {item}" for item in state.queued_for_brain)
            )
            state.queued_for_brain.clear()
        prompt = f"{capability_brief()}\n\n{text}" if first_turn else text
        streaming = state.add(state.provider, "")
        final_text: str | None = None
        async for event in transport.turn(prompt + queued):
            if event.kind == "delta":
                streaming.text += event.text
            elif event.kind == "final":
                final_text = event.text
                session.opened = True
        # The final event's text is authoritative; deltas are only the preview.
        streaming.text = final_text if final_text is not None else streaming.text
        if not streaming.text.strip():
            state.add("error", f"{state.provider} returned an empty reply")
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
    """Notice a tool subprocess asking for a credential.

    Deliberately runs while the console is busy: the subprocess that asks was
    spawned by the provider CLI mid-turn, so busy is the only state in which a
    request can exist. Gating on it hid the prompt entirely.
    """
    from sleipnir.capabilities import handoff

    if state.secret_request is not None:
        return
    request = handoff.pending()
    if request is not None:
        state.secret_request = request
        state.add(
            "sleipnir",
            f"A credential is needed: {request.label}. Type it below — it is masked, "
            "never stored, and never shown to the model that asked.",
        )


def handle_submitted(state: ConsoleState, text: str, dispatch) -> None:
    """Route one submitted line: local command, queue behind a live reply,
    or dispatch now. Split out of the I/O loop so the policy is testable."""
    if apply_slash(state, text):
        return
    if state.busy:
        # Queued, never dropped: the previous behaviour silently discarded
        # what you typed while a reply was streaming.
        state.pending_submissions.append(text)
        return
    dispatch(text)


def drain_pending(state: ConsoleState, dispatch) -> None:
    if not state.busy and state.pending_submissions:
        dispatch(state.pending_submissions.popleft())


async def run_console(state: ConsoleState | None = None, *, splash: bool = True) -> int:
    """Own the terminal until the operator leaves."""
    state = state or ConsoleState()
    colour = theme.supports_colour()
    pending_tasks: set[asyncio.Task[None]] = set()

    with raw_terminal() as interactive:
        loop = asyncio.get_running_loop()
        keys: asyncio.Queue[str] = asyncio.Queue()

        # No reader thread/callback at all when stdin is not a tty: platform
        # itself only builds one under the same condition, but skipping it
        # here too keeps the "not interactive" early-return below identical
        # to what it was before this seam existed.
        reader = (
            platform.key_reader(loop, keys.put_nowait)
            if interactive
            else contextlib.nullcontext()
        )
        with reader:
            if splash:
                await play_splash(colour=colour, skip_requested=lambda: not keys.empty())
            if not interactive:
                return 0

            def dispatch(text: str) -> None:
                state.add("you", text)
                task = asyncio.create_task(_handle(state, text))
                pending_tasks.add(task)
                task.add_done_callback(pending_tasks.discard)

            welcome = (
                f"Ready. Talking to {state.provider} with host control attached — keyboard, "
                "mouse, screen, browser and shell. /use codex switches provider; /help "
                "lists commands."
                if state.permission_mode == "bypassPermissions"
                else "Ready. Host actions will be confirmed with you before they run. /help lists commands."
            )
            state.add("sleipnir", welcome)
            try:
                while True:
                    width, height = shutil.get_terminal_size((90, 26))
                    _paint(render(state, width=width, height=height, colour=colour))
                    state.frame += 1
                    if state.frame % 8 == 0:
                        poll_secret_request(state)
                    try:
                        char = await asyncio.wait_for(keys.get(), timeout=FRAME_INTERVAL_S)
                    except TimeoutError:
                        char = None  # no key this frame; the border still flickers
                    if char == INTERRUPT:
                        return 0
                    if char is not None:
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
                        if submitted:
                            handle_submitted(state, submitted, dispatch)
                    else:
                        drain_pending(state, dispatch)
            finally:
                for task in pending_tasks:
                    task.cancel()
                with contextlib.suppress(Exception):
                    await asyncio.shield(asyncio.wait_for(state.aclose(), timeout=3.0))


__all__ = [
    "CAPABILITY_BRIEF",
    "ConsoleState",
    "FRAME_INTERVAL_S",
    "Message",
    "apply_key",
    "apply_slash",
    "capability_brief",
    "drain_pending",
    "handle_submitted",
    "play_splash",
    "raw_terminal",
    "refresh_brain_state",
    "render",
    "run_console",
    "run_digest",
]
