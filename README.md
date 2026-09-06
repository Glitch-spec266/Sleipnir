# Sleipnir

<p align="center">
  <img src="assets/sleipnir-mark.svg" width="600" alt="Sleipnir — eight-lane orchestration">
</p>

A budget-aware agentic orchestrator. Takes one complex project prompt,
decomposes it into a task DAG, and dispatches each task to the cheapest model
tier that can do it — while keeping the expensive orchestrator model's context
flat and staying inside a 5-hour usage window.

The design serves one insight: **delegation only saves money if subtask output
never re-enters the orchestrator's context.** The plan lives on disk. The
orchestrator is re-invoked fresh each cycle with only a compact, size-bounded
manifest.

## Status: Phases 1–14 complete; Phase 15 in progress

| Phase | Scope | State |
|---|---|---|
| 1 | state schema + design | complete |
| 2 | executor + adapters (`claude`, `codex`, `openrouter`) | complete |
| 3 | tier router | complete |
| 4 | budget governor | complete |
| 5 | CLI | complete |
| 6 | end-to-end resume gate, review, pentest | complete |
| 7 | dependency-free live TUI + sparse-control console | complete |

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
src/sleipnir/tui.py          bounded DAG / routing / budget terminal dashboard
src/sleipnir/cli.py          plan / run / status / resume / explain / tui / orchestrate
src/sleipnir/platform/       the one seam between Sleipnir and the OS:
                             POSIX and Windows backends behind one API
src/sleipnir/capabilities/computer/
                             desktop control: ydotool on Linux, SendInput
                             and GDI on Windows, audited in one place
tests/                       436 tests, including the executable form of the
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

On Windows the same three commands, with the interpreter where Windows puts it:

```powershell
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe "pydantic>=2.7" "httpx>=0.27" "pytest>=8"
.venv\Scripts\python.exe -m pytest -q
```

## Windows

Linux and Windows are both first-class. Every OS call — process trees, file
locking, console raw mode, shell selection, input injection, screen capture —
goes through `src/sleipnir/platform/`, which picks a backend once at import;
no other module branches on the platform. Nothing extra is installed and
nothing needs administrator rights: input is `user32.SendInput`, capture is
GDI plus a stdlib PNG encoder, and process containment is a job object.

Four differences are real and worth knowing before you rely on them:

- **Input injection is user-mode, not kernel-level.** ydotool writes to
  `/dev/uinput`, below the input stack. `SendInput` sits above it, so UIPI
  blocks it from reaching windows owned by an elevated process, the UAC secure
  desktop is unreachable by design, and software that checks `LLMHF_INJECTED`
  (anti-cheat, DRM, some banking apps) can tell the input is synthetic.
  `sleipnir doctor` reports whether this process is elevated for that reason.
- **A POSIX shell is a soft prerequisite.** `CommandCheck` commands in a
  `plan.json` are written POSIX-style, so Sleipnir prefers `sh` — from
  `$SLEIPNIR_SHELL`, then `PATH`, then a Git for Windows install — and falls
  back to `cmd.exe` with a loud `doctor` warning. `sleipnir setup` offers
  `winget install --id Git.Git` when none is found.
- **Codex's worker sandbox is weaker.** Its `workspace-write` mode is kernel-
  enforced on Linux and macOS; on Windows it is closer to an intention than a
  guarantee. Sleipnir cannot fix that, and says so rather than implying a
  containment it is not getting.
- **Parent-death containment is *stronger*.** `PR_SET_PDEATHSIG` sends a
  signal a provider CLI can trap; a job object with `KILL_ON_JOB_CLOSE` is
  unconditional and covers the whole descendant tree, so a hard-killed
  Sleipnir cannot leave a spending orphan behind.

State lives in `~/.sleipnir/` and `~/.cache/sleipnir/` on both platforms —
one location is easier to explain, and moving it would orphan existing runs.

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
