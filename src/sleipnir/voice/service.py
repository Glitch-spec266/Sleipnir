"""Resident desktop agent/speech bridge; one packaged startup per app launch.

The private stdin/stdout pipe carries JSON lines. Preferences and encrypted
history remain owned by the existing agent boundary, and every request returns
its own envelope so a failed turn cannot kill the next conversation.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import sys
from typing import Any, BinaryIO, TextIO

from sleipnir.gui_agent import build_parser as agent_parser, handle_instruction
from sleipnir.gui_history import EncryptedHistory
from sleipnir.voice.local_agent import LocalDesktopAgent
from sleipnir.voice.synthesis import build_parser as speech_parser, synthesize
from sleipnir.voice.transcription import MAX_AUDIO_BYTES, build_parser as transcription_parser, transcribe_audio

MAX_REQUEST_BYTES = 18 * 1024 * 1024


async def dispatch(request: dict[str, Any], agent: LocalDesktopAgent) -> dict[str, Any]:
    arguments = request.get("arguments", [])
    text = request.get("text", "")
    if not isinstance(arguments, list) or len(arguments) > 128 or not all(
        isinstance(argument, str) for argument in arguments
    ):
        raise ValueError("invalid service arguments")
    if not isinstance(text, str):
        raise ValueError("service text must be a string")
    if request.get("entrypoint") == "transcribe":
        args = transcription_parser().parse_args(arguments)
        if len(text) > 4 * ((MAX_AUDIO_BYTES + 2) // 3):
            raise ValueError("recording exceeds the 12 MiB safety limit")
        audio = base64.b64decode(text, validate=True)
        transcript = await transcribe_audio(
            audio, mode=args.mode, mime_type=args.mime_type, model=args.model,
            gemini_key=os.environ.get(args.gemini_env), prompt=args.prompt,
        )
        return {"status": "complete", "text": transcript}
    if request.get("entrypoint") == "agent":
        args = agent_parser().parse_args(arguments)
        history = (
            EncryptedHistory(args.history, args.history_key)
            if args.history is not None and args.history_key is not None
            else None
        )
        return await handle_instruction(
            text,
            workspace=args.workspace,
            route=args.route,
            permission_mode=args.permission_mode,
            task_grant=args.task_grant,
            model=args.model,
            ambient_provider=args.ambient_provider,
            session_id=args.session_id,
            variable_names={
                "openrouter": args.openrouter_env,
                "gemini": args.gemini_env,
                "nvidia-nim": args.nvidia_env,
            },
            history=history,
            operator_name=args.operator_name,
            local_agent=agent,
        )
    if request.get("entrypoint") == "speak":
        args = speech_parser().parse_args(arguments)
        payload = await synthesize(
            text,
            provider=args.provider,
            preset=args.preset,
            openrouter_key=os.environ.get(args.openrouter_env),
            gemini_key=os.environ.get(args.gemini_env),
        )
        return {
            "status": "complete",
            "audio": {
                "data": base64.b64encode(payload.data).decode("ascii"),
                "mimeType": payload.mime_type,
            } if payload else None,
        }
    raise ValueError("unsupported service entrypoint")


async def serve(source: BinaryIO, target: TextIO) -> None:
    agent = LocalDesktopAgent()
    target.write('{"type":"ready"}\n')
    target.flush()
    while True:
        line = await asyncio.to_thread(source.readline, MAX_REQUEST_BYTES + 1)
        if not line:
            return
        if len(line) > MAX_REQUEST_BYTES:
            # A partial oversized line cannot be safely correlated with a turn.
            raise ValueError("service request exceeds the 18 MiB safety limit")
        identifier = None
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("service request must be an object")
            identifier = request.get("id")
            if type(identifier) is not int or identifier < 1:
                raise ValueError("invalid service request id")
            # Tool/provider diagnostics must never become protocol responses.
            with contextlib.redirect_stdout(sys.stderr):
                result = await dispatch(request, agent)
        except SystemExit:
            result = {"status": "error", "text": "invalid service command arguments"}
        except Exception as error:  # noqa: BLE001 - preserve the next turn
            result = {"status": "error", "text": str(error)}
        target.write(json.dumps({"id": identifier, "result": result}, separators=(",", ":")) + "\n")
        target.flush()


def main() -> int:
    asyncio.run(serve(sys.stdin.buffer, sys.stdout))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
