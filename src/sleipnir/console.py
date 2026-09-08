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
* **Lane** (assessed): an ordinary awake message first passes a tool-free
  capability check.  A confident check lets the fast alias act; anything else
  fails closed to the conversation alias with the request untouched.
  ``/project`` skips both lanes and launches the planner and routed
  multi-model orchestration pipeline instead.
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
import codecs
import contextlib
import math
import os
import re
import shlex
import shutil
import sys
import tempfile
import termios
import tty
import uuid
from collections import abc, deque
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from sleipnir import chat, theme
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
  {exe} ios doctor [--project <path>] inspect Linux-native iOS prerequisites
  {exe} ios build --project <path>      build a SwiftPM iOS app with xtool
  {exe} ios ipa --project <path>        produce a signed IPA with xtool
  {exe} ios run --project <path>        build, install and launch on a device
  {exe} secret prompt "<label>"        ask the operator; inject into focused app
  {exe} secret prompt "<label>" --browser-selector "<css>"
                                         fill a browser field without relying on focus

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
    #: Parsed worker routing config. Mutations are written to a private,
    #: session-scoped normalized TOML consumed by project child processes.
    routing_config: object | None = None
    runtime_config_dir: Path | None = None
    cache_read_weight: float = 1.0
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
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
    #: Directories containing clipboard images explicitly attached by the
    #: operator. Added to Claude's allowed roots; never available to workers.
    attachment_dirs: set[Path] = field(default_factory=set)
    #: Alias for ordinary requests after a separate tool-free capability check.
    #: A false negative costs a stronger turn; a false positive can act
    #: incorrectly on the live desktop, so uncertainty falls back to ``model``.
    fast_model: str | None = "haiku"
    #: Set while a credential is being typed: the buffer is not echoed and is
    #: never added to the transcript.
    secret_request: object | None = None
    #: Reasoning effort for the claude backend; None leaves it to the provider.
    effort: str | None = None
    #: Highlighted row of the / menu. The menu itself is derived from the input
    #: buffer, so this is the only piece of it worth keeping.
    menu_index: int = 0

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

    def push_routing(self) -> None:
        """Send the current model and effort to any transport already built.

        Transports are cached per provider and outlive a ``/model`` or
        ``/effort``, so without this the footer would report a routing choice
        the next spawn never receives — a setting that reads as applied and is
        not is worse than one that was refused.
        """
        for provider, session in self.sessions.items():
            transport = getattr(session, "_transport", None)
            if transport is None:
                continue
            transport.model = self.models.get(provider)
            if hasattr(transport, "effort"):
                transport.effort = self.effort

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
                effort=self.effort,
                add_dirs=(self.run_dir,) if self.run_dir else (),
            )
        return session._transport  # type: ignore[no-any-return]

    async def aclose(self) -> None:
        for session in self.sessions.values():
            transport = getattr(session, "_transport", None)
            if transport is not None:
                await transport.close()
        if self.runtime_config_dir is not None:
            shutil.rmtree(self.runtime_config_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Local commands — intercepted before anything is dispatched to a provider
# ---------------------------------------------------------------------------

#: Effort levels the Claude CLI documents. Operator data in the same sense as a
#: model alias: this list mirrors ``claude --help``, and an unlisted value is
#: refused rather than passed through — a silently ignored effort flag reads to
#: the operator as applied, which is the expensive kind of wrong.
EFFORT_LEVELS: tuple[str, ...] = ("low", "medium", "high", "xhigh", "max")

#: The permission mode ``/ask on`` selects. Anything other than
#: ``bypassPermissions`` makes the provider confirm each tool use.
ASK_FIRST_MODE = "acceptEdits"


@dataclass(frozen=True)
class SlashCommand:
    """One local command. ``/help`` and the menu both render from these.

    Registry-driven on purpose: a command that existed only in ``apply_slash``
    would be invisible to the menu, and one documented only in ``/help`` would
    drift out of date the first time its arguments changed.
    """

    name: str
    usage: str
    summary: str
    handler: abc.Callable[["ConsoleState", str], None]


def _cmd_use(state: "ConsoleState", argument: str) -> None:
    if argument not in chat.PROVIDERS:
        state.add("sleipnir", f"Unknown provider {_clip(argument)!r}. Try: {', '.join(chat.PROVIDERS)}.")
        return
    if argument != state.provider:
        state.provider = argument
        state.add("sleipnir", f"Now talking to {argument}. Conversations stay separate.")
    else:
        state.add("sleipnir", f"Already talking to {argument}.")


def _cmd_model(state: "ConsoleState", argument: str) -> None:
    if not argument:
        state.add("sleipnir", f"Usage: /model <alias|default>. Now: {state.model or 'account default'}.")
        return
    state.model = None if argument in ("default", "@default") else argument
    state.push_routing()
    state.add("sleipnir", f"{state.provider} will use {state.model or 'account default'}.")


def _cmd_effort(state: "ConsoleState", argument: str) -> None:
    if argument in ("default", "@default", "off"):
        state.effort = None
        state.push_routing()
        state.add("sleipnir", "Effort left to the provider.")
        return
    if argument not in EFFORT_LEVELS:
        state.add(
            "sleipnir",
            f"Unknown effort {_clip(argument)!r}. Choose from: {', '.join(EFFORT_LEVELS)}.",
        )
        return
    state.effort = argument
    state.push_routing()
    state.add("sleipnir", f"Effort set to {argument}. Applies to claude; codex ignores it.")


def _cmd_ask(state: "ConsoleState", argument: str) -> None:
    if argument not in ("on", "off"):
        state.add("sleipnir", "Usage: /ask on|off.")
        return
    state.permission_mode = ASK_FIRST_MODE if argument == "on" else "bypassPermissions"
    state.add(
        "sleipnir",
        "Confirming each tool use." if argument == "on" else "Full host control restored.",
    )


def _persist_routing_config(state: "ConsoleState") -> None:
    config = state.routing_config
    if config is None:
        raise ValueError("no worker config is loaded")
    if state.runtime_config_dir is None:
        state.runtime_config_dir = Path(tempfile.mkdtemp(prefix="sleipnir-console-"))
        state.runtime_config_dir.chmod(0o700)
    target = state.runtime_config_dir / "sleipnir.toml"
    temporary = state.runtime_config_dir / f".{target.name}.{uuid.uuid4().hex}.tmp"
    with temporary.open("x", encoding="utf-8") as handle:
        handle.write(config.to_toml())
        handle.flush()
        os.fsync(handle.fileno())
    temporary.chmod(0o600)
    os.replace(temporary, target)
    state.config_path = target


def _cmd_config(state: "ConsoleState", argument: str) -> None:
    from sleipnir.config import ConfigError, SleipnirConfig

    if not argument:
        if state.routing_config is None:
            state.add("sleipnir", "No worker config loaded. Usage: /config <path>.")
            return
        backends = ", ".join(state.routing_config.backends)
        state.add("sleipnir", f"Config: {state.config_path or 'in memory'}; backends: {backends}.")
        return
    try:
        paths = shlex.split(argument)
    except ValueError as exc:
        state.add("sleipnir", f"Config command refused: {exc}.")
        return
    if len(paths) != 1:
        state.add("sleipnir", "Usage: /config <path>.")
        return
    path = Path(paths[0]).expanduser().resolve()
    try:
        state.routing_config = SleipnirConfig.load(path)
    except ConfigError as exc:
        state.add("sleipnir", f"Config refused: {_clip(str(exc))}")
        return
    state.config_path = path
    state.add("sleipnir", f"Worker config loaded from {path}.")


def _cmd_router(state: "ConsoleState", argument: str) -> None:
    from sleipnir.schema import Tier

    config = state.routing_config
    if config is None:
        state.add("sleipnir", "No worker config loaded. Use /config <path> first.")
        return
    try:
        parts = shlex.split(argument)
    except ValueError as exc:
        state.add("sleipnir", f"Router command refused: {exc}.")
        return
    if not parts:
        rows = [f"{tier.value}: {', '.join(config.policy(tier).prefer)}" for tier in Tier]
        state.add("sleipnir", "Worker routes — " + "; ".join(rows))
        return
    try:
        tier = Tier(parts[0])
    except ValueError:
        state.add("sleipnir", f"Unknown tier {_clip(parts[0])!r}. Try: {', '.join(t.value for t in Tier)}.")
        return
    if len(parts) == 1:
        policy = config.policy(tier)
        state.add("sleipnir", f"{tier.value}: {', '.join(policy.prefer)}.")
        return
    if len(parts) not in (2, 3):
        state.add("sleipnir", "Usage: /router <tier> [backend] [model].")
        return
    model_id = parts[-1]
    if len(parts) == 3:
        named = config.backends.get(parts[1])
        matches = [named] if named is not None and any(
            model.id == model_id for model in named.models
        ) else []
    else:
        matches = [
            backend for backend in config.backends.values()
            if any(model.id == model_id for model in backend.models)
        ]
    if len(matches) != 1:
        reason = "not configured" if not matches else "configured by more than one backend"
        state.add("sleipnir", f"Model {_clip(model_id)!r} is {reason}.")
        return
    backend = matches[0]
    selected = next(model for model in backend.models if model.id == model_id)
    config.backends[backend.name] = replace(
        backend, models=(selected, *(model for model in backend.models if model.id != model_id))
    )
    policy = config.policy(tier)
    config.tiers[tier] = replace(
        policy, prefer=(backend.name, *(name for name in policy.prefer if name != backend.name))
    )
    _persist_routing_config(state)
    state.add(
        "sleipnir",
        f"{tier.value} will try {model_id} via {backend.name} first; tier constraints still apply.",
    )


def _cmd_provider(state: "ConsoleState", argument: str) -> None:
    from sleipnir.config import Backend, ModelOption
    from sleipnir.schema import Adapter, BillingMode

    config = state.routing_config
    if config is None:
        state.add("sleipnir", "No worker config loaded. Use /config <path> first.")
        return
    try:
        parts = shlex.split(argument)
    except ValueError as exc:
        state.add("sleipnir", f"Provider command refused: {exc}.")
        return
    if parts == ["list"] or not parts:
        rows = []
        for backend in config.backends.values():
            secret = backend.api_key_env or "CLI auth"
            rows.append(f"{backend.name} ({backend.adapter.value}, {secret})")
        state.add("sleipnir", "Providers: " + ", ".join(rows))
        return
    if len(parts) not in (4, 6, 7, 8) or parts[0] != "add":
        state.add(
            "sleipnir",
            "Usage: /provider add <name> <adapter> <model> "
            "[base-url key-env [context [price-per-Mtok]]].",
        )
        return
    _, name, adapter_text, model_id, *http_fields = parts
    if name in config.backends:
        state.add("sleipnir", f"Provider {name!r} already exists.")
        return
    try:
        adapter = Adapter(adapter_text)
    except ValueError:
        state.add("sleipnir", f"Unknown adapter {adapter_text!r}.")
        return
    is_http = adapter in (Adapter.OPENROUTER, Adapter.OPENAI, Adapter.ANTHROPIC)
    if is_http and len(http_fields) < 2:
        state.add("sleipnir", "HTTP providers require a base URL and API-key environment variable name.")
        return
    if not is_http and http_fields:
        state.add("sleipnir", "CLI providers do not accept HTTP endpoint fields.")
        return
    base_url = http_fields[0] if is_http else None
    key_env = http_fields[1] if is_http else None
    if base_url is not None:
        parsed_url = urlsplit(base_url)
        if (
            parsed_url.scheme not in ("http", "https")
            or not parsed_url.netloc
            or parsed_url.username is not None
            or parsed_url.password is not None
        ):
            state.add(
                "sleipnir",
                "The base URL must be HTTP(S) and cannot contain embedded credentials.",
            )
            return
    if key_env is not None and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key_env) is None:
        state.add("sleipnir", "Pass an environment variable name, never a raw API key.")
        return
    try:
        context = int(http_fields[2]) if len(http_fields) >= 3 else None
        price = float(http_fields[3]) if len(http_fields) >= 4 else None
        if context is not None and context < 1:
            raise ValueError
        if price is not None and (not math.isfinite(price) or price < 0):
            raise ValueError
    except ValueError:
        state.add("sleipnir", "Context must be positive and price finite and non-negative.")
        return
    config.backends[name] = Backend(
        name=name,
        adapter=adapter,
        billing=BillingMode.METERED if is_http else BillingMode.SUBSCRIPTION,
        models=(ModelOption(id=model_id, context=context, price_per_mtok=price),),
        base_url=base_url,
        api_key_env=key_env,
    )
    _persist_routing_config(state)
    state.add(
        "sleipnir",
        f"Added session provider {name}; credential comes only from {key_env or 'official CLI auth'}. "
        f"Use /router <tier> {name} {model_id} to route work to it.",
    )


