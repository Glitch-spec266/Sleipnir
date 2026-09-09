"""Fast conversational relay for ambient voice responses."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import httpx

from sleipnir.voice.providers import VoiceProviderError
from sleipnir import chat

AMBIENT_SYSTEM = (
    "You are Sleipnir's concise ambient voice. Answer in at most four short "
    "sentences. Never claim an action was taken. If work is requested, say it "
    "needs the project lane and wait for escalation approval."
)


@dataclass(frozen=True, slots=True)
class AmbientReply:
    text: str
    provider: str
    model: str


class AmbientRelay:
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.transport = transport

    async def respond(
        self,
        prompt: str,
        *,
        provider: str,
        api_key: str,
        model: str | None = None,
        run_digest: str = "",
    ) -> AmbientReply:
        clean = " ".join(prompt.split())
        if not clean:
            raise ValueError("ambient prompt cannot be empty")
        context = run_digest[:32_000]
        user = f"RUN DIGEST:\n{context}\n\nOPERATOR:\n{clean}" if context else clean
        if provider == "gemini":
            return await self._gemini(user, api_key, model or "gemini-2.5-flash-lite")
        if provider == "openrouter":
            return await self._openai_shape(
                user,
                api_key,
                model or "openrouter/free",
                provider="openrouter",
                url="https://openrouter.ai/api/v1/chat/completions",
            )
        if provider == "nvidia-nim":
            return await self._openai_shape(
                user,
                api_key,
                model or "meta/llama-3.1-8b-instruct",
                provider="nvidia-nim",
                url="https://integrate.api.nvidia.com/v1/chat/completions",
            )
        raise VoiceProviderError(f"unknown ambient provider {provider!r}")

    async def _gemini(self, prompt: str, key: str, model: str) -> AmbientReply:
        async with httpx.AsyncClient(transport=self.transport, timeout=60) as client:
            response = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": key},
                json={
                    "systemInstruction": {"parts": [{"text": AMBIENT_SYSTEM}]},
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": 320, "temperature": 0.2},
                },
            )
        if response.status_code != 200:
            raise VoiceProviderError(f"Gemini ambient response returned HTTP {response.status_code}")
        try:
            text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as error:
            raise VoiceProviderError("Gemini ambient response contained no text") from error
        return AmbientReply(str(text).strip(), "gemini", model)

    async def _openai_shape(
        self,
        prompt: str,
        key: str,
        model: str,
        *,
        provider: str,
        url: str,
    ) -> AmbientReply:
        async with httpx.AsyncClient(transport=self.transport, timeout=60) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": AMBIENT_SYSTEM},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": 320,
                    "temperature": 0.2,
                },
            )
        if response.status_code != 200:
            raise VoiceProviderError(f"{provider} ambient response returned HTTP {response.status_code}")
        try:
            text = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise VoiceProviderError(f"{provider} ambient response contained no text") from error
        return AmbientReply(str(text).strip(), provider, model)


@dataclass(frozen=True, slots=True)
class WorkReply:
    text: str
    provider: str
    session_id: str


class WorkRelay:
    """Persistent Claude/Codex work sessions behind the desktop boundary."""

    def __init__(self, *, transport_factory: Callable[..., Any] = chat.transport_for) -> None:
        self.transport_factory = transport_factory
        self.sessions: dict[str, chat.ChatSession] = {}
        self.transports: dict[str, Any] = {}

    async def send(
        self,
        prompt: str,
        *,
        provider: str,
        workspace: Path,
        permission_mode: str = "ask",
        model: str | None = None,
        effort: str | None = None,
        session_id: str | None = None,
    ) -> WorkReply:
        if provider not in chat.PROVIDERS:
            raise ValueError(f"unsupported work provider {provider!r}")
        workspace = workspace.resolve()
        if not workspace.is_dir():
            raise ValueError(f"workspace does not exist: {workspace}")
        clean = prompt.strip()
        if not clean:
            raise ValueError("work prompt cannot be empty")
        posture = "bypassPermissions" if permission_mode == "always" else "acceptEdits"
        if provider not in self.sessions:
            session = chat.ChatSession(provider, **({"session_id": session_id} if session_id else {}))
            session.opened = session_id is not None
            self.sessions[provider] = session
        session = self.sessions[provider]
        transport = self.transports.get(provider)
        if transport is None:
            async def spawn(*argv: str, **kwargs: Any) -> Any:
                kwargs["cwd"] = str(workspace)
                return await asyncio.create_subprocess_exec(*argv, **kwargs)

            transport = self.transport_factory(
                session,
                permission_mode=posture,
                model=model,
                effort=effort,
                add_dirs=(workspace,),
                spawn=spawn,
            )
            self.transports[provider] = transport
        final = ""
        async for event in transport.turn(clean):
            if event.kind == "final":
                final = event.text
        if not final:
            raise VoiceProviderError(f"{provider} work session returned no final reply")
        return WorkReply(final, provider, session.session_id)

    async def close(self) -> None:
        for transport in self.transports.values():
            await transport.close()
        self.transports.clear()


__all__ = ["AMBIENT_SYSTEM", "AmbientRelay", "AmbientReply", "WorkRelay", "WorkReply"]
