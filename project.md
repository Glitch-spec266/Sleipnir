# Sleipnir — Project State

_Started: 2026-08-18 · Last checkpoint: 2026-08-19, sparse control + live Codex gate_

## Goal

A budget-aware agentic orchestrator. It takes one complex project prompt,
decomposes it into a task DAG, and dispatches each task to the cheapest model
tier that can do it — while keeping the expensive orchestrator model's context
flat and staying inside a 5-hour usage window.

"Done" means: `sleipnir run "<a real project prompt>"` plans the work, executes
it across `claude` / `codex` / OpenRouter, stays inside the usage window without
supervision, survives being killed and resumed, and reports honestly what it
spent in both dollars and window quota.

Everything rests on one invariant:

> **Subtask output never re-enters the orchestrator's context.**

## Phases

Two numbering schemes existed and did not line up. Now unified on the
**engineering** sequence used by `DESIGN.md`, `README.md`, the module docstrings
and the tests.

| Phase | Scope | State |
|---|---|---|
| 1 | state schema + bounded manifest | complete |
| 2 | executor + three adapters | complete |
| 3 | tier router + live pricing + config | complete |
| 4 | budget governor + usage parser + real utilisation | complete |
| 5 | planner + CLI | complete |
| 6 | final gate: end-to-end live run, review, heavy pentest | complete |
| 7 | live TUI dashboard + sparse-control console | complete |
| 8 | interactive console, host control, browser control | complete |

## Current phase/stage

Phases 1–8 are complete with **319 tests passing**.

Phases 1–7 gave the orchestrator: `sleipnir tui` is an offline/read-only
dashboard, `tui --run` safely owns/resumes workers, and `tui --orchestrate`
runs workers plus sparse brain control behind the same bounded console.
Isolated provider-backed Codex execution and genuine hard-kill/resume recovery
both pass end to end.

Phase 8 turned Sleipnir into a front door rather than a batch tool. Bare
`sleipnir` opens an animated green console; a typed message is handed to the
real `claude` CLI with session continuity, and the harness attaches host
capabilities the CLI does not have on its own — kernel-level keyboard/mouse
injection, screen capture, a persistent logged-in browser, and a credential
prompt that never lets a secret reach a model.

Live-verified on this machine: pointer injection under Wayland, `spectacle`
screen capture, Chromium navigation + text extraction + screenshot, operator
shell, and a two-turn `claude` round trip proving session continuity
(`SLEIPNIR-LINK-OK`, then correct recall on turn two).

## The parallel-build merge (2026-08-18)

Phases 3–5 were built **twice, independently**, from the same design document —
once by the mobile agent (pushed as `4065842`) and once locally. The convergence
was near-total: tier→model routing, transcript-derived budgets, deduplication on
`requestId`, ignoring `iterations[]`. Good evidence the architecture is
determined by the problem rather than by taste.