def _cmd_run_root(state: "ConsoleState", argument: str) -> None:
    from sleipnir.runlog import run_is_active

    if not argument:
        state.add("sleipnir", f"Run root: {state.run_dir or state.project_base or Path.cwd()}.")
        return
    if state.run_dir is not None and run_is_active(state.run_dir):
        state.add("sleipnir", "Run root cannot change while an executor is active.")
        return
    try:
        paths = shlex.split(argument)
    except ValueError as exc:
        state.add("sleipnir", f"Run-root command refused: {exc}.")
        return
    if len(paths) != 1:
        state.add("sleipnir", "Usage: /run-root <path>.")
        return
    root = Path(paths[0]).expanduser().resolve()
    state.project_base = root
    state.run_dir = root
    state.run_root_explicit = True
    state.add("sleipnir", f"Run root set to {root}.")


def _cmd_cache_read_weight(state: "ConsoleState", argument: str) -> None:
    try:
        value = float(argument)
    except ValueError:
        value = float("nan")
    if not math.isfinite(value) or value < 0:
        state.add("sleipnir", "Usage: /cache-read-weight <finite non-negative number>.")
        return
    state.cache_read_weight = value
    state.add("sleipnir", f"Cache-read weight set to {value:g}.")


def _cmd_help(state: "ConsoleState", argument: str) -> None:
    width = max(len(command.usage) for command in COMMANDS)
    body = "\n".join(f"{command.usage:<{width}}  {command.summary}" for command in COMMANDS)
    state.add("sleipnir", body + "\nEverything else goes to the provider.")


