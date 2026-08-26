"""OpenRouter adapter — plain HTTP, no SDK.

Auth is a bearer API key read from the environment. This is the one metered
path: unlike the CLI adapters it spends dollars rather than subscription window
quota, and it is the only adapter whose cost may need a price snapshot.

Unlike the CLI adapters, an HTTP model has no filesystem. It cannot write the
files a task's OutputContract demands. So this adapter appends a file-block
protocol to the prompt and materialises the blocks the model emits — see
:meth:`OpenRouterAdapter.prompt_suffix` and :func:`materialize_file_blocks`.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from sleipnir.adapters.base import (
    BaseAdapter,
    DispatchOutcome,
    DispatchPreview,
    DispatchRequest,
)
from sleipnir.artifacts import OUTCOME_FILENAME, SUMMARY_FILENAME
from sleipnir.schema import (
    Adapter,
    AttemptStatus,
    BillingMode,
    FailureKind,
    TokenUsage,
    estimate_tokens,
)

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
API_KEY_ENV = "OPENROUTER_API_KEY"
DEFAULT_MAX_RESPONSE_BYTES = 64 * 1024 * 1024

#: ```file:relative/path.py   ... ```
_FILE_BLOCK = re.compile(
    r"^[ \t]*```[ \t]*file:[ \t]*(?P<path>[^\n`]+?)[ \t]*\n(?P<body>.*?)^[ \t]*```[ \t]*$",
    re.MULTILINE | re.DOTALL,
)

ClientFactory = Callable[[], httpx.AsyncClient]


class _HttpFailure(Exception):
    """An HTTP error status, carried out of the streaming path.

    Streaming used to raise httpx.HTTPStatusError, which the generic HTTPError
    handler flattened to PROVIDER_ERROR — so a permanent 400 was treated as
    retryable and burned the whole retry ladder. Status classification now has
    exactly one home: :meth:`OpenRouterAdapter._classify_status`.
    """

    def __init__(self, status_code: int, text: str) -> None:
        super().__init__(f"{status_code}: {text[:200]}")
        self.status_code = status_code
        self.text = text


class _ResponseTooLarge(Exception):
    """A provider response exceeded the operator-independent safety ceiling."""


class OpenRouterAdapter(BaseAdapter):
    name = Adapter.OPENROUTER

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str | None = None,
        client_factory: ClientFactory | None = None,
        referer: str = "https://github.com/sleipnir",
        title: str = "Sleipnir",
        stream: bool = True,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client_factory = client_factory
        self.referer = referer
        self.title = title
        self.stream = stream
        if max_response_bytes < 1:
            raise ValueError("max_response_bytes must be positive")
        self.max_response_bytes = max_response_bytes

    @property
    def api_key(self) -> str | None:
        return self._api_key or os.environ.get(API_KEY_ENV)

    # -- prompt -------------------------------------------------------------

    @staticmethod
    def prompt_suffix(request: DispatchRequest) -> str:
        """Give a filesystem-less model a way to produce files.

        Without this the model returns prose, every declared output is missing,
        and every task looks like a partial failure for reasons that have
        nothing to do with the model's competence.
        """
        paths = "\n".join(f"- {out.path}" for out in request.task.outputs.outputs)
        return (
            "\n\n# Output protocol\n"
            "You cannot write files directly. Emit each required file as a fenced "
            "block whose info string is `file:<path>`, exactly like this:\n\n"
            "```file:example.py\n<file contents>\n```\n\n"
            f"Emit one block per file:\n{paths}\n"
            f"- {SUMMARY_FILENAME}\n"
            "Emit nothing outside these blocks."
        )

    # -- dispatch -----------------------------------------------------------

    async def dispatch(self, request: DispatchRequest) -> DispatchOutcome:
        workspace = request.workspace
        workspace.prepare()
        prompt = request.prompt + self.prompt_suffix(request)
        workspace.write_text("prompt.txt", prompt)

        if not self.api_key:
            return DispatchOutcome(
                status=AttemptStatus.FAILED,
                failure_kind=FailureKind.ADAPTER_ERROR,
                billing_mode=BillingMode.METERED,
                stderr_tail=f"{API_KEY_ENV} is not set",
            )

        try:
            async with asyncio.timeout(request.timeout_s):
                return await self._call(request, prompt)
        except TimeoutError:
            return DispatchOutcome(
                status=AttemptStatus.FAILED,
                failure_kind=FailureKind.TIMEOUT,
                billing_mode=BillingMode.METERED,
                stderr_tail=f"exceeded {request.timeout_s}s",
            )
        except asyncio.CancelledError:
            raise
        except _HttpFailure as exc:
            return self._classify_status(exc.status_code, exc.text)
        except _ResponseTooLarge as exc:
            return DispatchOutcome(
                status=AttemptStatus.FAILED,
                failure_kind=FailureKind.PROVIDER_ERROR,
                billing_mode=BillingMode.METERED,
                stderr_tail=str(exc),
            )
        except httpx.HTTPError as exc:
            return DispatchOutcome(
                status=AttemptStatus.FAILED,
                failure_kind=FailureKind.PROVIDER_ERROR,
                billing_mode=BillingMode.METERED,
                stderr_tail=f"{type(exc).__name__}: {exc}",
            )

    def _build_client(self) -> httpx.AsyncClient:
        if self._client_factory is not None:
            return self._client_factory()
        return httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=None))

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": self.referer,
            "X-Title": self.title,
            "Content-Type": "application/json",
        }

    def body(self, request: DispatchRequest, prompt: str) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": request.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": self.stream,
            # Ask for accounting both ways: OpenRouter's own `usage.include`
            # returns a real cost, and the OpenAI-compatible `stream_options`
            # is what makes usage appear in the final streamed chunk.
            "usage": {"include": True},
        }
        if self.stream:
            body["stream_options"] = {"include_usage": True}
        return body

    async def _call(self, request: DispatchRequest, prompt: str) -> DispatchOutcome:
        workspace = request.workspace
        url = f"{self.base_url}/chat/completions"
        body = self.body(request, prompt)

        content = ""
        payload: dict[str, Any] = {}
        client = self._build_client()
        try:
            if self.stream:
                content, payload = await self._stream(client, url, body, workspace.stdout_path)
            else:
                response = await client.post(url, headers=self._headers(), json=body)
                if len(response.content) > self.max_response_bytes:
                    raise _ResponseTooLarge(
                        f"provider response exceeded {self.max_response_bytes:,} bytes"
                    )
                workspace.stdout_path.write_bytes(response.content)
                if response.status_code >= 400:
                    return self._http_error(response)
                payload = response.json()
                content = self._content_of(payload)
        finally:
            await client.aclose()

        outcome = DispatchOutcome(
            status=AttemptStatus.SUCCEEDED,
            billing_mode=BillingMode.METERED,
            usage=self._usage_of(payload),
            model_used=payload.get("model") or request.model,
            response_text=content,
            exit_code=0,
        )

        cost = (payload.get("usage") or {}).get("cost")
        if isinstance(cost, int | float):
            outcome.reported_cost_usd = float(cost)

        written = materialize_file_blocks(content, workspace.dir)
        outcome.provider_meta = {
            "id": payload.get("id"),
            "finish_reason": self._finish_reason(payload),
            "files_written": written,
            "native_usage": payload.get("usage"),
        }

        if self._finish_reason(payload) == "length":
            outcome.status = AttemptStatus.PARTIAL
            outcome.failure_kind = FailureKind.TRUNCATED
        elif not written:
            # The model answered but emitted no file blocks, so nothing the
            # task promised exists. Better named now than diagnosed later as a
            # mysteriously empty artifact directory.
            outcome.provider_meta["warning"] = "response contained no file: blocks"

        workspace.write_json(
            OUTCOME_FILENAME,
            {
                "url": url,
                "model": request.model,
                "stream": self.stream,
                "provider": outcome.provider_meta,
            },
        )
        return outcome

    async def _stream(
        self,
        client: httpx.AsyncClient,
        url: str,
        body: dict[str, Any],
        stdout_path: Path,
    ) -> tuple[str, dict[str, Any]]:
        """Consume the SSE stream, writing every raw line to disk as it lands.

        Streaming to disk is not decoration: it is what makes a killed or timed
        out dispatch still leave usable evidence of how far the model got.
        """
        parts: list[str] = []
        payload: dict[str, Any] = {}
        wire_bytes = 0
        stdout_path.parent.mkdir(parents=True, exist_ok=True)

        with stdout_path.open("wb") as sink:
            async with client.stream(
                "POST", url, headers=self._headers(), json=body
            ) as response:
                if response.status_code >= 400:
                    raw_parts: list[bytes] = []
                    async for chunk in response.aiter_bytes():
                        wire_bytes += len(chunk)
                        if wire_bytes > self.max_response_bytes:
                            raise _ResponseTooLarge(
                                f"provider error response exceeded {self.max_response_bytes:,} bytes"
                            )
                        raw_parts.append(chunk)
                    raw = b"".join(raw_parts)
                    text = raw.decode("utf-8", errors="replace")
                    sink.write(raw)
                    sink.flush()
                    raise _HttpFailure(response.status_code, text)
                pending = bytearray()

                def consume(raw_line: bytes) -> None:
                    nonlocal payload
                    line = raw_line.rstrip(b"\r").decode("utf-8", errors="replace")
                    if not line.startswith("data:"):
                        return
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        return
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        return
                    for choice in chunk.get("choices") or []:
                        delta = (choice.get("delta") or {}).get("content")
                        if delta:
                            parts.append(delta)
                        if choice.get("finish_reason"):
                            payload.setdefault("choices", [{}])[0]["finish_reason"] = choice[
                                "finish_reason"
                            ]
                    if chunk.get("usage"):
                        payload["usage"] = chunk["usage"]
                    payload.setdefault("id", chunk.get("id"))
                    payload.setdefault("model", chunk.get("model"))

                async for chunk_bytes in response.aiter_bytes():
                    wire_bytes += len(chunk_bytes)
                    if wire_bytes > self.max_response_bytes:
                        raise _ResponseTooLarge(
                            f"provider stream exceeded {self.max_response_bytes:,} bytes"
                        )
                    sink.write(chunk_bytes)
                    pending.extend(chunk_bytes)
                    while (newline := pending.find(b"\n")) >= 0:
                        consume(bytes(pending[:newline]))
                        del pending[: newline + 1]
                if pending:
                    consume(bytes(pending))
        return "".join(parts), payload

    def _http_error(self, response: httpx.Response) -> DispatchOutcome:
        return self._classify_status(response.status_code, response.text)

    @staticmethod
    def _classify_status(status_code: int, text: str) -> DispatchOutcome:
        """The single place an HTTP status becomes a FailureKind.

        The distinction is whether retrying the identical request could ever
        work: 429 and 5xx are transient (PROVIDER_ERROR, retried), while a 4xx
        means the request itself is wrong (ADAPTER_ERROR, never retried at the
        same tier — retrying it just spends the ladder on a certainty).
        """
        transient = status_code >= 500 or status_code in (408, 409, 429)
        return DispatchOutcome(
            status=AttemptStatus.FAILED,
            failure_kind=FailureKind.PROVIDER_ERROR if transient else FailureKind.ADAPTER_ERROR,
            billing_mode=BillingMode.METERED,
            exit_code=status_code,
            stderr_tail=text[:2_000],
        )

    @staticmethod
    def _content_of(payload: dict[str, Any]) -> str:
        choices = payload.get("choices") or []
        if not choices:
            return ""
        return (choices[0].get("message") or {}).get("content") or ""

    @staticmethod
    def _finish_reason(payload: dict[str, Any]) -> str | None:
        choices = payload.get("choices") or []
        return choices[0].get("finish_reason") if choices else None

    @staticmethod
    def _usage_of(payload: dict[str, Any]) -> TokenUsage:
        usage = payload.get("usage") or {}
        prompt_details = usage.get("prompt_tokens_details") or {}
        completion_details = usage.get("completion_tokens_details") or {}
        raw_server_tools = usage.get("server_tool_use")
        server_tool_use = {
            name: count
            for name, count in (raw_server_tools.items() if isinstance(raw_server_tools, dict) else [])
            if isinstance(name, str)
            and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name)
            and type(count) is int
            and count >= 0
        }
        # Provider payload is untrusted. Keep the same bounded representation
        # used by TokenUsage rather than letting a malformed response make the
        # durable result log arbitrarily large.
        server_tool_use = dict(list(server_tool_use.items())[:16])
        cached = int(prompt_details.get("cached_tokens") or 0)
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or 0)
        return TokenUsage(
            # OpenAI-compatible APIs report cached tokens as a *subset* of
            # prompt_tokens, so they are subtracted out rather than added —
            # counting both would double the input on every cached call.
            input_tokens=max(0, prompt_tokens - cached),
            cache_read_tokens=cached,
            output_tokens=output_tokens,
            thinking_tokens=min(
                int(completion_details.get("reasoning_tokens") or 0), output_tokens
            ),
            server_tool_use=server_tool_use,
        )

    # -- dry run ------------------------------------------------------------

    def preview(self, request: DispatchRequest) -> DispatchPreview:
        prompt = request.prompt + self.prompt_suffix(request)
        notes = ["metered: spends dollars, not subscription window"]
        if not self.api_key:
            notes.append(f"{API_KEY_ENV} is NOT set — this dispatch would fail")
        return DispatchPreview(
            task_id=request.task.id,
            attempt=request.attempt,
            adapter=self.name,
            tier_final=request.tier_final,
            model=request.model,
            target=f"POST {self.base_url}/chat/completions",
            prompt_bytes=len(prompt.encode()),
            estimated_input_tokens=estimate_tokens(prompt),
            timeout_s=request.timeout_s,
            workspace=request.workspace.rel_dir,
            notes=notes,
        )


def materialize_file_blocks(content: str, target_dir: Path) -> list[str]:
    """Write ```file:<path> blocks into ``target_dir``.

    Paths are confined to the attempt directory: an absolute path or one
    escaping upward is skipped rather than honoured. A model that emits
    ``file:../../.ssh/authorized_keys`` is not a scenario worth trusting.
    """
    written: list[str] = []
    resolved_root = target_dir.resolve()
    for match in _FILE_BLOCK.finditer(content):
        raw_path = match.group("path").strip()
        if not raw_path or raw_path.startswith("/") or ".." in Path(raw_path).parts:
            continue
        destination = (target_dir / raw_path).resolve()
        if not destination.is_relative_to(resolved_root):
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(match.group("body"), encoding="utf-8")
        written.append(raw_path)
    return written


__all__ = [
    "API_KEY_ENV", "DEFAULT_BASE_URL", "DEFAULT_MAX_RESPONSE_BYTES",
    "OpenRouterAdapter", "materialize_file_blocks",
]
