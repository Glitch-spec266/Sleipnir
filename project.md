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
| 9 | phase gate, module escalation, duty-officer routing | complete |

## Current phase/stage

Phases 1–9 are complete with **419 tests passing**.

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

On 2026-08-19 the last missing join was verified live: a message typed into a
real console reached `claude`, and `claude` called
`python -m sleipnir.cli computer screenshot` on its own and read the resulting
PNG. The model driving the host through the harness is no longer a design
claim.

Phase 9 closed the loop between workers and the brain. When workers go quiet,
`gate.py` folds the run into a constant-size verdict — per-group counts and the
ids of what failed — and the harness tries to answer the failure itself before
paying for a reason-tier spawn: a failed module is re-run one tier stronger,
routing-only, so it cannot change what the work means. The brain is woken only
when work has genuinely stopped *and* the harness cannot fix it. The console's
asleep path is live too: an owned run lock means the brain is mid-build, and a
cheap duty officer answers from the same bounded verdict.

## What the first real console session found (2026-08-19)

Five bugs, none of which any test or review had caught, all found by one
operator using the thing for twenty minutes. Worth recording because of what
they have in common: every one was invisible to a unit test because the unit
behaved correctly in isolation.

1. **The console had no `--model`, so every message went to the account
   default.** A one-line question was answered by the most capable and slowest
   model, paying a full ~30k-token spawn — roughly a minute per turn. The
   console now defaults to `sonnet` and takes `--model`. Reported as "it routes
   to other models unnecessarily"; in fact the console never touched the tier
   router at all, which is exactly why nothing in the routing tests could see it.
2. **`cmd_browser` wrapped every call in `async with Browser(...)`.** The browser
   died with the command, so `browser open` and `browser click` were two
   different browsers and the second started blank. Multi-step web flows — the
   only reason the capability exists — were impossible. From the outside it
   looked like the same window opening and closing repeatedly, which is what the
   operator saw. Chromium is now launched detached and driven over CDP.
3. **`secret prompt` could not be reached by the model it was built for.**
   `secrets.capture` uses `getpass`, which needs a controlling terminal; a tool
   subprocess has none (`/dev/tty` → "No such device"). The credential path
   existed and was unreachable. Now a handoff: the subprocess files a labelled
   request, the console prompts inside its own frame, and the value goes from
   the operator's keyboard to the target without ever entering a file, a pipe,
   or the requesting process.
4. **The console never switched to the alternate screen buffer.** Every one of
   twelve frames per second was appended to the operator's scrollback, so
   exiting revealed hundreds of stacked copies of the UI. Reported, reasonably,
   as "it opened like 70 sleipnir instances" — nothing had spawned at all.
5. **`browser close` reported success while Chromium kept running.** Closing a
   CDP *connection* does not close the browser. The pid is now recorded at
   launch and the process group is signalled.

The console header was also drawing `art[:1]` — the top row of a five-row
wordmark — which renders as debris rather than a logo.

The wordmark has now been replaced outright by a letter-free horse emblem. Its
four visible leg pairs are the identity of Sleipnir; the surrounding frame
already carries the readable product name.

## Guarded fast lane and `/project` (2026-08-19)

Ordinary console requests now default to Haiku, but Haiku is not trusted to
decide and act in one step. Sleipnir first invokes it with `--tools ""` and a
binary capability protocol. Only an exact one-turn `SLEIPNIR_CAPABLE` verdict
allows a second Haiku turn to use tools. A decline, extra prose, missing turn
telemetry, or any malformed answer fails closed to Sonnet. Sleipnir never
replays a failed action automatically: once a model may have touched the host,
retrying the same request could duplicate an irreversible side effect.

`/project <goal>` is the explicit complex-work boundary. It never enters the
chat lane. The console launches the existing `plan` command followed by
`orchestrate`, preserving the real planner, tier router, budget governor,
acceptance checks, phase gate, and semantic-revision review. The child owns a
process group; leaving the console terminates provider descendants rather than
letting an abandoned project continue spending.

Clipboard behavior is now explicit on both sides of the console. Agent commands
`computer copy` and `computer paste` inject Ctrl+Shift+C/V, so the focused Linux
application owns and preserves text or image MIME. Operator text paste uses
bracketed-paste framing and cannot submit a multiline prompt halfway through.
Image pixels cannot cross a PTY, so `clipboard.py` reads the Wayland MIME and
materialises a private `0600` attachment for Claude instead. Clipboard content
is never written to the audit log; only its type and length/path are recorded.

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