COMMANDS: tuple[SlashCommand, ...] = (
    SlashCommand("/model", "/model <alias|default>", "model for this provider", _cmd_model),
    SlashCommand("/effort", "/effort <level|default>", "reasoning effort (claude)", _cmd_effort),
    SlashCommand("/use", "/use claude|codex", "switch provider", _cmd_use),
    SlashCommand("/ask", "/ask on|off", "confirm each tool use", _cmd_ask),
    SlashCommand(
        "/router", "/router <tier> [backend] [model]",
        "worker route for this session", _cmd_router,
    ),
    SlashCommand("/provider", "/provider add|list ...", "session worker API providers", _cmd_provider),
    SlashCommand("/config", "/config [path]", "show or load worker config", _cmd_config),
    SlashCommand("/run-root", "/run-root [path]", "show or set project run root", _cmd_run_root),
    SlashCommand(
        "/cache-read-weight", "/cache-read-weight <number>",
        "budget weight for cached input", _cmd_cache_read_weight,
    ),
    SlashCommand("/help", "/help", "list these commands", _cmd_help),
)


def menu_rows(state: "ConsoleState") -> tuple[SlashCommand, ...]:
    """Commands matching what has been typed so far — derived, never stored.

    Open only while the operator is still naming a command: a space means they
    have moved on to arguments and the menu would be in the way.
    """
    buffer = state.input_buffer
    if not buffer.startswith("/") or " " in buffer:
        return ()
    return tuple(command for command in COMMANDS if command.name.startswith(buffer))


