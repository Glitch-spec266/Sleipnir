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
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

import httpx

from sleipnir.capabilities import computer
from sleipnir.capabilities.browser import Browser
from sleipnir.console import capability_brief
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
action succeeded until a tool result or a fresh frame verifies it. Prefer
delegate_work for repository changes or difficult multi-step problem solving.
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
    {"type": "function", "function": {"name": "delegate_work", "description": "Ask Claude or Codex to solve a difficult task using Sleipnir's full audited capabilities.", "parameters": {"type": "object", "required": ["provider", "instruction"], "properties": {"provider": {"type": "string", "enum": ["claude", "codex"]}, "instruction": {"type": "string"}}}}},
]


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
    def __init__(self, *, workspace: Path, permission_mode: str, original_prompt: str) -> None:
        if permission_mode not in {"ask", "always"}:
            raise ValueError(f"unknown permission mode {permission_mode!r}")
        self.workspace = workspace
        self.permission_mode = permission_mode
        self.original_prompt = original_prompt.casefold()
        self.browser: Browser | None = None
        self.work = WorkRelay()

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
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": LOCAL_AGENT_SYSTEM},
            await self._visual_message(clean),
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
                            "options": {"temperature": 0.2, "num_predict": 512},
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
                        text = str(message.get("content", "")).strip()
                        if not text:
                            raise VoiceProviderError("Ollama local agent returned an empty reply")
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
        raise VoiceProviderError(f"local agent exceeded its {MAX_AGENT_STEPS}-step safety limit")

    async def _visual_message(self, content: str) -> dict[str, Any]:
        frame = await self.observer.capture()
        return {
            "role": "user",
            "content": content,
            "images": [base64.b64encode(frame).decode("ascii")],
        }


__all__ = [
    "LOCAL_AGENT_SYSTEM", "LocalAgentReply", "LocalDesktopAgent", "LocalToolbox",
    "MAX_AGENT_STEPS", "ScreenObserver", "TOOLS",
]