**Resolution: the mobile agent's branch is the base.** It is better structured
(config-driven, no model name or price anywhere in source, an `--explain` that
renders every candidate's accept/reject reason) and it includes `planner.py`,
`cli.py` and `config.py`, which the local build lacked entirely.

Five things were ported in from the local build, all found by live measurement
rather than by reasoning:

1. **The `-1` price sentinel.** Five live models price at `-1`. The
   implausible-price guard is a `>` test and misses negatives, so unguarded they
   read as −$1,000,000/Mtok and win every routing decision forever.
2. **Non-finite prices.** `float()` accepts `"Infinity"`, `"1e400"`, `"NaN"`.
   NaN passes every comparison guard and silently destroys the cost ordering.
3. **`<synthetic>` records** are CLI-generated messages, never API calls.
   Costing them invents spend that did not happen.
4. **Attempt rotation** in the router. Free models rate-limit individually, so
   an identical retry fails identically. Also yields tier escalation for free.
5. **A refusal that did not refuse.** `test_no_catalogue_and_no_network_refuses_to_run`
   deleted the cache but never blocked the fetch, so on any networked machine
   the guarantee passed by accident.

The local `governor.py` / `usage.py` were **superseded** by their `budget.py`,
which is better on two counts: a `request_id` fallback chain that dedupes
records lacking one, and first-use-anchored windows rather than a rolling
lookback. Both are preserved on the `parallel-build-local` branch.

## Decisions log

- 2026-08-18 — **Window quota, not dollars, is the scarce resource.** On a
  subscription `claude -p` costs $0 marginal but consumes the 5-hour window.
- 2026-08-18 — **Prices are fetched live and never remembered.** No catalogue
  and no cache is a hard error; a stale cache is used with `stale=True`
  surfaced, because an expired price beats no price.
- 2026-08-18 — **Per-dispatch fixed cost is a first-class routing input.** A
  `claude -p` spawn burns ~30k tokens before any work: $0.0404 on Haiku, $0.2022
  on Opus at live prices. A live headless run independently reported
  `total_cost_usd: 0.0447`, within 10% of the computed figure.
- 2026-08-18 — **Sleipnir reads `~/.claude/.credentials.json`** (operator
  approved) to call `GET /api/oauth/usage` for true window utilisation.
  Read-only, `claudeAiOauth.accessToken` only, never logged or persisted, fails
  soft to local estimation on every error path.
- 2026-08-18 — **The cache-read weighting question is dissolved, not answered.**
  The meter reports a *percentage*; on a subscription every dollar and token
  field in the response is null, so no client-side summing could reconstruct it.
  Utilisation is folded back into token units by solving
  `implied_limit = used / (utilisation/100)`, which absorbs whatever weight the
  real meter applies.
- 2026-08-18 — **Tests are hermetic by default.** Before the guard the suite
  made 18 authenticated calls per run, putting a bearer token on the wire on
  every `pytest`. `tests/conftest.py` patches out both the credential read and
  the endpoint; opting in requires `@pytest.mark.allow_utilization_reads` plus a
  mock transport.
- 2026-08-18 — **The usage endpoint is itself rate-limited** (observed 429 after
  a handful of rapid calls). TTL raised to 300s and failures cached as hard as
  successes, so a 429 cannot start a retry storm against the endpoint that
  reports throttling.
- 2026-08-18 — **Unknown context is not insufficient context.** A live-priced
  catalogue entry without context metadata stays eligible and is surfaced as
  uncertain; only a known-too-small window is rejected.
- 2026-08-18 — **Open attempts are durable crash markers.** Resume closes an
  orphan as `INTERRUPTED`, preserves its billing axis, and retries in a fresh
  workspace. It refuses recovery while the recorded executor PID is alive.
- 2026-08-18 — **A kernel lock owns each run directory.** Open-attempt PID
  checks cannot close the race where two executors both see READY before either
  appends. `run.lock` now uses non-blocking `flock`, which releases on process
  death without stale-lock deletion.
- 2026-08-18 — **The TUI is derived state, like status.** It renders only the
  plan, folded result log and budget snapshot; it stores no status and reads no
  artifact or summary content. It uses the standard library, keeping the two
  runtime dependencies unchanged.
- 2026-08-18 — **Attempt files are an untrusted boundary.** Summaries, outputs,
  repository inputs and dependency artifacts must be regular files physically
  inside their declared root. Symlink escapes and `../` input paths are refused,
  harness-owned filenames cannot be task outputs, and unrelated credentials are
  removed from agent CLI environments.
- 2026-08-19 — **Claude control is sparse, not per-task.** `orchestrate` lets
  workers run autonomously and wakes the reason-tier brain only at a terminal
  impasse. It receives the constant-size manifest plus at most four urgent task
  specs capped at 24k characters—never artifact content or transcripts.
- 2026-08-19 — **Brain revisions are typed and locally enforced.** Complete task
  or edge payloads are validated against the DAG; retargets may not disguise a
  semantic change; superseded/stale blast radius is computed locally; the audit
  is fsynced before `plan.json` is atomically replaced.
- 2026-08-19 — **The default policy matches the product economics.** Claude is
  first for reason/control, Codex subscription is first for bulk code, and
  OpenRouter is first for mechanical/extract work. Claude is no longer the
  example config's default worker for code tasks.
- 2026-08-19 — **Subscription quota pools are separate.** Codex CLI usage is
  reported as `codex_tokens`; it consumes neither the Claude 5-hour projection
  nor metered-dollar budget. The example uses `@cli-default`, which deliberately
  omits `--model` so an authenticated Codex CLI selects an account-supported
  default instead of failing when a pinned alias is retired.
- 2026-08-19 — **Semantic brain changes require operator review.** Routing-only
  retargets may auto-apply, but respec/add/remove/edge changes are persisted as
  pending proposals. `apply-revision` is the explicit review boundary and marks
  successfully applied proposals out of the TUI's pending count.
- 2026-08-19 — **Provider processes inherit executor death on Linux.** A real
  `SIGKILL` drill proved the run lock and recovery correct but exposed the Codex
  CLI continuing as an orphan. Real CLI children now run under a small
  `PR_SET_PDEATHSIG` guard that forwards parent death to the whole provider
  process group; a kernel-level test kills the supervisor and verifies both the
  guard and provider descendant stop.
- 2026-08-19 — **Stale and superseded are revision work queues.** They are not
  completion states. A changed task reruns first; stale descendants then rerun
  in strict dependency order using only freshly `DONE` upstream results. This
  closes a pentest finding where semantic revisions were validly persisted but
  the executor could never perform them.
- 2026-08-19 — **The TUI is now the full harness console.** Static/watch modes
  stay offline and log-derived; execution and orchestration modes own the same
  run lock. It reloads atomic plan revisions, exposes pending review and bounded
  control events, separates Claude/Codex/metered usage, and strips all terminal
  control characters from untrusted display values.
- 2026-08-19 — **Brain calls use the same durable accounting stream.** A valid
  or invalid completed control call appends an `AttemptFinished` record with
  usage, quota pool, notional cost, and decision artifact hash. It does not
  affect DAG task projection, but it does appear in budgets and the TUI.

- 2026-08-19 — **Bare `sleipnir` is the console, not an error.** The front door
  is a conversation, the way bare `claude` is. Every batch subcommand still
  exists; `argparse` simply no longer requires one.
- 2026-08-19 — **The console is a router, never a second model.** It renders and
  it decides *who* receives a message. Brain awake: straight to `claude` with
  `--session-id` then `--resume`, so the ~30k-token spawn overhead buys a
  continuing conversation instead of a stranger each turn. Brain asleep: a
  cheap OpenRouter duty officer answers from the bounded manifest, and a plan
  change becomes a `QUEUE:` line for the brain rather than an action — plan
  mutation still goes only through `revisions.apply_revision`.
- 2026-08-19 — **Wayland forced kernel-level input injection.** X11-style
  synthesis is gone by design, so `xdotool` would reach XWayland windows only.
  `ydotool` writes to `/dev/uinput`, which needs a udev rule; `sleipnir setup`
  packages that install and prints every root command before running it, so no
  future user hand-runs sudo from a README.
- 2026-08-19 — **`grim` is present on this box and must not be chosen.** It is
  wlroots-only and fails on KWin. Screenshot tool selection prefers
  `spectacle` on KDE explicitly; a pinned test covers the mis-selection.
- 2026-08-19 — **Capabilities are operator-lane only, and audited.** Worker
  tasks keep the credential-stripped environment and confined workspace. Every
  privileged call appends to `~/.sleipnir/capability-audit.jsonl`, and the
  redactor drops secret-shaped keys at the boundary rather than trusting
  callers — typed text is recorded as a length, never as content.
- 2026-08-19 — **A credential is a one-shot byte buffer, never a string.**
  `Secret` overrides every rendering hook (`__str__`, `__repr__`, `__format__`)
  so one stray `print` or traceback cannot leak it, wipes on consume, and
  raises on reuse because re-use means a caller stashed it. Python string
  immutability means a transient plaintext copy still exists at the moment of
  use; that ceiling is recorded in the module.
- 2026-08-19 — **The console defaults to `bypassPermissions`.** Host control is
  the product; a console that stops to confirm every click is an ordinary
  headless Claude. `--ask-first` narrows it back for a cautious session.
- 2026-08-19 — **GSAP's curves ported, GSAP not.** A terminal cannot run a web
  animation library, but the easing maths is what carries the feel. `theme.py`
  implements `power2.out`, `back.out` and `elastic.out` as pure functions of an
  explicit frame number, so the splash and the border flicker are deterministic
  and testable with no terminal attached.

## Open questions

- **Codex usage pricing remains notional.** The adapter surface, account-default
  selection and JSONL usage shape are live-verified against CLI 0.148.0; mapping
  a subscription call to dollar-equivalent price still depends on
  operator-supplied model data.
- **`llm_judge` acceptance checks raise at executor construction**, deliberately.
  Revisit only if a plan needs them.
- **`server_tool_use` is captured but not yet priced.** Web search and fetch
  bill per request ($0.01 in the catalogue); no run has exercised them yet.
- **Should `code`-tier work start on a free model?** Cheapest, and it falls back
  when acceptance checks fail — but it leans hard on those checks.

## Next steps

1. **Verify the one unverified leg**: that `claude`, running under the console,
   actually invokes the `sleipnir computer` / `browser` / `secret` commands.
   Every capability is live-verified standalone, and the console→`claude` link
   is live-verified, but the join could not be tested from inside a Claude Code
   session — nesting a `bypassPermissions` spawn is blocked there. One message
   into a real `sleipnir` console settles it.
2. Wire the console's asleep path to a live run: `ConsoleState.brain_awake`
   is honoured by the renderer and the handler, but nothing yet flips it from
   the orchestrator, so the duty-officer path is reachable only by setting it.
3. Continue the adversarial review of config values, workspace pre-creation and
   hard-kill orphan process groups; the concurrent-executor and filesystem-read
   findings are fixed.
4. Price `server_tool_use` requests into the cost model.
5. **Finish the Graphify refresh with a semantic pass.** The structural graph
   was rebuilt on 2026-08-19 and is current at **1,225 nodes / 3,709 edges /
   45 labelled communities**, all AST-derived. Five changed docs (`CLAUDE.md`,
   `project.md`, `overview.md`, `README.md`, `DESIGN.md`) were deliberately left
   unstamped rather than dispatched to extraction subagents, so a later full
   build re-queues them. Until then the graph carries no doc-derived nodes,
   which is why the health check reports 233 dangling and 314 collapsed edges —
   prose endpoints the code half still references.

## Environment on this machine

| Thing | State |
|---|---|
| `claude` CLI | present; `--model` takes `opus`/`sonnet`/`haiku` aliases |
| `codex` CLI | present; flags and JSONL usage verified against 0.148.0 |
| `uv` | **not installed** — use `python3 -m venv` + `pip` |
| `.venv` | present, Python 3.14.6 |
| `OPENROUTER_API_KEY` | set in `~/.bashrc`, live-verified against a `:free` model |
| `ANTHROPIC_API_KEY` | deliberately unset — keeps billing on subscription |
| git identity | set **locally** to `Claude <noreply@anthropic.com>`, matching prior commits |
| branches | `parallel-build-local` preserves the superseded local build |

## Phase 6 progress (2026-08-18)

- Baseline suite: 217 tests passing before Phase 6 changes.
- Codex CLI 0.148.0 flags verified from installed `--help`.
- Isolated live JSONL smoke call completed. It exposed and fixed cached-input
  double-counting in the Codex adapter; the observed usage payload is pinned by
  a regression test.
- Phase 6 review found and fixed a catalogue-policy regression: models with an
  unknown context window were being dropped even though unknown is not evidence
  of insufficiency. They are now retained, surfaced as uncertain, and covered
  at both catalogue and router layers.
- Phase 6 recovery review found that `resume` detected open attempts but left
  them projected as `running` forever. The executor now closes each orphan as
  `INTERRUPTED` and retries in a new attempt workspace; a regression test starts
  from a fsynced `AttemptStarted` with no terminal record.
- A live planner invocation was prepared but made no provider call because the
  first local module invocation failed before dispatch. The meter then reported
  `five_hour=100.0%` with reset at 2026-08-19 03:39:59 UTC, so all further live
  dispatch was stopped per the usage guard.
- Pentest fixed three real trust-boundary classes: duplicate concurrent
  executors, symlink/path escapes that could move host-file content into agent
  prompts or summaries, and wholesale secret inheritance by delegated CLI
  subprocesses. Bandit reports no findings; `pip check` is clean.
- Phase 7 began with a pure terminal renderer and CLI integration. Static mode
  cannot spend; `--run` owns the executor under the same kernel lock; large DAGs
  are height-bounded and subagent summaries never render.
- The missing ongoing-brain seam is now implemented. A fake-backed end-to-end
  test exhausts two worker attempts, accepts a Claude-style retarget revision,
  fsyncs its audit, and completes on attempt three without repeating other work.
- A three-attempt isolated live gate preserved two pre-dispatch failures, then
  succeeded through the Codex subscription using `@cli-default`. The accepted
  task wrote and hashed its required artifact; accounting reported 48,456
  `codex_tokens`, zero Claude-window tokens, and zero metered dollars.
- The real hard-kill drill left an open attempt, released the kernel lock,
  rotated to attempt two on resume, produced the accepted artifact, and charged
  65,093 tokens only to the Codex quota pool. Pentesting that path exposed and
  fixed an orphan-provider lifetime gap with the Linux parent-death guard.
- A live seeded terminal impasse invoked Claude Sonnet once with only the
  bounded manifest/frontier. It produced a routing-only revision, raised the
  retry allowance from one to two, and Codex completed the accepted artifact on
  attempt two. Observed usage was 170,791 Claude tokens ($0.304761 notional) and
  48,497 Codex tokens, with zero metered dollars. That run exposed and closed
  missing control-call log accounting.
- The full hermetic checkpoint is 277 tests passing; `compileall`, `pip check`,
  `git diff --check`, and Bandit all pass.