def menu_selection(state: "ConsoleState") -> SlashCommand | None:
    rows = menu_rows(state)
    if not rows:
        return None
    return rows[state.menu_index % len(rows)]


def apply_slash(state: "ConsoleState", line: str) -> bool:
    """Handle a local command. True means consumed — send nothing anywhere."""
    if not line.startswith("/"):
        return False
    name, _, argument = line.strip().partition(" ")
    for command in COMMANDS:
        if command.name == name:
            command.handler(state, argument.strip())
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
        prompt_line = f"🔒 {label}: {'•' * len(state.input_buffer)}{caret}"
    else:
        suffix = f" (+{len(state.pending_submissions)} queued)" if state.pending_submissions else ""
        prompt_line = f"› {_clip(state.input_buffer)}{caret}{suffix}"
    # The menu sits above the prompt so the row being chosen is next to the
    # text that filters it. Usage and summary are static registry strings, but
    # they go through _clip like every other value that reaches the screen.
    rows = menu_rows(state)
    if rows:
        chosen = menu_selection(state)
        usage_width = max(len(row.usage) for row in rows)
        for row in rows:
            marker = "❯" if row is chosen else " "
            entry = f" {marker} {_clip(row.usage):<{usage_width}}  {_clip(row.summary)}"
            level = theme.BRIGHT if row is chosen else theme.DIM + 1
            lines.append(theme.paint(entry[:inner], level, colour=colour))
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
#: Menu navigation. Tab and ctrl-n/ctrl-p are single bytes; arrow keys arrive
#: as multi-byte escape sequences, which the reader would have to buffer.
MENU_NEXT = ("\t", "\x0e")
MENU_PREVIOUS = "\x10"

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
    rows = menu_rows(state)
    if rows and char in MENU_NEXT:
        state.menu_index = (state.menu_index + 1) % len(rows)
        return None
    if rows and char == MENU_PREVIOUS:
        state.menu_index = (state.menu_index - 1) % len(rows)
        return None
    if char in ENTER:
        # With the menu open, Enter completes the highlighted command rather
        # than submitting a half-typed one. An exact name is already complete,
        # so it submits — otherwise /help could never be sent.
        chosen = menu_selection(state)
        if chosen is not None and chosen.name != state.input_buffer:
            state.input_buffer = f"{chosen.name} "
            state.menu_index = 0
            return None
        line = state.input_buffer.strip()
        state.input_buffer = ""
        state.menu_index = 0
        return line or None
    if char in BACKSPACE:
        state.input_buffer = state.input_buffer[:-1]
        return None
    if char == "\x15":  # ctrl-u, clear line
        state.input_buffer = ""
        return None
    if char.isprintable():
        state.input_buffer += char
        # The filtered list changed under the highlight; keeping the old index
        # would select whatever happened to land in that row.
        state.menu_index = 0
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


