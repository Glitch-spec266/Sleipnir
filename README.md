# Sleipnir

A budget-aware agentic orchestrator. Takes one complex project prompt,
decomposes it into a task DAG, and dispatches each task to the cheapest model
tier that can do it — while keeping the expensive orchestrator model's context
flat and staying inside a 5-hour usage window.

The design serves one insight: **delegation only saves money if subtask output
never re-enters the orchestrator's context.** The plan lives on disk. The
orchestrator is re-invoked fresh each cycle with only a compact, size-bounded
manifest.

## Status: Phase 2 (executor) — awaiting review

| Phase | Scope | State |
|---|---|---|
| 1 | state schema + design | complete |
| 2 | executor + adapters (`claude`, `codex`, `openrouter`) | **complete, under review** |
| 3 | tier router | not started |
| 4 | budget governor | not started |
| 5 | CLI | not started |

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
tests/                       118 tests, including the executable form of the
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

Python 3.12+. Runtime dependency: `pydantic`. No agent frameworks.

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python "pydantic>=2.7" "pytest>=8"
.venv/bin/python -m pytest -q
```

## Security note

`CommandCheck` acceptance checks execute shell commands from `plan.json`. A plan
file is executable content: do not run one from a source you do not trust.
