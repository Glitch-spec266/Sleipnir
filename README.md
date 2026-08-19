# Sleipnir

A budget-aware agentic orchestrator. Takes one complex project prompt,
decomposes it into a task DAG, and dispatches each task to the cheapest model
tier that can do it — while keeping the expensive orchestrator model's context
flat and staying inside a 5-hour usage window.

The design serves one insight: **delegation only saves money if subtask output
never re-enters the orchestrator's context.** The plan lives on disk. The
orchestrator is re-invoked fresh each cycle with only a compact, size-bounded
manifest.

## Status: Phases 1–9 complete

| Phase | Scope | State |
|---|---|---|
| 1 | state schema + design | complete |
| 2 | executor + adapters (`claude`, `codex`, `openrouter`) | complete |
| 3 | tier router | complete |
| 4 | budget governor | complete |
| 5 | CLI | complete |
| 6 | end-to-end resume gate, review, pentest | complete |
| 7 | dependency-free live TUI + sparse-control console | complete |
| 8 | interactive console + audited host/browser/credential control | complete |
| 9 | phase gate + automatic escalation before scarce-brain wakeup | complete |

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
src/sleipnir/pricing.py      live OpenRouter catalogue, TTL cache
src/sleipnir/config.py       TOML backend + per-tier policy
src/sleipnir/router.py       tier -> model, with full routing rationale
src/sleipnir/budget.py       5-hour window accounting and downshift
src/sleipnir/planner.py      prompt -> validated task DAG
src/sleipnir/revisions.py    typed, audited mid-run plan changes
src/sleipnir/orchestrator.py sparse bounded-context brain decisions
src/sleipnir/gate.py         constant-size phase verdict + finite escalation
src/sleipnir/tui.py          bounded DAG / routing / budget terminal dashboard
src/sleipnir/console.py      guarded chat + `/project` multi-model front door
src/sleipnir/chat.py         Claude session transport + tool-free fast-lane gate
src/sleipnir/cli.py          plan / run / status / resume / explain / tui / orchestrate
tests/                       399 tests, including the executable form of the
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

Python 3.12+. Runtime dependencies: `pydantic` and `httpx`. No agent frameworks.

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python "pydantic>=2.7" "httpx>=0.27" "pytest>=8"
.venv/bin/python -m pytest -q
```

## Terminal dashboard

`sleipnir tui` prints a read-only snapshot and cannot dispatch anything.
`sleipnir tui --watch` follows a run, and `sleipnir tui --run` executes or
resumes it under the run-directory lock while displaying live DAG, route and
budget state. The dashboard adds no runtime dependency and never displays
subagent summaries or artifact content.
`sleipnir tui --orchestrate` adds the bounded sparse-brain loop to that same
console; plan revisions reload live and review-required proposals are surfaced.
Read-only/watch modes are catalogue-free and offline; their usage line derives
metered dollars, Claude-window tokens, and Codex tokens directly from the log.
All untrusted display values are stripped of terminal control characters.

## Interactive console

Bare `sleipnir` opens the full-screen console. Ordinary messages first receive
a tool-free Haiku capability check. The check process is launched with no tools,
so it cannot touch the desktop while deciding; only an exact affirmative verdict
lets a second Haiku turn act. Declines and malformed verdicts go to Sonnet. A
failed action is never automatically replayed because it may already have had a
side effect. `--fast-model` and `--model` override the two aliases, and an empty
`--fast-model` disables the gate.

`/project <goal>` is the explicit boundary for larger work. It bypasses ordinary
chat and runs the existing `plan` then `orchestrate` commands, so decomposition,
tier routing, budgets, acceptance checks, phase-gate escalation, and review gates
remain the same pipeline as batch operation.

The console enables terminal bracketed-paste mode, so Ctrl+Shift+V inserts
multiline text atomically instead of leaking CSI markers or submitting halfway
through. Clipboard images cannot travel through a text PTY; when the terminal
forwards the paste event, Sleipnir reads the image MIME with `wl-paste`, saves it
as a private `0600` attachment, and gives Claude the path. The agent-facing
`sleipnir computer copy` and `sleipnir computer paste` commands emit real
Ctrl+Shift+C/V chords, preserving either text or image MIME in the focused app.

The splash uses a letter-free eight-legged horse emblem; the frame title carries
the product name, so the mark itself is a logo rather than another nameplate.

## Sparse brain control

`sleipnir orchestrate` runs the DAG normally and spends no extra Claude call
when workers succeed. At a terminal impasse it invokes the configured
reason-tier brain with only the bounded manifest and up to four urgent task
specs (24k characters total). The brain may stop, defer, or propose a typed
revision; Sleipnir validates the full DAG and computes the revision blast radius
locally before persisting anything.

Semantic task/edge proposals require explicit operator review through
`sleipnir apply-revision`; only routing-only retargets auto-apply by default.
Applied proposal files remain as audit artifacts but no longer inflate the
TUI's pending-review badge.
When a semantic revision is approved, superseded tasks and stale descendants
are rerun in dependency order rather than being mistaken for completed work.

The shipped example policy keeps Claude first for `reason`, puts the Codex
subscription first for bulk `code`, and uses OpenRouter first for cheap
`mechanical`/`extract` work. This reserves Claude's tighter window for planning
and control while distributing worker usage across the other two backends.
Codex subscription usage is tracked in its own quota pool. The example's
`@cli-default` sentinel lets the authenticated CLI choose its currently
supported account default; operators can still pin a concrete model id.
Sparse brain calls append their own durable usage/cost record, so the TUI and
budget history include Claude control spend as well as worker spend.

## Security note

`CommandCheck` acceptance checks execute shell commands from `plan.json`. A plan
file is executable content: do not run one from a source you do not trust.