def _claude_dirs(state: ConsoleState) -> tuple[Path, ...]:
    directories = set(state.attachment_dirs)
    if state.run_dir is not None:
        directories.add(state.run_dir)
    return tuple(sorted(directories))


async def _lane_model(state: ConsoleState, prompt: str) -> str | None:
    """Pick the alias for this turn; the fast one only on a confident check.

    The classification runs one-shot in a throwaway session with physically no
    tools, so a check that fails cannot have acted and the untouched request is
    simply routed to the strong alias. It deliberately does not reuse the
    durable session: gate instructions there would poison the turn that follows.
    """
    if not state.fast_model or state.provider != "claude":
        return state.model
    state.status = "checking · fast lane"
    try:
        assessment = await chat.ask_claude(
            prompt,
            str(uuid.uuid4()),
            resume=False,
            permission_mode=state.permission_mode,
            model=state.fast_model,
            tools=(),
            system_prompt=chat.FAST_LANE_ASSESSMENT,
        )
    except chat.ChatError:
        state.status = "escalating · strong lane"
        state.add(
            "sleipnir",
            "The tool-free capability check was unavailable; routing the untouched "
            f"request to {state.model or 'the strong model'}.",
        )
        return state.model
    if chat.fast_lane_capable(assessment):
        state.status = "acting · fast lane"
        state.add("sleipnir", f"Fast lane approved; {state.fast_model} is acting.")
        return state.fast_model
    state.status = "escalating · strong lane"
    state.add(
        "sleipnir",
        "Fast lane declined or failed closed; routing the untouched request to "
        f"{state.model or 'the strong model'}.",
    )
    return state.model