- 2026-08-19 — **The gate is a verdict, not a review.** The tempting version of
  "the brain comes back and reviews all the reports" is quadratic: its context
  grows with the number of modules. `evaluate_gate` returns per-group counts and
  failed ids only, so a 5-task run and a 500-task run produce the same-sized
  object. Verification stays where it belongs — acceptance checks decide pass or
  fail, and the brain sees the verdict.
- 2026-08-19 — **Escalation must grant an attempt, not only a tier.** A task is
  FAILED precisely because `attempts >= retry.max_attempts`. Raising only the
  tier produces a better-routed task the executor will never dispatch — the
  escalation silently does nothing. Both fields are outside `spec_hash`, so the
  change stays routing-only and auto-appliable; granting exactly one more
  attempt rather than resetting the counter keeps the ladder finite.
- 2026-08-19 — **Only a task that actually lost is escalated.** SKIPPED means a
  dependency failed and this task never got a turn; CANCELLED means the operator
  or the budget stopped the run. Escalating either re-routes a whole downstream
  subtree on one upstream failure, spending money on models that were never the
  problem. Both still stop a group passing.
- 2026-08-19 — **Brain wakefulness is derived, like task status.** The console
  reads the run lock: an owned run directory means an executor is mid-build and
  the brain is asleep between decisions. Nothing is stored, so there is no
  wake-state file to go stale or to repair after a crash.
- 2026-08-19 — **Capability classification gets no tools.** Asking a model to
  promise it will decline before acting is not enforcement. The fast-lane check
  runs with an empty tool set, and only a strict affirmative opens Haiku's
  action turn; uncertainty and protocol drift go to Sonnet.
- 2026-08-19 — **Complexity is an operator command, not a prose heuristic.**
  Ordinary messages are small requests; `/project <goal>` invokes the existing
  multi-model plan/orchestrate pipeline. This boundary is visible, predictable,
  and cannot silently classify a casual desktop command as a full project.
- 2026-08-19 — **Clipboard MIME stays with the desktop.** Ctrl+Shift+C/V are
  injected as physical chords for agent-driven app interaction. Console text
  paste is bracketed; console image paste is a private file attachment because
  a terminal byte stream cannot represent pixels.
- 2026-08-19 — **The mark is a horse, not typography.** The border already says
  SLEIPNIR. The animated art is now the eight-legged emblem itself, including a
  compact form that keeps all four leg pairs at narrow widths.
- 2026-08-19 — **Server tools are usage, not tokens.** Claude, OpenRouter and
  transcript parsing retain web-search/fetch counts alongside token usage. A
  route freezes the catalogue's per-search price for fallback estimates, while
  a provider-reported total remains authoritative and is never charged twice.
  Current Anthropic documentation prices search at $0.01 per successful request
  and web fetch at no extra request fee; fetched content still costs tokens.
- 2026-08-19 — **Configuration does not coerce policy.** Integer fields reject
  booleans, fractions and non-finite values; list-valued policy fields reject
  strings masquerading as lists; catalogue locations are typed before any run.
- 2026-08-19 — **Harness writes distrust their own workspace after dispatch.**
  Workspace roots and parents are checked before creation, harness files use
  no-follow writes in an already-claimed directory, and an agent-created
  `outcome.json` symlink cannot overwrite a host file.
- 2026-08-19 — **Parent death includes hard escalation.** The Linux guard sends
  the provider group `SIGTERM`, waits one second, then sends `SIGKILL` itself.
  Cleanup therefore still finishes when the executor is gone and a descendant
  ignores termination.
- 2026-08-19 — **The console does not get a weaker process boundary.** Ordinary
  Claude turns and `/project` stages now use the same streaming ProcessRunner
  as workers: private disk-backed output, bounded response loading, process
  groups, cancellation cleanup and Linux parent-death escalation.
- 2026-08-19 — **A PID file is a claim, not authority.** Browser shutdown now
  verifies that the PID is a session leader whose live `/proc` command line
  carries Sleipnir's exact debugging port and profile. PID publication is
  private and atomic; stale/symlinked claims cannot redirect writes or kills.
- 2026-08-19 — **A credential prompt needs a live claimant.** Handoff requests
  are private bounded regular files whose ID matches the filename and whose
  requester PID is alive under the same user. Forged/dead requests and symlink
  payloads are discarded; answer status is a closed vocabulary written once.
- 2026-08-19 — **Every persistent host path is a trust boundary.** Capability
  audit append refuses file/directory symlinks, clipboard images refuse a
  redirected destination, and Chromium refuses a symlinked profile before
  Playwright launches. Rejected paths cause no external mutation.
- 2026-08-19 — **A project gets a run directory, not the source directory.** A
  bare console allocates a fresh timestamped workspace under `./runs` for each
  `/project`; discovered config follows it. Only an explicit `--run-root` uses
  an exact path, which is created before the child starts.
