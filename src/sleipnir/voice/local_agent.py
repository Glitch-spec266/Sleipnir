"""Bounded local multimodal operator agent backed by Ollama.

The model sees an ephemeral current desktop frame and may use a deliberately
small set of audited browser/desktop tools. Frames are read into memory and the
temporary capture is immediately removed. Consequential interaction follows
the desktop permission policy; the default ``ask`` posture observes and plans
but does not click or type.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

import httpx

from sleipnir.capabilities import audit
from sleipnir.capabilities import computer
from sleipnir.capabilities.browser import Browser
from sleipnir.console import capability_brief
from sleipnir.voice.routing import is_smalltalk, needs_reasoning, needs_screen
from sleipnir.voice.providers import VoiceProviderError
from sleipnir.voice.relay import WorkRelay

MAX_FRAME_BYTES = 12 * 1024 * 1024
MAX_TOOL_RESULT_CHARS = 16_000
MAX_AGENT_STEPS = 12

LOCAL_AGENT_SYSTEM = """\
You are JARVIS, Sleipnir's local multimodal operator agent. Be concise and
truthful. You receive the freshest desktop frame at the start of the turn and
after actions that can change the display. Use browser DOM tools when a web page
can be understood reliably from structure; use observe_screen for native apps,
visual layouts, pictures, or when the display may have changed. Never claim an
action succeeded until a tool result or a fresh frame verifies it.

Solve the operator's problem yourself. Reasoning, planning, explanations,
research, maths, writing, and documents are your work, not someone else's: think
it through and answer. Use write_file only when the operator asked for a
document or deliverable -- a self-contained HTML presentation, an essay, notes,
a plan -- and then say where you put it. A spoken question is answered by
speaking, not by writing a file. Only call delegate_work when the operator names Claude or Codex, or
when the task needs changes to a source repository.

The desktop frame is background context. Do not describe it, and do not call
observe_screen, unless the operator's request is about what is on the screen.

Always end your turn by speaking one short sentence to the operator confirming
what you did or found, even when the task needed no answer.