async def _handle(state: ConsoleState, text: str) -> None:
    """Send one operator message to whoever is on duty, streaming the reply."""
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
        # A pasted image lands in a fresh private directory, and a persistent
        # process cannot gain an allowed root after launch. Relaunching is safe:
        # the transport resumes the same session, so no context is lost.
        dirs = _claude_dirs(state)
        if state.provider == "claude" and getattr(transport, "add_dirs", ()) != dirs:
            await transport.close()
            transport.add_dirs = dirs
        # The gate is a separate one-shot turn; only its verdict reaches here.
        lane = await _lane_model(state, prompt + queued)
        restore_model = getattr(transport, "model", None)
        transport.model = lane
        streaming = state.add(state.provider, "")
        final_text: str | None = None
        try:
            async for event in transport.turn(prompt + queued):
                if event.kind == "delta":
                    streaming.text += event.text
                elif event.kind == "final":
                    final_text = event.text
                    session.opened = True
        finally:
            # Lane selection is per turn. A failed fast action may have touched
            # the host and is never replayed, but it must not silently promote
            # the fast alias to the session's configured model either.
            transport.model = restore_model
        # The final event's text is authoritative; deltas are only the preview.
        streaming.text = final_text if final_text is not None else streaming.text
        if not streaming.text.strip():
            state.add("error", f"{state.provider} returned an empty reply")
    except Exception as error:  # noqa: BLE001 - the console must never die on a reply
        state.add("error", f"{type(error).__name__}: {error}")
    finally:
        state.busy = False
        state.status = "ready"


async def submit_secret(state: ConsoleState, typed: str) -> str:
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
        if request.browser_selector:
            from sleipnir.capabilities.browser import Browser

            async with Browser() as web:
                await web.fill_secret(request.browser_selector, secret)
                if request.submit:
                    await web.press(request.browser_selector, "Enter")
        else:
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
        keys: asyncio.Queue[str | PastedText] = asyncio.Queue()
        decoder = TerminalInputDecoder()

        def _on_readable() -> None:
            data = os.read(sys.stdin.fileno(), 8192)
            for event in decoder.feed(data):
                keys.put_nowait(event)

        if interactive:
            loop.add_reader(sys.stdin.fileno(), _on_readable)
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
            "mouse, screen, browser and shell. Ordinary requests use the guarded "
            "fast lane; /project <goal> starts the multi-model workflow. /use codex "
            "switches provider; /help lists commands."
            if state.permission_mode == "bypassPermissions"
            else "Ready. Host actions will be confirmed with you before they run. "
            "/project <goal> starts the multi-model workflow; /help lists commands."
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
                    event = await asyncio.wait_for(keys.get(), timeout=FRAME_INTERVAL_S)
                except TimeoutError:
                    drain_pending(state, dispatch)
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
                        await submit_secret(state, typed)
                    else:
                        apply_key(state, char)
                    continue
                submitted = apply_key(state, char)
                if submitted:
                    handle_submitted(state, submitted, dispatch)
        finally:
            if interactive:
                loop.remove_reader(sys.stdin.fileno())
            for task in pending_tasks:
                task.cancel()
            with contextlib.suppress(Exception):
                await asyncio.shield(asyncio.wait_for(state.aclose(), timeout=3.0))


__all__ = [
    "CAPABILITY_BRIEF",
    "ConsoleState",
    "FRAME_INTERVAL_S",
    "Message",
    "PastedText",
    "TerminalInputDecoder",
    "apply_key",
    "apply_slash",
    "capability_brief",
    "drain_pending",
    "handle_submitted",
    "play_splash",
    "paste_system_clipboard",
    "project_goal",
    "raw_terminal",
    "refresh_brain_state",
    "render",
    "run_console",
    "run_digest",
]
