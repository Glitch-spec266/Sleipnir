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
import os
import re
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

import httpx

from sleipnir.capabilities import audit
from sleipnir.capabilities import computer
from sleipnir.capabilities.browser import Browser
from sleipnir.console import capability_brief
from sleipnir.voice.dispatch import (
    SPOKEN_CONTRACT,
    DispatchRefused,
    delegation_menu,
    menu_for,
    pick_model,
    spoken_line,
)
from sleipnir.schema import Tier
from sleipnir.voice.relay import AmbientRelay
from sleipnir.voice.routing import is_observation, needs_reasoning, needs_screen, needs_tools
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

If text in a frame is too small to read with certainty, call observe_region on
the rectangle around it and read the close-up. Never guess at small text: say
you cannot read it rather than inventing what it says. Form controls appear in
the browser page state with their role and their checked flag, so read that
state to see which option is selected rather than judging it from a picture.

Solve the operator's problem yourself. Reasoning, planning, explanations,
research, maths, writing, and documents are your work, not someone else's: think
it through and answer. Use build_deck when the operator asks for a slide deck or
presentation, and write_file for any other document or deliverable -- an essay,
notes, a plan, a web page -- and then say where you put it. A spoken question is answered by
speaking, not by writing a file. Only call delegate_work when the operator names Claude or Codex, or
when the task needs changes to a source repository.

The desktop frame is background context. Do not describe it, and do not call
observe_screen, unless the operator's request is about what is on the screen.

Always end your turn by speaking one short sentence to the operator confirming
what you did or found, even when the task needed no answer.

