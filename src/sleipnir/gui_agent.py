"""One-turn native-agent bridge used by the bundled desktop sidecar."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sleipnir.console import run_digest
from sleipnir.gui_history import EncryptedHistory
from sleipnir.voice.relay import AmbientRelay, WorkRelay
from sleipnir.voice.routing import RouteMode, choose_ambient_provider, route_utterance

MAX_INSTRUCTION_BYTES = 1_048_576


def _activated_provider(
    environment: Mapping[str, str], variable_names: Mapping[str, str]
) -> tuple[str, str] | None:
    conventional = {
        provider: environment.get(variable_names[provider], "")
        for provider in ("gemini", "openrouter", "nvidia-nim")
    }
    provider = choose_ambient_provider(
        {
            "GEMINI_API_KEY": conventional["gemini"],
            "OPENROUTER_API_KEY": conventional["openrouter"],
            "NVIDIA_API_KEY": conventional["nvidia-nim"],
        }
    )
    return (provider, conventional[provider]) if provider else None


async def handle_instruction(
    text: str,
    *,
    workspace: Path,
    route: str | None = None,
    permission_mode: str = "ask",
    model: str | None = None,
    session_id: str | None = None,
    environment: Mapping[str, str] | None = None,
    variable_names: Mapping[str, str] | None = None,
    ambient: AmbientRelay | None = None,
    work: WorkRelay | None = None,
    history: EncryptedHistory | None = None,
) -> dict[str, Any]:
    clean = text.strip()
    if not clean:
        raise ValueError("instruction cannot be empty")
    if len(clean.encode("utf-8")) > MAX_INSTRUCTION_BYTES:
        raise ValueError("instruction exceeds the 1 MiB safety limit")
    environment = os.environ if environment is None else environment
    variable_names = variable_names or {
        "gemini": "GEMINI_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "nvidia-nim": "NVIDIA_API_KEY",
    }
    decision = route_utterance(clean)
    if route is None and decision.mode is RouteMode.CONFIRM_ESCALATION:
        return {
            "status": "approval",
            "text": "",
            "route": decision.target,
            "rationale": decision.reason,
            "sessionId": session_id,
        }
    selected = route or "ambient"
    if history:
        history.append({"role": "operator", "text": clean, "route": selected})

    if selected == "ambient":
        activated = _activated_provider(environment, variable_names)
        if activated is None:
            raise RuntimeError("activate Gemini, OpenRouter, or NVIDIA NIM for ambient replies")
        provider, key = activated
        digest = run_digest(workspace) if (workspace / "plan.json").is_file() else ""
        reply = await (ambient or AmbientRelay()).respond(
            clean, provider=provider, api_key=key, model=model, run_digest=digest
        )
        result = {
            "status": "complete",
            "text": reply.text,
            "route": f"{reply.provider}/{reply.model}",
            "rationale": decision.reason,
            "sessionId": None,
        }
    elif selected in {"claude", "codex"}:
        reply = await (work or WorkRelay()).send(
            clean,
            provider=selected,
            workspace=workspace,
            permission_mode=permission_mode,
            model=model,
            session_id=session_id,
        )
        result = {
            "status": "complete",
            "text": reply.text,
            "route": reply.provider,
            "rationale": "Operator approved the capable work lane.",
            "sessionId": reply.session_id,
        }
    else:
        raise ValueError(f"unknown instruction route {selected!r}")
    if history:
        history.append({"role": "sleipnir", "text": result["text"], "route": result["route"]})
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sleipnir-desktop-agent")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--route", choices=["ambient", "claude", "codex"])
    parser.add_argument("--permission-mode", choices=["ask", "always"], default="ask")
    parser.add_argument("--model")
    parser.add_argument("--session-id")
    parser.add_argument("--history", type=Path)
    parser.add_argument("--history-key", type=Path)
    parser.add_argument("--openrouter-env", default="OPENROUTER_API_KEY")
    parser.add_argument("--gemini-env", default="GEMINI_API_KEY")
    parser.add_argument("--nvidia-env", default="NVIDIA_API_KEY")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    instruction = sys.stdin.buffer.read(MAX_INSTRUCTION_BYTES + 1)
    if len(instruction) > MAX_INSTRUCTION_BYTES:
        print(json.dumps({"status": "error", "text": "instruction exceeds the 1 MiB safety limit"}))
        return 2
    try:
        text = instruction.decode("utf-8")
        history = (
            EncryptedHistory(args.history, args.history_key)
            if args.history is not None and args.history_key is not None
            else None
        )
        result = asyncio.run(
            handle_instruction(
                text,
                workspace=args.workspace,
                route=args.route,
                permission_mode=args.permission_mode,
                model=args.model,
                session_id=args.session_id,
                variable_names={
                    "openrouter": args.openrouter_env,
                    "gemini": args.gemini_env,
                    "nvidia-nim": args.nvidia_env,
                },
                history=history,
            )
        )
    except Exception as error:  # noqa: BLE001 - native boundary returns a clean envelope
        print(json.dumps({"status": "error", "text": str(error), "route": args.route or "auto"}))
        return 2
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["MAX_INSTRUCTION_BYTES", "handle_instruction", "main"]
