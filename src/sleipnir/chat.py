"""Where a typed message goes.

Sleipnir is a harness, not a model.  This module is the whole of its opinion
about conversation: pick the recipient, hand over the text, hand back the
reply.

The recipient depends on whether the brain is awake, and that distinction is
the economics of the entire project in one branch.  Waking the reason tier to
answer "is it done yet?" costs a full expensive spawn and, worse, spends
context that the run needs later.  So while workers are building, a cheap model
answers from the bounded manifest — the same constant-size object the brain
itself is allowed to see, and nothing more.

No model name appears here.  ``claude`` is invoked without ``--model`` so the
authenticated account picks its own default, and the asleep-path model is
resolved from the operator's TOML policy, exactly as dispatch routing is.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path

from sleipnir.schema import Tier


class ChatError(RuntimeError):
    """The recipient could not be reached or did not answer usefully."""


@dataclass(frozen=True)
class Reply:
    text: str
    speaker: str
    session_id: str | None = None
    cost_usd: float | None = None


# ---------------------------------------------------------------------------
# The brain: the real Claude Code CLI
# ---------------------------------------------------------------------------


def claude_argv(
    session_id: str,
    *,
    resume: bool,
    executable: str = "claude",
    permission_mode: str = "acceptEdits",
    add_dirs: tuple[Path, ...] = (),
) -> list[str]:
    """Build the headless invocation.

    ``--session-id`` opens the conversation; every later turn uses ``--resume``
    against the same id.  Without that the console would be a series of
    strangers, each paying the ~30k-token spawn overhead to learn what the last
    one already knew.
    """
    argv = [executable, "-p", "--output-format", "json"]
    argv += ["--resume", session_id] if resume else ["--session-id", session_id]
    argv += ["--permission-mode", permission_mode]
    for directory in add_dirs:
        argv += ["--add-dir", str(directory)]
    return argv


async def ask_claude(
    prompt: str,
    session_id: str,
    *,
    resume: bool,
    timeout_s: float = 900.0,
    **argv_kwargs: object,
) -> Reply:
    """Send one turn to Claude Code and wait for the whole reply.

    The prompt goes over stdin, never argv: argv is world-readable in
    ``/proc``, and a pasted file would blow past ``ARG_MAX``.
    """
    argv = claude_argv(session_id, resume=resume, **argv_kwargs)  # type: ignore[arg-type]
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(prompt.encode("utf-8")), timeout=timeout_s
        )
    except TimeoutError as error:
        process.kill()
        await process.wait()
        raise ChatError(f"claude did not reply within {timeout_s:.0f}s") from error

    if process.returncode != 0:
        detail = stderr.decode("utf-8", "replace").strip()[:400]
        raise ChatError(f"claude exited {process.returncode}: {detail}")

    try:
        payload = json.loads(stdout.decode("utf-8", "replace"))
    except json.JSONDecodeError as error:
        raise ChatError("claude did not emit the JSON envelope it was asked for") from error

    text = payload.get("result") or payload.get("text") or ""
    if not isinstance(text, str):
        raise ChatError("claude reply had no textual result")
    return Reply(
        text=text,
        speaker="claude",
        session_id=payload.get("session_id") or session_id,
        cost_usd=payload.get("total_cost_usd"),
    )


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
    executed and never mutates the plan — plan changes go through
    ``revisions.apply_revision`` and its operator-review gate, unchanged.
    """
    for line in reversed(text.splitlines()):
        stripped = line.strip()
        if stripped.upper().startswith("QUEUE:"):
            instruction = stripped[6:].strip()
            return instruction or None
    return None


__all__ = [
    "ChatError",
    "Reply",
    "ROUTER_SYSTEM",
    "ask_claude",
    "ask_router",
    "claude_argv",
    "extract_queued_instruction",
    "router_model",
]