Do not request, reveal, or type credentials; credential entry stays behind
Sleipnir's protected operator prompt. Stop when the task is complete or when a
tool says operator approval is required. When a tool answers
approval_required, stop immediately and say in one sentence what you intend to
do and why, so the operator can approve the whole task at once. Do not retry
the same action, and do not carry on as if it had succeeded."""


TOOLS: list[dict[str, Any]] = [
    {"type": "function", "function": {"name": "observe_screen", "description": "Attach the newest full-desktop frame so you can read text, images, and UI state.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "observe_region", "description": "Attach a close-up of one rectangle of the screen at full fidelity. Use this when text is too small to read in the full frame; the last frame's own coordinates tell you where to look.", "parameters": {"type": "object", "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}, "width": {"type": "integer"}, "height": {"type": "integer"}}, "required": ["x", "y", "width", "height"]}}},
    {"type": "function", "function": {"name": "browser_scroll", "description": "Scroll the browser page; negative moves down. Returns the page state that follows.", "parameters": {"type": "object", "properties": {"amount": {"type": "integer"}}, "required": ["amount"]}}},
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
    {"type": "function", "function": {"name": "build_deck", "description": "Build a real PowerPoint (.pptx) presentation in the operator's Sleipnir folder. Use this whenever a slide deck or presentation is asked for.", "parameters": {"type": "object", "required": ["path", "title", "slides"], "properties": {"path": {"type": "string", "description": "File name ending in .pptx, e.g. photosynthesis.pptx"}, "title": {"type": "string"}, "slides": {"type": "array", "items": {"type": "object", "required": ["title"], "properties": {"title": {"type": "string"}, "bullets": {"type": "array", "items": {"type": "string"}}}}}}}}},
    {"type": "function", "function": {"name": "open_file", "description": "Show a file you wrote to the operator in Sleipnir's browser.", "parameters": {"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "delegate_work", "description": "Hand a problem you cannot solve to a capable worker. Use claude or codex only when the operator names them or the task changes a source repository; use api with a tier from the delegation menu for a hard question you cannot answer yourself.", "parameters": {"type": "object", "required": ["provider", "instruction"], "properties": {"provider": {"type": "string", "enum": ["claude", "codex", "api"]}, "tier": {"type": "string", "description": "Required for provider=api: the tier name from the delegation menu."}, "instruction": {"type": "string"}}}}},
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


def _conversation_turns(
    history: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, str]]:
    """Turn recent stored history into bounded Ollama chat messages.

    History entries are written by the GUI bridge and carry its own role names
    plus routing metadata. Only the role and the text are forwarded; anything
    else -- a route, a timestamp, a path -- is not conversation and would only
    spend context.
    """
    turns: list[dict[str, str]] = []
    for entry in list(history or [])[-CHAT_HISTORY_TURNS:]:
        text = str(entry.get("text", "")).strip()
        if not text:
            continue
        role = "user" if str(entry.get("role", "")) == "operator" else "assistant"
        turns.append({"role": role, "content": text})
    return turns


class LocalCapabilityExceeded(VoiceProviderError):
    """The local model cannot finish this task, so it must be delegated.

    Distinct from a provider fault: the call succeeded and the model simply was
    not good enough. Retrying it locally buys nothing.
    """


# MEASURED 2026-09-10: asking this model to be brief is what made it loop.
# Bare, it answered 17*24+139 correctly in 11.0 s with 1,748 characters of
# thinking. Adding *any* brevity instruction -- in the system role or appended
# to the user turn -- pushed thinking to 6,800-7,700 characters and returned
# empty content past the deadline, every time. It deliberates about being
# short instead of about the problem.
#
# So the question goes in bare and the answer is shortened afterwards. Same
# rule as "clip the goal, never the prompt": shorten the output, not the ask.
SHORTEN_PROMPT = (
    "Restate this answer as one short spoken sentence, keeping the number and "
    "its units:\n\n"
)
#: How much of a long answer is shown to the shortening call. Two thousand
#: characters is far more than any spoken answer needs and keeps the second
#: call cheap.
SHORTEN_SOURCE_CHARS = 2_000
SHORTEN_TOKENS = 120

# MEASURED: reasoning consumed the whole token budget on the physics question
# and left nothing for the answer, which reached the operator as silence.
REASON_TOKENS = 2048
# MEASURED 2026-09-10 on the bare-question protocol: 12.0 s for the arithmetic
# and 25.0 s for the projectile question, both correct. The 9B was correct too
# and took 21.4 s and 36.9 s for twice the VRAM, which is why the smaller model
# stayed. Forty seconds covers the measured worst case with headroom; a model
# that is genuinely looping still hands the question on rather than making the
# operator wait for a longer version of the same failure.
REASON_DEADLINE_SECONDS = 40.0

# The conversational lane is the default, so this system prompt answers
# questions as well as greetings. It must not mention tools: the model does not
# have any on this lane, and naming them makes a small model promise an action
# it cannot take.
CHAT_SYSTEM = (
    "You are JARVIS, the operator's assistant, speaking aloud in conversation. "
    "Talk with them: greet them back, answer from what you know, and ask a "
    "natural follow-up when there is one. Keep it to one or two spoken "
    "sentences. Do not think out loud and do not mention the screen. You are "
    "not doing anything right now: never say you have adjusted, opened, "
    "checked or changed something, and do not offer to -- if the operator "
    "wants something done they will ask for it."
)
# One or two spoken sentences, with the headroom a real answer needs. 96 tokens
# truncated anything longer than a greeting.
CHAT_TOKENS = 320
# Enough to resolve "and you?" or "why?" without turning every greeting into a
# long prompt. Bounded on purpose: history is the one thing on this lane that
# could grow without limit.
CHAT_HISTORY_TURNS = 8

# Reading the screen is one vision call, not a tool loop. MEASURED 2026-09-11:
# "what's on my screen right now" took 43.5 s and twelve steps through the tool
# loop and produced no answer; the same frame answered in a single call in
# roughly two seconds. The prompt forbids claiming action because the loop's
# failure mode was narrating browser clicks it had made by accident.
LOOK_SYSTEM = (
    "You are JARVIS, the operator's assistant, speaking aloud. The image "
    "attached is the operator's screen as it is right now. Answer their "
    "question about it in one or two short spoken sentences. Describe only "
    "what you can actually see; if text is too small to read, say so rather "
    "than guessing. You have no tools on this turn: never say you have "
    "opened, clicked, scrolled or changed anything, and never mention a page "
    "or application that is not visible in this image."
)
LOOK_TOKENS = 320


def with_operator(system: str, operator_name: str) -> str:
    """Prefix a system prompt with the operator's name when one is configured.

    A name is ordinary preference data, not a credential, so it travels in
    ``preferences.json`` like the wake word. Without it the assistant answers
    "I don't have access to your personal information" to "what is my name",
    which is true and useless.
    """
    name = " ".join((operator_name or "").split())
    if not name:
        return system
    return f"You are speaking with {name}. Address them by name when it is natural.\n\n{system}"


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
# A delegated answer is spoken, and only its first line returns to the local
# model. Paying for more than that buys detail nobody reads.
MAX_DELEGATED_TOKENS = 700
# A spoken request produces a deck somebody reads, not a book. These caps
# are what keep a looping model from writing a hundred-slide file.
MAX_DECK_SLIDES = 40
MAX_DECK_BULLETS = 12
MAX_DECK_TEXT = 300
DEFAULT_OUTPUT_ROOT = Path.home() / "Sleipnir"


@dataclass(frozen=True, slots=True)
class LocalAgentReply:
    text: str
    model: str
    steps: int
    # The consequential action this turn stopped on, so the console can ask the
    # operator once for the whole task rather than once per click.
    approval: str | None = None


# A whole screen has to fit a model's image budget; a region the operator asked
# about is small enough to keep more of its pixels and less compression.
FRAME_PIXELS = 1280
CLOSE_LOOK_PIXELS = 1600


class ScreenObserver:
    """Capture one audited frame without leaving screenshot files behind."""

    async def capture(self, *, region: tuple[int, int, int, int] | None = None) -> bytes:
        """Capture the screen, or one region of it at full fidelity.

        A 1920x1080 screen downscaled to fit 1280 px leaves small text a guess,
        and a model asked to read it will guess confidently. Cropping before
        the downscale is what lets a form question keep its own pixels.
        """
        if region is not None:
            left, top, width, height = region
            if width <= 0 or height <= 0:
                raise ValueError("a screen region must have a positive width and height")
        with tempfile.TemporaryDirectory(prefix="sleipnir-observe-") as root:
            path = Path(root) / "desktop.png"
            await asyncio.to_thread(computer.screenshot, path)
            frame = path
            if converter := shutil.which("magick") or shutil.which("convert"):
                reduced = Path(root) / "desktop.jpg"
                argv = [converter, str(path)]
                if region is not None:
                    left, top, width, height = region
                    argv += ["-crop", f"{width}x{height}+{left}+{top}", "+repage"]
                argv += [
                    "-resize",
                    f"{CLOSE_LOOK_PIXELS if region else FRAME_PIXELS}x"
                    f"{CLOSE_LOOK_PIXELS if region else FRAME_PIXELS}>",
                    "-strip",
                    "-quality",
                    "90" if region else "72",
                    str(reduced),
                ]
                process = await asyncio.create_subprocess_exec(
                    *argv,
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
        task_grant: bool = False,
    ) -> None:
        if permission_mode not in {"ask", "always"}:
            raise ValueError(f"unknown permission mode {permission_mode!r}")
        self.workspace = workspace
        self.permission_mode = permission_mode
        self.original_prompt = original_prompt.casefold()
        self.output_root = (output_root or DEFAULT_OUTPUT_ROOT).expanduser()
        self.browser: Browser | None = None
        self.work = WorkRelay()
        self.relay = AmbientRelay()
        # Routing inputs are loaded once per turn at most, and only if the
        # model actually delegates: an ordinary turn must not pay for a
        # catalogue fetch it never uses.
        self._routing: tuple[Any, Any] | None = None
        # Set by observe_region and consumed by the next frame refresh, so a
        # close-up replaces the wide frame rather than adding a second image.
        self.pending_region: tuple[int, int, int, int] | None = None
        # One spoken "yes" covers this turn's task. Answering a five-question
        # form takes a dozen consequential actions, and refusing each one made
        # the task unreachable rather than merely guarded.
        self.task_grant = task_grant
        self.blocked: list[str] = []

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
        """Refuse a consequential action unless this task is already approved.

        The grant is scoped to one turn and never covers credentials: those
        stay behind Sleipnir's protected operator prompt regardless.
        """
        if self.permission_mode == "always" or self.task_grant:
            return None
        self.blocked.append(action)
        return json.dumps({"status": "approval_required", "action": action})

    async def _web(self) -> Browser:
        if self.browser is None:
            self.browser = await Browser().start()
        return self.browser

    async def execute(self, name: str, arguments: dict[str, Any]) -> str:
        if name == "observe_screen":
            return "A fresh desktop frame is attached in the next message."
        if name == "observe_region":
            self.pending_region = (
                int(arguments["x"]),
                int(arguments["y"]),
                int(arguments["width"]),
                int(arguments["height"]),
            )
            return "A close-up of that region is attached in the next message."
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
        if name in {"browser_click", "browser_click_text", "browser_fill", "browser_scroll", "computer_click", "computer_type", "computer_key", "computer_scroll"}:
            if blocked := self._approval(name):
                return blocked
        if name == "browser_click":
            await (await self._web()).click(str(arguments["selector"]))
            # Returning the literal "clicked browser element" left the model
            # blind until the next frame, so it had to guess what its own click
            # had done.
            return json.dumps(await (await self._web()).state())[:MAX_TOOL_RESULT_CHARS]
        if name == "browser_click_text":
            await (await self._web()).click_text(str(arguments["text"]))
            return json.dumps(await (await self._web()).state())[:MAX_TOOL_RESULT_CHARS]
        if name == "browser_fill":
            await (await self._web()).fill(str(arguments["selector"]), str(arguments["text"]))
            return json.dumps(await (await self._web()).state())[:MAX_TOOL_RESULT_CHARS]
        if name == "browser_scroll":
            await (await self._web()).scroll(int(arguments["amount"]))
            return json.dumps(await (await self._web()).state())[:MAX_TOOL_RESULT_CHARS]
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
        if name == "build_deck":
            return await asyncio.to_thread(
                self._build_deck,
                str(arguments.get("path", "")),
                str(arguments.get("title", "")),
                list(arguments.get("slides") or []),
            )
        if name == "open_file":
            destination = self._resolved_output(arguments.get("path", ""))
            if not destination.is_file():
                raise ValueError(f"{destination.name} has not been written yet")
            await (await self._web()).goto(destination.as_uri())
            return json.dumps({"status": "opened", "path": str(destination)})
        if name == "delegate_work":
            return await self._delegate(arguments)
        raise ValueError(f"unknown local tool {name!r}")

    def _build_deck(self, path: str, title: str, slides: list[Any]) -> str:
        """Write a real .pptx, reusing write_file's containment check.

        python-pptx is an optional extra so the core keeps its three runtime
        dependencies. A machine without it gets a refusal that names the extra,
        which the model can repeat to the operator -- a traceback cannot be.
        """
        try:
            from pptx import Presentation  # noqa: PLC0415 - optional extra
            from pptx.util import Pt
        except ImportError:
            return json.dumps({
                "status": "unavailable",
                "reason": "presentations need the optional python-pptx extra "
                          "(pip install 'sleipnir[deck]')",
            })
        destination = self._resolved_output(path)
        if destination.suffix.casefold() != ".pptx":
            destination = destination.with_suffix(".pptx")
        if destination.exists() and self.permission_mode != "always":
            return json.dumps({"status": "approval_required", "action": f"overwrite {destination.name}"})
        if len(slides) > MAX_DECK_SLIDES:
            raise ValueError(f"a deck may hold at most {MAX_DECK_SLIDES} slides")

        deck = Presentation()
        opening = deck.slides.add_slide(deck.slide_layouts[0])
        opening.shapes.title.text = title[:MAX_DECK_TEXT] or "Presentation"
        for entry in slides:
            if not isinstance(entry, dict):
                raise ValueError("each slide must be an object with a title")
            slide = deck.slides.add_slide(deck.slide_layouts[1])
            slide.shapes.title.text = str(entry.get("title", ""))[:MAX_DECK_TEXT]
            body = slide.placeholders[1].text_frame
            body.clear()
            bullets = [str(b)[:MAX_DECK_TEXT] for b in (entry.get("bullets") or [])]
            for index, bullet in enumerate(bullets[:MAX_DECK_BULLETS]):
                paragraph = body.paragraphs[0] if index == 0 else body.add_paragraph()
                paragraph.text = bullet
                paragraph.font.size = Pt(20)
        destination.parent.mkdir(parents=True, exist_ok=True)
        deck.save(str(destination))
        audit.record(
            "local.build_deck",
            {"path": str(destination), "slides": len(slides)},
        )
        return json.dumps({"status": "written", "path": str(destination)})

    async def _delegate(self, arguments: dict[str, Any]) -> str:
        """Hand the turn to a capable worker, and audit every outcome.

        Delegation spends the operator's quota somewhere else, which makes it a
        privileged call in exactly the sense the audit log exists for. Three
        shapes are recorded -- the refusal, the routing decision and the
        result -- and never the instruction itself: that is the operator's
        words and the worker's prompt, so only its size is logged, the same
        rule as typed text.
        """
        provider = str(arguments["provider"]).casefold()
        instruction = str(arguments["instruction"]).strip()
        if self.permission_mode != "always" and provider not in self.original_prompt:
            audit.record(
                "local.delegate_work",
                {"provider": provider, "chars": len(instruction), "outcome": "refused"},
            )
            return json.dumps({"status": "approval_required", "action": f"delegate to {provider}"})

        if provider == "api":
            return await self._delegate_to_tier(arguments.get("tier", ""), instruction)

        prompt = f"{capability_brief()}\n\n{instruction}"
        reply = await self.work.send(
            prompt,
            provider=provider,
            workspace=self.workspace,
            permission_mode=self.permission_mode,
        )
        audit.record(
            "local.delegate_work",
            {
                "provider": provider,
                "chars": len(instruction),
                "outcome": "answered",
                "reply_chars": len(reply.text),
            },
        )
        return reply.text[:MAX_TOOL_RESULT_CHARS]

    async def _delegate_to_tier(self, tier: str, instruction: str) -> str:
        """Route a tier the model named to one free model and ask it.

        Only the worker's spoken line comes back. Delegation happens because
        the local model already lost this problem; handing it the whole reply
        to summarise would spend its context on the work it could not do.
        """
        try:
            config, catalog = await self._routing_inputs()
            choice = pick_model(config, catalog, tier=str(tier))
        except DispatchRefused as error:
            audit.record(
                "local.delegate_work",
                {"provider": "api", "tier": str(tier)[:40], "outcome": "refused"},
            )
            return json.dumps({"status": "unavailable", "reason": str(error)[:400]})
        audit.record(
            "local.delegate_work",
            {
                "provider": "api",
                "tier": choice.tier.value,
                "backend": choice.backend,
                "model": choice.model,
                "chars": len(instruction),
                "outcome": "routed",
            },
        )
        # Read at call time and never stored, never logged: the choice carries
        # the variable's *name*, exactly as the config schema does.
        key = os.environ.get(choice.api_key_env, "") if choice.api_key_env else ""
        reply = await self.relay.respond(
            instruction,
            provider="openai",
            api_key=key,
            model=choice.model,
            base_url=choice.base_url,
            system=SPOKEN_CONTRACT,
            max_tokens=MAX_DELEGATED_TOKENS,
        )
        spoken = spoken_line(reply.text)
        audit.record(
            "local.delegate_work",
            {"provider": "api", "model": choice.model, "outcome": "answered",
             "reply_chars": len(reply.text), "spoken_chars": len(spoken)},
        )
        return spoken

    async def _routing_inputs(self) -> tuple[Any, Any]:
        """Load the operator's config and the price catalogue, once per turn."""
        if self._routing is not None:
            return self._routing
        from sleipnir.config import ConfigError, SleipnirConfig
        from sleipnir.pricing import (
            DEFAULT_MODELS_URL,
            CatalogUnavailableError,
            ModelCatalog,
        )

        path = SleipnirConfig.discover(self.workspace)
        if path is None:
            raise DispatchRefused(
                "no sleipnir.toml is configured, so there are no tiers to route to"
            )
        try:
            config = SleipnirConfig.load(path)
        except ConfigError as error:
            raise DispatchRefused(f"the operator's config could not be read: {error}") from error
        try:
            catalog = await ModelCatalog(
                url=config.catalog_url or DEFAULT_MODELS_URL,
                ttl_s=config.catalog_ttl_s,
                **({"cache_path": config.catalog_cache_path} if config.catalog_cache_path else {}),
            ).load()
        except CatalogUnavailableError as error:
            # A missing catalogue means no prices, and a missing price is never
            # zero. Refusing is the only answer that keeps the free-only
            # guarantee honest.
            raise DispatchRefused(f"live prices are unavailable: {error}") from error
        self._routing = (config, catalog)
        return self._routing

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
        task_grant: bool = False,
        history: Sequence[Mapping[str, Any]] | None = None,
        operator_name: str = "",
    ) -> LocalAgentReply:
        clean = prompt.strip()
        if not clean:
            raise ValueError("local agent prompt cannot be empty")
        workspace = workspace.resolve()
        toolbox = None if self.tool_runner else LocalToolbox(
            workspace=workspace,
            permission_mode=permission_mode,
            original_prompt=clean,
            task_grant=task_grant,
        )
        run_tool = self.tool_runner or toolbox.execute  # type: ignore[union-attr]
        performed: list[str] = []
        nudged = False
        if needs_reasoning(clean):
            try:
                return await self._reason(clean, model=model)
            except LocalCapabilityExceeded:
                # The deadline exists to hand off fast rather than make the
                # operator wait, so it has to actually hand off. Going through
                # the tool keeps the delegation on the audited path.
                return await self._escalate(clean, model=model, run_tool=run_tool)
        if is_observation(clean):
            return await self._look(clean, model=model, operator_name=operator_name)
        if not needs_tools(clean):
            return await self._chat(
                clean, model=model, history=history, operator_name=operator_name
            )
        opening: dict[str, Any] = (
            await self._visual_message(clean)
            if needs_screen(clean)
            else {"role": "user", "content": clean}
        )
        # The menu is the only thing the model is ever told about delegation
        # targets: tier names and the operator's own one-line descriptions,
        # never a model id or a price.
        menu = menu_for(workspace)
        system = (
            f"{LOCAL_AGENT_SYSTEM}\n\nDelegation tiers you may name with "
            f"provider=api:\n{menu}"
            if menu
            else LOCAL_AGENT_SYSTEM
        )
        # The tool loop had no history at all, so a follow-up ("do that again
        # for the other one") reached the model with no referent and it asked
        # about the screen instead.
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": with_operator(system, operator_name)},
            *_conversation_turns(history),
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
                        return LocalAgentReply(
                            text=text,
                            model=model,
                            steps=step,
                            approval=toolbox.blocked[0] if toolbox and toolbox.blocked else None,
                        )
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
                            "observe_screen", "observe_region", "browser_open", "browser_click",
                            "browser_click_text", "browser_fill", "browser_scroll",
                            "computer_click", "computer_type", "computer_key", "computer_scroll",
                        }
                    if refresh:
                        # The model needs the newest visual state, not an ever-growing
                        # filmstrip. Keeping old frames exhausts a modest local context
                        # after one action and contradicts the live-observer contract.
                        for prior in messages:
                            prior.pop("images", None)
                        region = getattr(toolbox, "pending_region", None)
                        if toolbox is not None:
                            toolbox.pending_region = None
                        messages.append(
                            await self._visual_message(
                                "A close-up of the region you asked for."
                                if region
                                else "Fresh desktop state after the tool result.",
                                region=region,
                            )
                        )
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

    async def _escalate(
        self, content: str, *, model: str, run_tool: Callable[[str, dict[str, Any]], Awaitable[str]]
    ) -> LocalAgentReply:
        """Hand an unanswerable question to a capable tier, and speak the result."""
        answer = await run_tool(
            "delegate_work",
            {"provider": "api", "tier": Tier.REASON.value, "instruction": content},
        )
        text = str(answer).strip()
        if text.startswith("{"):
            # A refusal envelope is for the log, not for the speakers. The
            # operator asked a question and is owed a sentence either way.
            try:
                reason = str(json.loads(text).get("reason", "")).strip()
            except ValueError:
                reason = ""
            detail = f" -- {reason}" if reason else ""
            return LocalAgentReply(
                text=f"I couldn't work that one out, and I couldn't hand it on either{detail}.",
                model=model,
                steps=1,
            )
        return LocalAgentReply(text=text, model=model, steps=1)

    async def _single_turn(
        self,
        content: str,
        *,
        model: str,
        system: str,
        think: bool,
        num_predict: int,
        prior: list[dict[str, str]] | None = None,
    ) -> tuple[str, str]:
        """One Ollama call. Returns ``(content, thinking)``, both stripped."""
        async with httpx.AsyncClient(transport=self.transport, timeout=300) as client:
            response = await client.post(
                "http://127.0.0.1:11434/api/chat",
                json={
                    "model": model,
                    "messages": [
                        *([{"role": "system", "content": system}] if system else []),
                        *(prior or []),
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
                    system="",
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
        # The scratchpad answer is prose. Shortening it costs a measured
        # 0.2-0.4 s with thinking off and is what makes it speakable.
        short, _ = await self._single_turn(
            f"{SHORTEN_PROMPT}{text[:SHORTEN_SOURCE_CHARS]}",
            model=model,
            system="",
            think=False,
            num_predict=SHORTEN_TOKENS,
        )
        return LocalAgentReply(text=short or text, model=model, steps=2)

    async def _chat(
        self,
        content: str,
        *,
        model: str,
        history: Sequence[Mapping[str, Any]] | None = None,
        operator_name: str = "",
    ) -> LocalAgentReply:
        """Hold a conversation in exactly one call: no tools, no frame, no loop.

        The twelve-step agent loop is the wrong shape for talking -- it pays a
        screenshot and a vision encode before it can even decline to use a
        tool, which is what made a greeting take twenty seconds.
        """
        prior = _conversation_turns(history)
        chat_system = with_operator(CHAT_SYSTEM, operator_name)
        text, _ = await self._single_turn(
            content, model=model, system=chat_system, think=False,
            num_predict=CHAT_TOKENS, prior=prior,
        )
        if not text:
            # MEASURED: qwen3-vl answers nothing at all with thinking disabled,
            # so every greeting fell through to the placeholder. A reply this
            # short is still fast with a bounded scratchpad.
            text, _ = await self._single_turn(
                content, model=model, system=chat_system, think=True,
                num_predict=CHAT_TOKENS, prior=prior,
            )
        return LocalAgentReply(text=text or "I'm here.", model=model, steps=1)

    async def _look(
        self, content: str, *, model: str, operator_name: str = ""
    ) -> LocalAgentReply:
        """Read the screen in one vision call: no tools, no loop, no browser."""
        message = await self._visual_message(content)
        async with httpx.AsyncClient(transport=self.transport, timeout=120) as client:
            response = await client.post(
                "http://127.0.0.1:11434/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": with_operator(LOOK_SYSTEM, operator_name)},
                        message,
                    ],
                    "stream": False,
                    "think": False,
                    "options": {"temperature": 0.2, "num_predict": LOOK_TOKENS},
                },
            )
            response.raise_for_status()
            text = strip_thinking(str(response.json().get("message", {}).get("content", "")))
        return LocalAgentReply(
            text=text or "I can see your screen but could not describe it.",
            model=model,
            steps=1,
        )

    async def _visual_message(
        self, content: str, *, region: tuple[int, int, int, int] | None = None
    ) -> dict[str, Any]:
        frame = await self.observer.capture(region=region) if region else await self.observer.capture()
        return {
            "role": "user",
            "content": content,
            "images": [base64.b64encode(frame).decode("ascii")],
        }


__all__ = [
    "CHAT_SYSTEM", "LOCAL_AGENT_SYSTEM", "LOOK_SYSTEM", "with_operator", "LocalCapabilityExceeded", "SHORTEN_PROMPT", "LocalAgentReply", "LocalDesktopAgent", "LocalToolbox",
    "MAX_AGENT_STEPS", "ScreenObserver", "TOOLS", "strip_thinking",
]
