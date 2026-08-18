# Sleipnir

A budget-aware agentic orchestrator. Takes one complex project prompt,
decomposes it into a task DAG, and dispatches each task to the cheapest model
tier that can do it — while keeping the expensive orchestrator model's context
flat and staying inside a 5-hour usage window.

The design serves one insight: **delegation only saves money if subtask output
never re-enters the orchestrator's context.** The plan lives on disk. The
orchestrator is re-invoked fresh each cycle with only a compact, size-bounded
manifest.

## Status: Phase 4 (budget governor) complete

Phase numbers here are the *engineering* sequence used throughout `DESIGN.md`,
the module docstrings and the tests. `project.md` counts *workflow* phases and is
offset by one, because its Phase 1 is a requirements round rather than code.

| Phase | Scope | State |
|---|---|---|
| 1 | state schema + design | complete |
| 2 | executor + adapters (`claude`, `codex`, `openrouter`) | complete |
| 3 | tier router + live pricing | **complete** |
| 4 | budget governor + usage parser | **complete** |
| 5 | planner + run loop | not started |
| 6 | CLI | not started |

`project.md` is the live state board; `overview.md` is the plain-language
architecture guide.

Read [`DESIGN.md`](DESIGN.md) for the tradeoffs, the manifest size math, and the
open decisions.

## What exists

```
src/sleipnir/schema.py       pydantic models for plan.json, results.jsonl,
                             revisions.jsonl, and the derived Manifest
src/sleipnir/projection.py   pure fold of results over plan -> task status,
                             and the bounded manifest projection
src/sleipnir/executor.py     readiness, concurrency cap, cancellation, dry run
src/sleipnir/adapters/       claude (`claude -p`), codex (`codex exec`),
                             openrouter (plain HTTP)
src/sleipnir/process.py      async subprocess: streaming, timeout, tree kill
src/sleipnir/context.py      InputContract -> the exact subagent prompt
src/sleipnir/artifacts.py    attempt workspaces and output collection
src/sleipnir/checks.py       acceptance checks
src/sleipnir/runlog.py       append-only results.jsonl, fsync per record
src/sleipnir/pricing.py      live OpenRouter price fetch, cached to a disk
                             snapshot; never populated from memory
src/sleipnir/router.py       tier -> concrete model, scoring per-dispatch fixed
                             cost as a first-class term
src/sleipnir/usage.py        defensive parser for Claude Code's own usage
                             records; dedupes, and refuses to guess
src/sleipnir/governor.py     the only component allowed to refuse work
tests/                       206 tests, including the executable form of the
                             manifest size bound
```

Provider auth is never reimplemented. The `claude` and `codex` adapters shell
out to the official CLIs and inherit whatever credentials those hold;
`openrouter` reads a bearer key from `OPENROUTER_API_KEY`. No adapter performs
an OAuth flow.

## The property everything else rests on

The orchestrator's per-cycle context does not grow with the size of the plan:

| tasks | manifest tokens |
|---:|---:|
| 60 | 2,689 |
| 600 | 2,696 |
| 10,000 | 2,706 |

`test_manifest_size_is_constant_in_task_count` fails if a change reintroduces
growth.

## Development

Python 3.12+. Runtime dependencies: `pydantic`, `httpx`. No agent frameworks.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install "pydantic>=2.7" "httpx>=0.27" "pytest>=8"
.venv/bin/python -m pytest -q
```

`uv` works too if you have it; it is not installed on the development machine.

The router needs prices. They are fetched from
`https://openrouter.ai/api/v1/models`, which requires no API key, and cached to
`.sleipnir-cache/prices.json`. *Dispatching* to OpenRouter does need
`OPENROUTER_API_KEY` in the environment — including for its free models.

## Security note

`CommandCheck` acceptance checks execute shell commands from `plan.json`. A plan
file is executable content: do not run one from a source you do not trust.
