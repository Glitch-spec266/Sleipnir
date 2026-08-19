"""The Sleipnir console: the window you actually talk to.

What this is, structurally: a full-screen renderer that owns the terminal, plus
a message router.  It is *not* a second Claude.  A message you type is handed
to the real ``claude`` CLI — Sleipnir's job is to decide **who** receives it and
to widen what the receiver can do, not to answer for it.

Routing is the interesting part.  The brain is expensive and context-bound, so
it is not always listening:

* **Brain awake** (no run in flight, or the run has hit a gate): the message
  goes straight to ``claude`` with session continuity, so a conversation is a
  conversation.
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
import contextlib
import os
import shutil
import sys
import termios
import tty
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sleipnir import theme

FRAME_INTERVAL_S = 1 / 12  # fast enough for flicker, cheap enough to ignore

# The console is the only place Sleipnir tells the model what host powers it
# has. Workers never see this text — they keep the confined sandbox.
CAPABILITY_BRIEF = """\
You are running inside Sleipnir, a harness that extends you with host control.
These are real shell commands available to you via Bash:

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
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    frame: int = 0
    #: Host control is the product, so the console does not stop to ask before
    #: every click and keystroke.  Narrowing this to ``acceptEdits`` turns
    #: Sleipnir back into an ordinary headless Claude with no reach outside the
    #: repository — correct for a cautious session, useless for the desk robot.
    permission_mode: str = "bypassPermissions"

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

    art = theme.logo_lines(width)
    if height > 22:
        for line in art[:1]:
            lines.append(theme.paint(line, theme.NORMAL + 1, colour=colour))
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
        sys.stdout.write(theme.HIDE_CURSOR)
        sys.stdout.flush()
        yield True
    finally:
        termios.tcsetattr(stream, termios.TCSADRAIN, saved)
        sys.stdout.write(theme.SHOW_CURSOR + theme.RESET + "\n")
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


async def _handle(state: ConsoleState, text: str, *, first_turn: list[bool]) -> None:
    """Send one operator message to whoever is on duty."""
    from sleipnir import chat

    state.busy = True
    state.status = "thinking" if state.brain_awake else "routing"
    try:
        if state.brain_awake:
            prompt = f"{capability_brief()}\n\n{text}" if first_turn[0] else text
            reply = await chat.ask_claude(
                prompt,
                state.session_id,
                resume=not first_turn[0],
                permission_mode=state.permission_mode,
                add_dirs=(state.run_dir,) if state.run_dir else (),
            )
            first_turn[0] = False
            state.add("claude", reply.text)
        else:
            state.add(
                "sleipnir",
                "The orchestrator is asleep mid-build. Answering from the run "
                "manifest instead of waking it.",
            )
    except Exception as error:  # noqa: BLE001 - the console must never die on a reply
        state.add("error", f"{type(error).__name__}: {error}")
    finally:
        state.busy = False
        state.status = "ready"


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
        keys: asyncio.Queue[str] = asyncio.Queue()

        def _on_readable() -> None:
            data = os.read(sys.stdin.fileno(), 1024).decode("utf-8", "ignore")
            for char in data:
                keys.put_nowait(char)

        loop.add_reader(sys.stdin.fileno(), _on_readable)
        state.add(
            "sleipnir",
            "Ready. Your message goes to Claude Code with host control attached — "
            "keyboard, mouse, screen, browser and shell. Run with --ask-first to "
            "confirm each action instead."
            if state.permission_mode == "bypassPermissions"
            else "Ready. Host actions will be confirmed with you before they run.",
        )
        try:
            while True:
                width, height = shutil.get_terminal_size((90, 26))
                _paint(render(state, width=width, height=height, colour=colour))
                state.frame += 1
                try:
                    char = await asyncio.wait_for(keys.get(), timeout=FRAME_INTERVAL_S)
                except TimeoutError:
                    continue  # no key this frame; the border still flickers
                if char == INTERRUPT:
                    return 0
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
    "apply_key",
    "capability_brief",
    "play_splash",
    "raw_terminal",
    "render",
    "run_console",
]
