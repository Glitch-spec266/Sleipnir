"""Adapter tests. Every adapter is driven end to end against a fake.

The Claude payload below is a *verbatim capture* from a real
`claude -p --output-format json` run (CLI 2.1.234), trimmed only of fields the
adapter ignores. Testing against remembered shapes is how you ship a parser
that reads the wrong field for a year.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from fakes import fake_spawner
from test_schema import make_task

from sleipnir.adapters.base import DispatchRequest
from sleipnir.adapters.claude import ClaudeAdapter
from sleipnir.adapters.codex import (
    CODEX_CLI_DEFAULT_MODEL,
    CodexAdapter,
    CodexInvocation,
)
from sleipnir.adapters.openrouter import (
    API_KEY_ENV,
    OpenRouterAdapter,
    materialize_file_blocks,
)
from sleipnir.artifacts import AttemptWorkspace
from sleipnir.schema import AttemptStatus, BillingMode, FailureKind, Tier


def run(coro):
    return asyncio.run(coro)


def request_for(tmp_path: Path, **kwargs) -> DispatchRequest:
    task = kwargs.pop("task", None) or make_task("t0001")
    return DispatchRequest(
        task=task,
        attempt=kwargs.pop("attempt", 1),
        tier_final=kwargs.pop("tier_final", Tier.CODE),
        model=kwargs.pop("model", "vendor/model-x"),
        prompt=kwargs.pop("prompt", "do the thing"),
        workspace=AttemptWorkspace(tmp_path, task.id, 1),
        timeout_s=kwargs.pop("timeout_s", 30.0),
        env=kwargs.pop("env", {}),
        grace_s=kwargs.pop("grace_s", 0.05),
        run_id=kwargs.pop("run_id", "run-test"),
    )


# ---------------------------------------------------------------------------
# Claude — verbatim captured payload
# ---------------------------------------------------------------------------

CLAUDE_PAYLOAD = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "stop_reason": "end_turn",
    "terminal_reason": "completed",
    "num_turns": 1,
    "duration_ms": 2280,
    "session_id": "3e657966-20e2-5cc1-b307-f9e771e89469",
    "total_cost_usd": 0.06145,
    "result": "OK",
    "permission_denials": [],
    "api_error_status": None,
    # Last message only — the trap.
    "usage": {
        "input_tokens": 10,
        "cache_creation_input_tokens": 30149,
        "cache_read_input_tokens": 0,
        "output_tokens": 38,
        "output_tokens_details": {"thinking_tokens": 32},
        "cache_creation": {
            "ephemeral_1h_input_tokens": 30149,
            "ephemeral_5m_input_tokens": 0,
        },
    },
    # Whole-dispatch aggregate — what the adapter must actually read.
    "modelUsage": {
        "claude-haiku-4-5-20251001": {
            "inputTokens": 907,
            "outputTokens": 49,
            "cacheReadInputTokens": 0,
            "cacheCreationInputTokens": 30149,
            "costUSD": 0.06145,
            "contextWindow": 200000,
        }
    },
}


def claude_adapter(payload=None, **spawn_kwargs) -> tuple[ClaudeAdapter, list]:
    calls: list = []
    stdout = json.dumps(payload if payload is not None else CLAUDE_PAYLOAD).encode()
    spawn_kwargs.setdefault("stdout", stdout)
    return ClaudeAdapter(spawn=fake_spawner(calls=calls, **spawn_kwargs)), calls


def test_claude_reads_model_usage_not_last_message_usage(tmp_path: Path):
    """The whole point: `usage.input_tokens` is 10, `modelUsage` is 907."""
    adapter, _ = claude_adapter()
    outcome = run(adapter.dispatch(request_for(tmp_path)))

    assert outcome.status is AttemptStatus.SUCCEEDED
    assert outcome.usage.input_tokens == 907, "must not read the last-message usage block"
    assert outcome.usage.output_tokens == 49
    assert outcome.usage.cache_write_1h_tokens == 30149
    assert outcome.usage.total_input_tokens == 907 + 30149


def test_claude_cost_is_authoritative_not_estimated(tmp_path: Path):
    adapter, _ = claude_adapter()
    outcome = run(adapter.dispatch(request_for(tmp_path)))
    assert outcome.reported_cost_usd == pytest.approx(0.06145)
    assert outcome.billing_mode is BillingMode.SUBSCRIPTION


def test_claude_sums_usage_across_fallback_models(tmp_path: Path):
    payload = dict(CLAUDE_PAYLOAD)
    payload["modelUsage"] = {
        "model-a": {"inputTokens": 100, "outputTokens": 10, "cacheCreationInputTokens": 5},
        "model-b": {"inputTokens": 200, "outputTokens": 90, "cacheCreationInputTokens": 7},
    }
    adapter, _ = claude_adapter(payload)
    outcome = run(adapter.dispatch(request_for(tmp_path)))
    assert outcome.usage.input_tokens == 300
    assert outcome.usage.output_tokens == 100
    # The model that produced the most output is the one that did the work.
    assert outcome.model_used == "model-b"


def test_claude_prompt_goes_over_stdin_not_argv(tmp_path: Path):
    """Prompts carry file contents; argv has a length limit and is world-readable."""
    adapter, calls = claude_adapter()
    secret_prompt = "prompt with sensitive context"
    run(adapter.dispatch(request_for(tmp_path, prompt=secret_prompt)))
    assert secret_prompt not in " ".join(calls[0]["argv"])


def test_claude_subprocess_does_not_inherit_unrelated_credentials(tmp_path: Path):
    adapter, calls = claude_adapter()
    env = {
        "PATH": "/usr/bin",
        "OPENROUTER_API_KEY": "or-secret",
        "GITHUB_TOKEN": "gh-secret",
        "SSH_AUTH_SOCK": "/tmp/agent.sock",
    }
    run(adapter.dispatch(request_for(tmp_path, env=env)))
    child_env = calls[0]["kwargs"]["env"]
    assert child_env["PATH"] == "/usr/bin"
    assert "OPENROUTER_API_KEY" not in child_env
    assert "GITHUB_TOKEN" not in child_env
    assert "SSH_AUTH_SOCK" not in child_env


def test_claude_argv_uses_verified_flags(tmp_path: Path):
    adapter, calls = claude_adapter()
    run(adapter.dispatch(request_for(tmp_path, model="claude-haiku-4-5-20251001")))
    argv = calls[0]["argv"]
    assert argv[0] == "claude"
    assert "-p" in argv
    assert argv[argv.index("--output-format") + 1] == "json"
    assert argv[argv.index("--model") + 1] == "claude-haiku-4-5-20251001"
    assert "--permission-mode" in argv


def test_claude_session_id_is_stable_within_a_run(tmp_path: Path):
    one = ClaudeAdapter._session_id(request_for(tmp_path, attempt=1, run_id="run-a"))
    same = ClaudeAdapter._session_id(request_for(tmp_path, attempt=1, run_id="run-a"))
    other = ClaudeAdapter._session_id(request_for(tmp_path, attempt=2, run_id="run-a"))
    assert one == same and one != other


def test_claude_session_id_differs_across_runs(tmp_path: Path):
    """Regression: seeding on (task, attempt) alone made every resume collide
    with 'Session ID ... is already in use' and burn a retry."""
    first = ClaudeAdapter._session_id(request_for(tmp_path, attempt=1, run_id="run-a"))
    resumed = ClaudeAdapter._session_id(request_for(tmp_path, attempt=1, run_id="run-b"))
    assert first != resumed


def test_executor_run_ids_are_unique(tmp_path: Path):
    """Two executors started in the same second must not share a run_id."""
    from sleipnir.executor import Executor, ExecutorConfig, StaticRouter
    from sleipnir.runlog import ResultLog
    from sleipnir.schema import Adapter as A
    from sleipnir.schema import Plan
    from datetime import UTC, datetime

    plan = Plan(
        plan_id="p", goal="g", created_at=datetime.now(UTC), tasks=[make_task("a")]
    )
    router = StaticRouter({t: (A.CLAUDE, "m") for t in Tier})

    def make():
        return Executor(
            plan,
            adapters={},
            router=router,
            log=ResultLog(tmp_path / "r.jsonl"),
            config=ExecutorConfig(run_root=tmp_path, env={}),
        )

    assert make().run_id != make().run_id


def test_claude_max_tokens_is_partial_not_failed(tmp_path: Path):
    payload = dict(CLAUDE_PAYLOAD, stop_reason="max_tokens")
    adapter, _ = claude_adapter(payload)
    outcome = run(adapter.dispatch(request_for(tmp_path)))
    assert outcome.status is AttemptStatus.PARTIAL
    assert outcome.failure_kind is FailureKind.TRUNCATED


def test_claude_permission_denials_do_not_downgrade_a_clean_run(tmp_path: Path):
    """Observed live: a subagent was denied one tool, worked around it, and
    produced correct output. Downgrading that to partial triggers a retry that
    doubles the cost for nothing. Disk state decides, not provider chatter."""
    payload = dict(CLAUDE_PAYLOAD, permission_denials=[{"tool": "Bash"}])
    adapter, _ = claude_adapter(payload)
    outcome = run(adapter.dispatch(request_for(tmp_path)))
    assert outcome.status is AttemptStatus.SUCCEEDED
    assert outcome.failure_kind is None
    # Still recorded, so it is diagnosable.
    assert outcome.provider_meta["permission_denials"] == [{"tool": "Bash"}]


def test_claude_denials_on_a_failed_run_are_tool_errors(tmp_path: Path):
    payload = dict(
        CLAUDE_PAYLOAD, is_error=True, subtype="error", permission_denials=[{"tool": "Bash"}]
    )
    adapter, _ = claude_adapter(payload)
    outcome = run(adapter.dispatch(request_for(tmp_path)))
    assert outcome.status is AttemptStatus.FAILED
    assert outcome.failure_kind is FailureKind.TOOL_ERROR


def test_claude_api_error_is_provider_error(tmp_path: Path):
    payload = dict(CLAUDE_PAYLOAD, api_error_status=529, is_error=True)
    adapter, _ = claude_adapter(payload)
    outcome = run(adapter.dispatch(request_for(tmp_path)))
    assert outcome.status is AttemptStatus.FAILED
    assert outcome.failure_kind is FailureKind.PROVIDER_ERROR


def test_claude_unparseable_output_keeps_the_bytes(tmp_path: Path):
    adapter, _ = claude_adapter(None, stdout=b"segfault: not json at all")
    outcome = run(adapter.dispatch(request_for(tmp_path)))
    assert outcome.failure_kind is FailureKind.PROVIDER_ERROR
    assert "segfault" in outcome.response_text


def test_claude_timeout(tmp_path: Path):
    adapter, _ = claude_adapter(None, never_exits=True)
    outcome = run(adapter.dispatch(request_for(tmp_path, timeout_s=0.05)))
    assert outcome.status is AttemptStatus.FAILED
    assert outcome.failure_kind is FailureKind.TIMEOUT


def test_claude_missing_executable_is_adapter_error(tmp_path: Path):
    async def boom(*argv, **kwargs):
        raise FileNotFoundError("claude")

    adapter = ClaudeAdapter(spawn=boom)
    outcome = run(adapter.dispatch(request_for(tmp_path)))
    assert outcome.failure_kind is FailureKind.ADAPTER_ERROR


def test_claude_writes_prompt_and_outcome_to_disk(tmp_path: Path):
    adapter, _ = claude_adapter()
    request = request_for(tmp_path, prompt="the exact prompt")
    run(adapter.dispatch(request))
    assert (request.workspace.dir / "prompt.txt").read_text() == "the exact prompt"
    assert json.loads((request.workspace.dir / "outcome.json").read_text())["exit_code"] == 0


def test_claude_preview_does_not_spawn(tmp_path: Path):
    calls: list = []
    adapter = ClaudeAdapter(spawn=fake_spawner(calls=calls))
    preview = adapter.preview(request_for(tmp_path))
    assert calls == []
    assert "claude" in preview.target
    assert preview.estimated_input_tokens > 0


# ---------------------------------------------------------------------------
# Codex — real CLI shape verified; invocation remains configurable
# ---------------------------------------------------------------------------


def test_codex_invocation_is_configurable(tmp_path: Path):
    invocation = CodexInvocation(
        executable="/opt/codex", subcommand=("exec",), model_flag="-m", json_flag="--json"
    )
    adapter = CodexAdapter(invocation=invocation, spawn=fake_spawner(stdout=b"{}"))
    calls: list = []
    adapter._runner = adapter._runner.__class__(spawn=fake_spawner(calls=calls, stdout=b"{}"))
    run(adapter.dispatch(request_for(tmp_path, model="gpt-x")))
    assert calls[0]["argv"][:4] == ["/opt/codex", "exec", "-m", "gpt-x"]


def test_codex_cli_default_omits_stale_model_override(tmp_path: Path):
    calls: list = []
    adapter = CodexAdapter(spawn=fake_spawner(calls=calls, stdout=b"{}"))
    run(adapter.dispatch(request_for(tmp_path, model=CODEX_CLI_DEFAULT_MODEL)))
    argv = calls[0]["argv"]
    assert "--model" not in argv
    assert CODEX_CLI_DEFAULT_MODEL not in argv


def test_codex_subprocess_does_not_inherit_unrelated_credentials(tmp_path: Path):
    calls: list = []
    adapter = CodexAdapter(spawn=fake_spawner(calls=calls, stdout=b"{}"))
    run(adapter.dispatch(request_for(tmp_path, env={
        "PATH": "/usr/bin",
        "OPENROUTER_API_KEY": "or-secret",
        "GITHUB_TOKEN": "gh-secret",
    })))
    child_env = calls[0]["kwargs"]["env"]
    assert child_env == {"PATH": "/usr/bin"}


def test_codex_finds_usage_at_an_unknown_nesting_depth(tmp_path: Path):
    events = [
        {"type": "start"},
        {"type": "done", "payload": {"response": {"usage": {
            "input_tokens": 1200, "output_tokens": 340,
            "output_tokens_details": {"reasoning_tokens": 100},
        }}}},
    ]
    stdout = ("\n".join(json.dumps(e) for e in events)).encode()
    adapter = CodexAdapter(spawn=fake_spawner(stdout=stdout))
    outcome = run(adapter.dispatch(request_for(tmp_path)))
    assert outcome.usage.input_tokens == 1200
    assert outcome.usage.output_tokens == 340
    assert outcome.usage.thinking_tokens == 100
    assert outcome.provider_meta["usage_found"] is True


def test_codex_accepts_openai_style_key_names(tmp_path: Path):
    stdout = json.dumps({"usage": {"prompt_tokens": 50, "completion_tokens": 7}}).encode()
    adapter = CodexAdapter(spawn=fake_spawner(stdout=stdout))
    outcome = run(adapter.dispatch(request_for(tmp_path)))
    assert outcome.usage.input_tokens == 50
    assert outcome.usage.output_tokens == 7


def test_codex_normalizes_observed_cli_usage_without_double_counting_cache(tmp_path: Path):
    stdout = json.dumps({
        "type": "turn.completed",
        "usage": {
            "input_tokens": 13_987,
            "cached_input_tokens": 9_984,
            "cache_write_input_tokens": 0,
            "output_tokens": 5,
            "reasoning_output_tokens": 2,
        },
    }).encode()
    adapter = CodexAdapter(spawn=fake_spawner(stdout=stdout))
    outcome = run(adapter.dispatch(request_for(tmp_path)))
    assert outcome.usage.input_tokens == 4_003
    assert outcome.usage.cache_read_tokens == 9_984
    assert outcome.usage.total_input_tokens == 13_987
    assert outcome.usage.thinking_tokens == 2


def test_codex_says_so_when_usage_is_unknown(tmp_path: Path):
    """A zeroed usage record would tell the governor the call was free."""
    adapter = CodexAdapter(spawn=fake_spawner(stdout=b'{"type":"message","text":"hi"}'))
    outcome = run(adapter.dispatch(request_for(tmp_path)))
    assert outcome.provider_meta["usage_found"] is False
    assert "unmeasured" in outcome.provider_meta["warning"]


def test_codex_preview_records_verified_cli_surface(tmp_path: Path):
    adapter = CodexAdapter()
    preview = adapter.preview(request_for(tmp_path))
    assert any("verified" in note for note in preview.notes)


def test_codex_default_invocation_is_writable_noninteractive_and_sandboxed(tmp_path: Path):
    calls: list = []
    adapter = CodexAdapter(spawn=fake_spawner(calls=calls, stdout=b"{}"))
    run(adapter.dispatch(request_for(tmp_path)))
    argv = calls[0]["argv"]
    assert "--approve-for-me" in argv
    assert "--sandbox" not in argv, "0.148.0 rejects --sandbox with --approve-for-me"
    assert "--skip-git-repo-check" in argv
    assert "--dangerously-bypass-approvals-and-sandbox" not in argv


# ---------------------------------------------------------------------------
# OpenRouter — httpx MockTransport, no network
# ---------------------------------------------------------------------------


def sse(*chunks: dict | str) -> bytes:
    lines = []
    for chunk in chunks:
        lines.append(f"data: {chunk if isinstance(chunk, str) else json.dumps(chunk)}")
        lines.append("")
    return "\n".join(lines).encode()


def openrouter(handler, **kwargs) -> OpenRouterAdapter:
    return OpenRouterAdapter(
        api_key="test-key",
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        **kwargs,
    )


def test_openrouter_streams_content_usage_and_cost(tmp_path: Path):
    body = sse(
        {"id": "gen-1", "model": "vendor/model-x", "choices": [{"delta": {"content": "Hel"}}]},
        {"choices": [{"delta": {"content": "lo"}, "finish_reason": "stop"}]},
        {"usage": {
            "prompt_tokens": 100, "completion_tokens": 20, "cost": 0.0012,
            "prompt_tokens_details": {"cached_tokens": 40},
        }},
        "[DONE]",
    )
    adapter = openrouter(lambda request: httpx.Response(200, content=body))
    req = request_for(tmp_path)
    outcome = run(adapter.dispatch(req))

    assert outcome.status is AttemptStatus.SUCCEEDED
    assert outcome.response_text == "Hello"
    assert outcome.reported_cost_usd == pytest.approx(0.0012)
    assert outcome.billing_mode is BillingMode.METERED
    # Cached tokens are a SUBSET of prompt_tokens; counting both doubles input.
    assert outcome.usage.input_tokens == 60
    assert outcome.usage.cache_read_tokens == 40
    # The raw stream landed on disk as it arrived.
    assert b"data:" in req.workspace.stdout_path.read_bytes()


def test_openrouter_materializes_file_blocks(tmp_path: Path):
    content = "```file:out.py\nprint('hi')\n```\n```file:summary.md\ndid the thing\n```"
    body = sse(
        {"choices": [{"delta": {"content": content}, "finish_reason": "stop"}]},
        {"usage": {"prompt_tokens": 10, "completion_tokens": 5}},
        "[DONE]",
    )
    adapter = openrouter(lambda request: httpx.Response(200, content=body))
    req = request_for(tmp_path)
    outcome = run(adapter.dispatch(req))
    assert sorted(outcome.provider_meta["files_written"]) == ["out.py", "summary.md"]
    assert (req.workspace.dir / "out.py").read_text().strip() == "print('hi')"


def test_openrouter_warns_when_no_file_blocks_are_emitted(tmp_path: Path):
    body = sse({"choices": [{"delta": {"content": "just prose"}, "finish_reason": "stop"}]}, "[DONE]")
    adapter = openrouter(lambda request: httpx.Response(200, content=body))
    outcome = run(adapter.dispatch(request_for(tmp_path)))
    assert "no file: blocks" in outcome.provider_meta["warning"]


def test_openrouter_refuses_an_unbounded_provider_stream(tmp_path: Path):
    body = sse({"choices": [{"delta": {"content": "x" * 500}}]}, "[DONE]")
    adapter = openrouter(
        lambda request: httpx.Response(200, content=body), max_response_bytes=128
    )
    outcome = run(adapter.dispatch(request_for(tmp_path)))
    assert outcome.status is AttemptStatus.FAILED
    assert outcome.failure_kind is FailureKind.PROVIDER_ERROR
    assert "exceeded 128 bytes" in outcome.stderr_tail


def test_openrouter_length_finish_is_truncated(tmp_path: Path):
    body = sse({"choices": [{"delta": {"content": "cut"}, "finish_reason": "length"}]}, "[DONE]")
    adapter = openrouter(lambda request: httpx.Response(200, content=body))
    outcome = run(adapter.dispatch(request_for(tmp_path)))
    assert outcome.status is AttemptStatus.PARTIAL
    assert outcome.failure_kind is FailureKind.TRUNCATED


def test_openrouter_rate_limit_is_retryable_but_bad_request_is_not(tmp_path: Path):
    rate_limited = openrouter(lambda request: httpx.Response(429, text="slow down"))
    assert run(rate_limited.dispatch(request_for(tmp_path))).failure_kind is FailureKind.PROVIDER_ERROR

    bad_request = openrouter(lambda request: httpx.Response(400, text="bad model"))
    assert run(bad_request.dispatch(request_for(tmp_path))).failure_kind is FailureKind.ADAPTER_ERROR


def test_openrouter_requires_an_api_key(tmp_path: Path, monkeypatch):
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    adapter = OpenRouterAdapter(client_factory=lambda: httpx.AsyncClient())
    outcome = run(adapter.dispatch(request_for(tmp_path)))
    assert outcome.failure_kind is FailureKind.ADAPTER_ERROR
    assert API_KEY_ENV in outcome.stderr_tail


def test_openrouter_preview_redacts_and_makes_no_request(tmp_path: Path, monkeypatch):
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    called = []
    adapter = OpenRouterAdapter(
        client_factory=lambda: called.append(1) or httpx.AsyncClient()
    )
    preview = adapter.preview(request_for(tmp_path))
    assert called == []
    assert "chat/completions" in preview.target
    assert any(API_KEY_ENV in note for note in preview.notes)


def test_openrouter_body_requests_usage_accounting(tmp_path: Path):
    adapter = OpenRouterAdapter(api_key="k")
    body = adapter.body(request_for(tmp_path), "prompt")
    assert body["usage"] == {"include": True}
    assert body["stream_options"] == {"include_usage": True}


def test_openrouter_prompt_suffix_lists_every_required_output(tmp_path: Path):
    request = request_for(tmp_path)
    suffix = OpenRouterAdapter.prompt_suffix(request)
    assert "file:" in suffix
    for expected in request.task.outputs.outputs:
        assert expected.path in suffix


# ---------------------------------------------------------------------------
# File-block materialisation is a trust boundary
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["../escape.py", "/etc/passwd", "../../.ssh/authorized_keys", "a/../../b.py"],
)
def test_file_blocks_cannot_escape_the_attempt_directory(tmp_path: Path, path: str):
    written = materialize_file_blocks(f"```file:{path}\npwned\n```", tmp_path)
    assert written == []
    assert not (tmp_path.parent / "escape.py").exists()


def test_file_blocks_write_nested_paths(tmp_path: Path):
    written = materialize_file_blocks("```file:pkg/mod.py\nx = 1\n```", tmp_path)
    assert written == ["pkg/mod.py"]
    assert (tmp_path / "pkg" / "mod.py").read_text() == "x = 1\n"