Do not request, reveal, or type credentials; credential entry stays behind
Sleipnir's protected operator prompt. Stop when the task is complete or when a
tool says operator approval is required."""


TOOLS: list[dict[str, Any]] = [
    {"type": "function", "function": {"name": "observe_screen", "description": "Attach the newest full-desktop frame so you can read text, images, and UI state.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "browser_open", "description": "Open a URL in Sleipnir's persistent visible browser.", "parameters": {"type": "object", "required": ["url"], "properties": {"url": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "browser_text", "description": "Read bounded visible text from the current browser page.", "parameters": {"type": "object", "properties": {"selector": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "browser_click", "description": "Click a CSS selector in the current browser page.", "parameters": {"type": "object", "required": ["selector"], "properties": {"selector": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "browser_click_text", "description": "Reliably click the first browser element with an exact visible label; prefer this when you know button or link text.", "parameters": {"type": "object", "required": ["text"], "properties": {"text": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "browser_fill", "description": "Fill a non-secret browser field.", "parameters": {"type": "object", "required": ["selector", "text"], "properties": {"selector": {"type": "string"}, "text": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "computer_click", "description": "Move to screen coordinates and click.", "parameters": {"type": "object", "required": ["x", "y"], "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}, "button": {"type": "string", "enum": ["left", "right"]}}}}},
    {"type": "function", "function": {"name": "computer_type", "description": "Type non-secret text into the focused window.", "parameters": {"type": "object", "required": ["text"], "properties": {"text": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "computer_key", "description": "Press a key chord such as ctrl+l or enter.", "parameters": {"type": "object", "required": ["combo"], "properties": {"combo": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "computer_scroll", "description": "Scroll the focused window; negative moves down.", "parameters": {"type": "object", "required": ["amount"], "properties": {"amount": {"type": "integer"}}}}},
    {"type": "function", "function": {"name": "write_file", "description": "Write a document you have composed (HTML presentation, essay, notes, plan) into the operator's Sleipnir output folder and return its path.", "parameters": {"type": "object", "required": ["path", "content"], "properties": {"path": {"type": "string", "description": "File name, e.g. photosynthesis-deck.html"}, "content": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "open_file", "description": "Show a file you wrote to the operator in Sleipnir's browser.", "parameters": {"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "delegate_work", "description": "Ask Claude or Codex to solve a difficult task using Sleipnir's full audited capabilities. Only when the operator names them, or for source repository changes.", "parameters": {"type": "object", "required": ["provider", "instruction"], "properties": {"provider": {"type": "string", "enum": ["claude", "codex"]}, "instruction": {"type": "string"}}}}},
]

ACTION_NUDGE = (
    "Do that now by calling the tool, without describing it first. "
    "Then confirm in one sentence."
)

# A small model's way of failing: it narrates the action instead of emitting the
# call.  Measured live on qwen3.5:4b, twice, with two different openings -- so
# the phrase is matched anywhere in the reply, not just at the start.
_PROMISE_PHRASES = (
    "i'll ", "i will ", "let me ", "i'm going to", "i am going to",
    "i can create", "i can write", "going to create", "here's what i'll",
)
# "let me know" is the one common phrase that reads as a promise but is really
# a hand-back to the operator.
_PROMISE_EXCEPTIONS = ("let me know",)


class LocalCapabilityExceeded(VoiceProviderError):
    """The local model cannot finish this task, so it must be delegated.

    Distinct from a provider fault: the call succeeded and the model simply was
    not good enough. Retrying it locally buys nothing.
    """


REASON_SYSTEM = (
    "You are JARVIS, the operator's assistant, speaking aloud. Work the problem "
    "carefully, then state only the final answer in one short sentence with its "
    "units. Do not read your working aloud."
)

# MEASURED: reasoning consumed the whole token budget on the physics question
# and left nothing for the answer, which reached the operator as silence.
REASON_TOKENS = 2048
# MEASURED: "17 times 24 plus 139" made both 4B and 9B deliberate for 121 s and
# 131 s and still answer nothing, while a retry at a larger ceiling only bought
# a longer wait. A model that loops does not need more budget -- it needs a
# different model. The deadline turns that into a prompt, bounded escalation.
REASON_DEADLINE_SECONDS = 25.0

CHAT_SYSTEM = (
    "You are JARVIS, the operator's assistant, speaking aloud. This is small "
    "talk, not a task. Reply in one short friendly sentence. Do not think out "
    "loud, do not explain yourself, and do not mention the screen."
)


_THINK_BLOCK = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.IGNORECASE | re.DOTALL)
_THINK_OPEN = re.compile(r"<think\b[^>]*>.*\Z", re.IGNORECASE | re.DOTALL)


def strip_thinking(text: str) -> str:
    """Remove a model's visible reasoning before anything is spoken.

    ``think: false`` is a request, not a guarantee: a qwen3-style model can
    still emit a literal ``<think>`` block inside the message content. An
    unterminated block is dropped to the end of the string -- the reasoning was
    cut off mid-thought, so there is no answer after it to keep.
    """
    without = _THINK_BLOCK.sub(" ", text)
    without = _THINK_OPEN.sub(" ", without)
    return " ".join(without.split())


def _promises_action(text: str) -> bool:
    body = text.casefold()
    for exception in _PROMISE_EXCEPTIONS:
        body = body.replace(exception, "")
    return any(phrase in body for phrase in _PROMISE_PHRASES)


MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
DEFAULT_OUTPUT_ROOT = Path.home() / "Sleipnir"


@dataclass(frozen=True, slots=True)
class LocalAgentReply:
    text: str
    model: str
    steps: int


class ScreenObserver:
    """Capture one audited frame without leaving screenshot files behind."""

    async def capture(self) -> bytes:
        with tempfile.TemporaryDirectory(prefix="sleipnir-observe-") as root:
            path = Path(root) / "desktop.png"
            await asyncio.to_thread(computer.screenshot, path)
            frame = path
            if converter := shutil.which("magick") or shutil.which("convert"):
                reduced = Path(root) / "desktop.jpg"
                process = await asyncio.create_subprocess_exec(
                    converter,
                    str(path),
                    "-resize",
                    "1280x1280>",
                    "-strip",
                    "-quality",
                    "72",
                    str(reduced),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                if await process.wait() == 0 and reduced.is_file():
                    frame = reduced
            data = frame.read_bytes()
        if not data or len(data) > MAX_FRAME_BYTES:
            raise VoiceProviderError("desktop frame is empty or exceeds 12 MiB")
        return data


class LocalToolbox:
    def __init__(
        self,
        *,
        workspace: Path,
        permission_mode: str,
        original_prompt: str,
        output_root: Path | None = None,
    ) -> None:
        if permission_mode not in {"ask", "always"}:
            raise ValueError(f"unknown permission mode {permission_mode!r}")
        self.workspace = workspace
        self.permission_mode = permission_mode
        self.original_prompt = original_prompt.casefold()
        self.output_root = (output_root or DEFAULT_OUTPUT_ROOT).expanduser()
        self.browser: Browser | None = None
        self.work = WorkRelay()

    def _resolved_output(self, raw: str) -> Path:
        """Resolve a model-supplied file name inside the output folder.

        The name is untrusted model output, so containment is checked after
        resolution rather than by inspecting the string: `..` segments, an
        absolute path and a symlinked parent all fail the same way.
        """
        name = str(raw).strip()
        if not name:
            raise ValueError("path is required")
        self.output_root.mkdir(parents=True, exist_ok=True)
        root = self.output_root.resolve()
        destination = (root / name).resolve()
        if destination != root and root not in destination.parents:
            raise ValueError("documents may only be written inside the Sleipnir output folder")
        return destination

    def _approval(self, action: str) -> str | None:
        if self.permission_mode == "always":
            return None
        return json.dumps({"status": "approval_required", "action": action})

    async def _web(self) -> Browser:
        if self.browser is None:
            self.browser = await Browser().start()
        return self.browser

    async def execute(self, name: str, arguments: dict[str, Any]) -> str:
        if name == "observe_screen":
            return "A fresh desktop frame is attached in the next message."
        if name == "browser_open":
            raw = str(arguments.get("url", "")).strip()
            if not raw:
                raise ValueError("url is required")
            url = raw if urlparse(raw).scheme in {"http", "https"} else f"https://{raw}"
            await (await self._web()).goto(url)
            return json.dumps(await (await self._web()).state())[:MAX_TOOL_RESULT_CHARS]
        if name == "browser_text":
            if arguments.get("selector"):
                text = await (await self._web()).text(str(arguments["selector"]))
                return text[:MAX_TOOL_RESULT_CHARS]
            return json.dumps(await (await self._web()).state())[:MAX_TOOL_RESULT_CHARS]
        if name in {"browser_click", "browser_click_text", "browser_fill", "computer_click", "computer_type", "computer_key", "computer_scroll"}:
            if blocked := self._approval(name):
                return blocked
        if name == "browser_click":
            await (await self._web()).click(str(arguments["selector"]))
            return "clicked browser element"
        if name == "browser_click_text":
            await (await self._web()).click_text(str(arguments["text"]))
            return json.dumps(await (await self._web()).state())[:MAX_TOOL_RESULT_CHARS]
        if name == "browser_fill":
            await (await self._web()).fill(str(arguments["selector"]), str(arguments["text"]))
            return "filled browser field"
        if name == "computer_click":
            await asyncio.to_thread(computer.move_mouse, int(arguments["x"]), int(arguments["y"]))
            await asyncio.to_thread(computer.click, str(arguments.get("button", "left")))
            return "clicked desktop coordinates"
        if name == "computer_type":
            await asyncio.to_thread(computer.type_text, str(arguments["text"]))
            return "typed into focused window"
        if name == "computer_key":
            combo = [part for part in str(arguments["combo"]).casefold().split("+") if part]
            await asyncio.to_thread(computer.key, *combo)
            return "pressed key chord"
        if name == "computer_scroll":
            await asyncio.to_thread(computer.scroll, int(arguments["amount"]))
            return "scrolled focused window"
        if name == "write_file":
            destination = self._resolved_output(arguments.get("path", ""))
            content = str(arguments.get("content", ""))
            if len(content.encode("utf-8")) > MAX_DOCUMENT_BYTES:
                raise ValueError("document exceeds the 2 MiB local write limit")
            # Creating a new file is ordinary work; replacing the operator's
            # existing one is a mutation, and mutations wait for `always`.
            if destination.exists() and self.permission_mode != "always":
                return json.dumps({"status": "approval_required", "action": f"overwrite {destination.name}"})
            destination.write_text(content, encoding="utf-8")
            audit.record("local.write_file", {"path": str(destination), "chars": len(content)})
            return json.dumps({"status": "written", "path": str(destination)})
        if name == "open_file":
            destination = self._resolved_output(arguments.get("path", ""))
            if not destination.is_file():
                raise ValueError(f"{destination.name} has not been written yet")
            await (await self._web()).goto(destination.as_uri())
            return json.dumps({"status": "opened", "path": str(destination)})
        if name == "delegate_work":
            provider = str(arguments["provider"]).casefold()
            if self.permission_mode != "always" and provider not in self.original_prompt:
                return json.dumps({"status": "approval_required", "action": f"delegate to {provider}"})
            prompt = f"{capability_brief()}\n\n{str(arguments['instruction']).strip()}"
            reply = await self.work.send(
                prompt,
                provider=provider,
                workspace=self.workspace,
                permission_mode=self.permission_mode,
            )
            return reply.text[:MAX_TOOL_RESULT_CHARS]
        raise ValueError(f"unknown local tool {name!r}")

    async def close(self) -> None:
        if self.browser is not None:
            await self.browser.close()
        await self.work.close()


class LocalDesktopAgent:
    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        observer: ScreenObserver | None = None,
        tool_runner: Callable[[str, dict[str, Any]], Awaitable[str]] | None = None,
    ) -> None:
        self.transport = transport
        self.observer = observer or ScreenObserver()
        self.tool_runner = tool_runner

    async def respond(
        self,
        prompt: str,
        *,
        model: str,
        workspace: Path,
        permission_mode: str,
    ) -> LocalAgentReply:
        clean = prompt.strip()
        if not clean:
            raise ValueError("local agent prompt cannot be empty")
        workspace = workspace.resolve()
        toolbox = None if self.tool_runner else LocalToolbox(
            workspace=workspace, permission_mode=permission_mode, original_prompt=clean
        )
        run_tool = self.tool_runner or toolbox.execute  # type: ignore[union-attr]
        performed: list[str] = []
        nudged = False
        if is_smalltalk(clean):
            return await self._chat(clean, model=model)
        if needs_reasoning(clean):
            return await self._reason(clean, model=model)
        opening: dict[str, Any] = (
            await self._visual_message(clean)
            if needs_screen(clean)
            else {"role": "user", "content": clean}
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": LOCAL_AGENT_SYSTEM},
            opening,
        ]
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=180) as client:
                for step in range(1, MAX_AGENT_STEPS + 1):
                    response = await client.post(
                        "http://127.0.0.1:11434/api/chat",
                        json={
                            "model": model,
                            "messages": messages,
                            "tools": TOOLS,
                            "stream": False,
                            # Small local models can spend the entire output budget
                            # on hidden reasoning and emit neither a tool nor a final
                            # answer. The visible observe/act loop is the reasoning
                            # trace we can actually verify.
                            "think": False,
                            "keep_alive": "15m",
                            # A document-producing tool call carries the whole document in its
                            # arguments.  A 512- or 1024-token cap truncates that mid-JSON,
                            # which arrives as an empty message rather than as an error.
                            "options": {"temperature": 0.2, "num_predict": 4096},
                        },
                    )
                    if response.status_code != 200:
                        detail = response.text.strip().replace("\n", " ")[:480]
                        raise VoiceProviderError(
                            f"Ollama local agent returned HTTP {response.status_code}"
                            f"{f': {detail}' if detail else ''}"
                        )
                    try:
                        message = response.json()["message"]
                    except (KeyError, TypeError, ValueError) as error:
                        raise VoiceProviderError("Ollama local agent returned no message") from error
                    assistant = {
                        key: message[key]
                        for key in ("role", "content", "thinking", "tool_calls")
                        if key in message
                    }
                    messages.append(assistant)
                    calls = message.get("tool_calls") or []
                    if not calls:
                        text = strip_thinking(str(message.get("content", "")))
                        if not performed and not nudged and _promises_action(text):
                            nudged = True
                            messages.append({"role": "user", "content": ACTION_NUDGE})
                            continue
                        if not text:
                            # The operator is owed an answer even when the model
                            # goes quiet: silence after a spoken instruction is
                            # indistinguishable from not having heard them.
                            if not performed:
                                raise VoiceProviderError("Ollama local agent returned an empty reply")
                            text = f"Done. I ran {', '.join(dict.fromkeys(performed))}."
                        return LocalAgentReply(text=text, model=model, steps=step)
                    refresh = False
                    for call in calls:
                        function = call.get("function", {})
                        name = str(function.get("name", ""))
                        arguments = function.get("arguments") or {}
                        if not isinstance(arguments, dict):
                            raise VoiceProviderError("Ollama emitted invalid tool arguments")
                        try:
                            result = await run_tool(name, arguments)
                        except Exception as error:  # noqa: BLE001 - error becomes bounded tool evidence
                            result = json.dumps({"status": "error", "detail": str(error)[:480]})
                        performed.append(name)
                        messages.append({"role": "tool", "tool_name": name, "content": result[:MAX_TOOL_RESULT_CHARS]})
                        refresh = refresh or name in {
                            "observe_screen", "browser_open", "browser_click", "browser_click_text", "browser_fill",
                            "computer_click", "computer_type", "computer_key", "computer_scroll",
                        }
                    if refresh:
                        # The model needs the newest visual state, not an ever-growing
                        # filmstrip. Keeping old frames exhausts a modest local context
                        # after one action and contradicts the live-observer contract.
                        for prior in messages:
                            prior.pop("images", None)
                        messages.append(await self._visual_message("Fresh desktop state after the tool result."))
        finally:
            if toolbox is not None:
                await toolbox.close()
        # The step limit is a budget, not a failure to report: an operator who
        # spoke an instruction is told what happened rather than hearing an error.
        if performed:
            return LocalAgentReply(
                text=f"I stopped at my {MAX_AGENT_STEPS}-step limit after {', '.join(dict.fromkeys(performed))}.",
                model=model,
                steps=MAX_AGENT_STEPS,
            )
        raise VoiceProviderError(f"local agent exceeded its {MAX_AGENT_STEPS}-step safety limit")

    async def _single_turn(
        self, content: str, *, model: str, system: str, think: bool, num_predict: int
    ) -> tuple[str, str]:
        """One Ollama call. Returns ``(content, thinking)``, both stripped."""
        async with httpx.AsyncClient(transport=self.transport, timeout=300) as client:
            response = await client.post(
                "http://127.0.0.1:11434/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": content},
                    ],
                    "stream": False,
                    "think": think,
                    "keep_alive": "15m",
                    "options": {"temperature": 0.2 if think else 0.4, "num_predict": num_predict},
                },
            )
        if response.status_code != 200:
            detail = response.text.strip().replace("\n", " ")[:480]
            raise VoiceProviderError(
                f"Ollama local agent returned HTTP {response.status_code}"
                f"{f': {detail}' if detail else ''}"
            )
        try:
            message = response.json()["message"]
        except (KeyError, TypeError, ValueError) as error:
            raise VoiceProviderError("Ollama local agent returned no message") from error
        return (
            strip_thinking(str(message.get("content", ""))),
            str(message.get("thinking", "")).strip(),
        )

    async def _reason(self, content: str, *, model: str) -> LocalAgentReply:
        """Answer with a scratchpad, and never hand back the scratchpad.

        Ollama reports reasoning in its own ``thinking`` field, so empty content
        beside non-empty thinking says the model deliberated without converging.
        That is a capability limit, not a transient fault: it is raised as
        :class:`LocalCapabilityExceeded` so the caller delegates instead of
        paying for a longer version of the same failure.
        """
        try:
            async with asyncio.timeout(REASON_DEADLINE_SECONDS):
                text, thinking = await self._single_turn(
                    content,
                    model=model,
                    system=REASON_SYSTEM,
                    think=True,
                    num_predict=REASON_TOKENS,
                )
        except TimeoutError as error:
            raise LocalCapabilityExceeded(
                f"the local model did not converge on this within {REASON_DEADLINE_SECONDS:.0f} seconds"
            ) from error
        if not text:
            raise LocalCapabilityExceeded(
                "the local model deliberated without reaching an answer"
                if thinking
                else "the local model returned no answer"
            )
        return LocalAgentReply(text=text, model=model, steps=1)

    async def _chat(self, content: str, *, model: str) -> LocalAgentReply:
        """Answer a greeting in exactly one call: no tools, no frame, no loop.

        The twelve-step agent loop is the wrong shape for "what's up" -- it
        pays a screenshot and a vision encode before it can even decline to use
        a tool, which is what made a greeting take twenty seconds.
        """
        text, _ = await self._single_turn(
            content, model=model, system=CHAT_SYSTEM, think=False, num_predict=96
        )
        if not text:
            # MEASURED: qwen3-vl answers nothing at all with thinking disabled,
            # so every greeting fell through to the placeholder. A greeting is
            # short enough that a bounded scratchpad is still fast.
            text, _ = await self._single_turn(
                content, model=model, system=CHAT_SYSTEM, think=True, num_predict=256
            )
        return LocalAgentReply(text=text or "I'm here.", model=model, steps=1)

    async def _visual_message(self, content: str) -> dict[str, Any]:
        frame = await self.observer.capture()
        return {
            "role": "user",
            "content": content,
            "images": [base64.b64encode(frame).decode("ascii")],
        }


__all__ = [
    "CHAT_SYSTEM", "LOCAL_AGENT_SYSTEM", "LocalCapabilityExceeded", "REASON_SYSTEM", "LocalAgentReply", "LocalDesktopAgent", "LocalToolbox",
    "MAX_AGENT_STEPS", "ScreenObserver", "TOOLS", "strip_thinking",
]