- 2026-08-19 — **Code starts on Codex subscription, not a free model.** The
  shipped policy already made this choice: bulk code prefers Codex, then
  OpenRouter, then Claude. Free catalogue models remain eligible only after
  policy reaches the metered backend.
- 2026-08-19 — **The phase gate is live, not only simulated.** A disposable
  terminal failure produced a real failed-module verdict, revision 1 changed
  only `mechanical → extract` and attempts `1 → 2`, and real Codex completed
  the accepted retry with a hashed `SLEIPNIR_GATE_LIVE_OK` artifact. Accounting
  recorded 48,566 Codex tokens and zero Claude-window or metered spend.
- 2026-08-19 — **`/project` crosses the real console boundary.** A command typed
  into the PTY planned exactly two independent `reason`/`code` tasks, routed
  both through Codex, and completed hashed `ROUTED_REASON_OK` and
  `ROUTED_CODE_OK` artifacts in one orchestration cycle (130,718 Codex tokens).
- 2026-08-19 — **Only a tool-free failure may fall back automatically.** If the
  Haiku assessment process itself is unavailable, Sleipnir rotates uncertain
  first-turn session state and gives Sonnet the untouched original request.
  Once any model has tools, failure is never replayed.
- 2026-08-19 — **Lane choice stays visible after the status frame.** The console
  records a content-free transcript notice when the fast lane is approved or
  fails closed to the strong model, so operators and live verification can
  distinguish Haiku action from Sonnet fallback without logging the request.
- 2026-08-19 — **Credential handoff stays live during the model turn.** The
  console polls while Claude is busy, because that is exactly when its tool
  subprocess waits. Browser requests may carry a CSS selector; the console
  fills it over CDP and wipes the secret, avoiding the focus paradox where
  returning to the terminal loses the browser field.
- 2026-08-19 — **The focus-independent browser secret path is live.** A real
  non-TTY request blocked while a busy console detected it, CDP filled and
  submitted a disposable password field, and the page exposed only
  `SUBMITTED_LENGTH_25` before clearing it. The requester learned only
  `credential supplied`; the dummy value appears in no Sleipnir state or log.
- 2026-08-19 — **Invalid browser commands are side-effect free.** Argument
  arity is checked before Playwright attaches, and `browser close` signals the
  verified detached process directly. Closing an absent browser no longer
  launches Chromium merely to shut it down.

## Open questions

- **Codex usage pricing remains notional.** The adapter surface, account-default
  selection and JSONL usage shape are live-verified against CLI 0.148.0; mapping
  a subscription call to dollar-equivalent price still depends on
  operator-supplied model data.
- **`llm_judge` acceptance checks raise at executor construction**, deliberately.
  Revisit only if a plan needs them.

## Next steps

1. ~~**Verify the one unverified leg**~~ — **done, live, 2026-08-19.** A message
   typed into a real `sleipnir` console ("take a screenshot and tell me whats on
   my screen rn") reached `claude`, which invoked
   `python -m sleipnir.cli computer screenshot` itself and read back a real
   3840x1080 dual-monitor capture. That closes the join the harness exists for:
   console → `claude` → host capability → image back into the model's context.
   Browser navigation and the new focus-independent secret/CDP handoff are also
   live-verified standalone; the remaining proof is Claude initiating them from
   inside the console after quota resets.
2. ~~**Live-verify the gate against a real provider run.**~~ **Done, live,
   2026-08-19.** The gate persisted one finite failed-module-only escalation,
   real Codex completed attempt two, and the declared proof artifact passed.
3. ~~Continue the adversarial review of config values, workspace pre-creation
   and hard-kill orphan process groups.~~ **Done, 2026-08-19.** Numeric/list
   config coercions now fail closed, workspace creation/writes reject symlink
   pivots, and the parent-death guard hard-kills SIGTERM-resistant descendants.
4. ~~Price `server_tool_use` requests into the cost model.~~ **Done, 2026-08-19.**
   Search request rates come from the frozen live catalogue snapshot; fetch
   counts remain visible but carry no separate fee under current Anthropic
   pricing. Provider totals take precedence over estimates.
5. **Partially live-verified.** A disposable `/project` typed into the real PTY
   completed through `reason` and `code` tiers with two accepted artifacts.
   The ordinary Haiku-pass and Haiku-decline→Sonnet branches still require the
   exhausted Claude window to reset.

Live verification is currently paused by the provider, not by the harness: the
read-only Anthropic meter reported the five-hour window at **100.0%**, resetting
at **2026-08-19 23:29:59 UTC**. No Claude call was attempted after that reading;
the gate and `/project` proofs used the separate Codex subscription pool.

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
