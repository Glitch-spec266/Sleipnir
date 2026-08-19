# Sleipnir — project instructions

Read `project.md` for current state, `overview.md` for how the code works, and
`DESIGN.md` for why each tradeoff was made.

## The one invariant

> **Subtask output never re-enters the orchestrator's context.**

Everything else is negotiable. This is not. If it leaks even once — even as
"just a short summary" — the cost of a run goes from linear to quadratic and the
entire project is worse than doing the work in a single long session.

Concretely, this means:

- **Never add a field to `Manifest`, or anything nested inside it, that can carry
  artifact content.** Paths only. `EvidenceEntry.artifact_paths` is paths by
  design, and that is structural rather than a matter of policy.
- **Never inline the full DAG into the manifest.** The chosen approach is group
  rollups plus an on-demand `read_plan(group=…)` drill-down. Inlining a
  "compressed" skeleton reintroduces Θ(n) growth quietly, which is the dangerous
  kind.
- `test_manifest_size_is_constant_in_task_count` is the executable form of this
  rule. If a change makes it fail, the change is wrong — do not adjust the test
  to fit.

## Rules that will bite you if ignored

- **Task status is never stored.** It is always folded from `results.jsonl` over
  `plan.json` via `projection.fold_results`. Do not add a status field, a cache,
  or a checkpoint file. The absence of derived state on disk is exactly what
  makes crash recovery a normal read instead of a repair routine.
- **Terminal text is a trust boundary.** Plans, model ids, and brain reasons
  can contain control bytes. Route every TUI value through `_clip`; its
  printable-character filter prevents ANSI/newline injection. Static/watch TUI
  modes must stay offline, while `--run`/`--orchestrate` own the run lock.
- **`Task.spec_hash()` must keep excluding routing fields** — `tier`, `priority`,
  `timeout_s`, `retry`, `adapter_hint`, `group`. If tier entered the hash, every
  budget downshift would invalidate completed work and the governor would fight
  the executor. `test_spec_hash_ignores_routing_fields` pins this.
- **Adapters report; the executor decides.** An adapter returns a
  `DispatchOutcome` of raw observed facts and must never decide whether a task
  succeeded. It cannot know — acceptance checks run after it returns, and pricing
  lives elsewhere.
- **Whether the work is good is decided by what landed on disk**, through the
  output contract and the acceptance checks. Never by provider chatter. A tool
  permission denial is recorded in `provider_meta` and changes nothing about
  status; treating it as failure once caused successful work to be retried at
  double cost.
- **A check that cannot be performed fails at executor construction, not at task
  time.** A plan that cannot be fully verified must be refused before anything is
  dispatched.
- **`results.jsonl` is append-only, fsynced per record.** A torn *final* line is
  discarded and logged; a torn line anywhere else is real corruption and must
  fail loudly rather than be silently repaired.
- **You may not read from a task you do not declare as a dependency.** Both
  `summaries` and `artifacts` are cross-checked against `depends_on`. Without
  this, a task can race its own input producer.

## The router (Phase 3)

- **No model name and no price may appear in the source.** Both arrive as data:
  prices from the live catalogue, capability claims from the operator's TOML
  config. The catalogue has no capability column, so the router never infers one.
- **`--explain` prints every candidate with its accept/reject reason**, not just
  the winner. A router you cannot interrogate is a router you cannot trust with
  money. Keep it that way.
- **`resolve()` uses its `attempt` argument** to take the *n*-th cheapest viable
  candidate. This is load-bearing twice over: free models rate-limit
  individually, so an identical retry fails identically; and it produces tier
  escalation (sonnet then opus) with no ladder code. Do not "simplify" it back to
  always picking the cheapest.
- **A missing price is never zero.** `PriceBook.get` raises rather than
  defaulting, and the router drops the candidate. Zero would read as free forever
  and that candidate would win every comparison it entered.
- **Reject non-finite prices explicitly.** `float()` accepts `"Infinity"`,
  `"1e400"` and `"NaN"`. NaN is the trap: every comparison against it is False, so
  it passes a `>= 0` guard *and* silently destroys any ordering built on it.
- **Reject negative prices explicitly.** Five live `openrouter/*` meta-models
  price at `-1`, the sentinel for "cost depends which model is picked". The
  implausible-price guard is a `>` test and does not catch a negative, so
  unguarded they read as −$1,000,000/Mtok and win every route forever.
- **Keep the implausible-price guard too.** Prices are documented as USD per
  token; if that ever became per-million, every number would be 1e6 too high.
  Anything over $10,000/Mtok is a units change, not a fact.
- **An unknown context window does not exclude a candidate.** Unknown is not the
  same as too small; refusing on absent data over-refuses.
- **Nothing from the network may reach a dispatch.** `RoutingDecision.model`
  comes from config; the catalogue supplies only prices, keyed by ids used for
  lookup. Keep it that way — it is why a hostile catalogue cannot inject a model,
  URL, or argv element.

## Money and resources

- **Window quota is the scarce resource, not dollars.** This runs on a Claude
  subscription: `claude -p` costs ~$0 marginal but consumes the 5-hour usage
  window. Dollar figures in reports are **notional** — what the work would have
  cost at metered API rates — and must be labelled as such. `RunReport` carries
  `notional_usd` alongside `cost_usd` for exactly this reason.
- **`CostEstimate` carries `amount_usd` and `window_tokens` separately on
  purpose.** They are two scarce resources that do not convert. Never collapse
  them into one number; the cheapest option in dollars may be the one that
  exhausts the window.
- **Every `claude -p` spawn costs ~30k cache-creation tokens before doing any
  work.** That is a floor, independent of task size. Per-dispatch fixed cost is a
  first-class router input — routing a trivial task to an expensive spawn can
  cost more than the work is worth.
- **Cache-read tokens are counted 1:1 with input tokens, deliberately.** This
  over-estimates window consumption by roughly 10×, which makes the governor
  downshift too eagerly rather than blow the window. Do not "fix" this to a ~0.1
  weight until Phase 3 has measured what the 5-hour window actually meters.
- **Never quote model prices from memory.** Fetch
  `https://openrouter.ai/api/v1/models` (public, no key required) and cache to a
  disk snapshot.
- **Never sum `input_tokens` alone** when parsing usage records — it read `2`
  against 47,052 cache-creation tokens in a real record. Sum all four input
  channels. Do not also sum `iterations[]`; it repeats the same counts and
  double-counts every turn. Dedupe on `requestId`.

## The budget governor (Phase 4)

- **Never invent a window limit.** With no known limit the governor allows and
  reports burn rate. A guessed limit throttles a run that had room or clears one
  that did not, and nothing downstream can tell which happened.
- **An observed HTTP 429 is ground truth and outranks every estimate.** Real
  transcripts carry `{"error":"rate_limit","apiErrorStatus":429}`. It stops
  subscription dispatch and leaves metered dispatch alone — the window is spent,
  dollars are not.
- **A blown dollar budget is a refusal, never a downshift.** A cheaper model
  still spends dollars, so only refusing actually stops it. `BUDGET_DENIED` must
  never be retried at the tier that was denied.
- **Deduplicate usage records on `requestId`.** Measured at 52-59% duplicates
  across two corpora — skipping this does not skew the budget, it *doubles* it.
  Records lacking an id get a synthesised one so they dedupe too.
- **Skip `<synthetic>` records.** They are CLI-generated messages, not API calls.
- **Never sum `iterations[]` as well as the top level.** Measured: they agree on
  every record, so summing both exactly doubles every turn.
- **The usage parser must never read message content.** It extracts counters only.
  Transcripts hold prompts and source code, and a budget scan that touched them
  would become a data-exfiltration path. There is a canary test for this.
- **The window is a percentage, not a token count.** `GET /api/oauth/usage`
  returns `five_hour.utilization`; on a subscription every dollar and token field
  in that response is null. Never try to reconstruct the limit by summing
  tokens — it has no client-side form. It is folded back into token units by
  solving `implied_limit = used / (utilisation/100)`, which absorbs whatever
  weight the real meter gives cache reads.
- **The credential read is narrow and must stay narrow.** Read-only; only
  `claudeAiOauth.accessToken` (the same file holds unrelated plugin secrets that
  are never touched); never logged, never persisted, never in an exception
  message, never in a `BudgetSnapshot` or the `Manifest`. Every failure path
  falls back to local estimation rather than raising — the `except` is
  deliberately broad because a leaked traceback carrying a bearer token would
  matter more than losing the reading.
- **The usage endpoint is itself rate-limited** (observed 429). Cache failures as
  hard as successes; a governor that retried on 429 would throttle itself out of
  the reading that tells it about throttling.
- **Tests must never touch the credential or the endpoint.** `tests/conftest.py`
  makes that the default; opting in needs `@pytest.mark.allow_utilization_reads`
  and a mock transport. Before that guard the suite made 18 authenticated calls
  per run.

## Environment on this machine

- `claude` and `codex` CLIs are both installed. Codex CLI 0.148.0 flags,
  account-default selection, JSONL usage, and artifact production are
  live-verified. `@cli-default` means omit `--model`; do not replace it with a
  hard-coded alias in source or the shipped example.
- **`uv` is not installed.** The README says to use it; use `python3 -m venv`
  and `pip` instead. A `.venv` exists.
- `OPENROUTER_API_KEY` comes from the user's shell environment. **Never write a
  key into the repo, and never echo a key's value into a transcript.**
- `ANTHROPIC_API_KEY` is deliberately unset — setting it would switch `claude -p`
  from subscription billing to metered billing.

## Working style here

- **Fakes are not enough.** Phase 2's 118 fake-based tests all passed, and a
  single live smoke run then found three real bugs — including one that broke the
  resume path the entire design exists to protect. Every phase ends with at least
  one small live run.
- The test fake sits at the **spawn boundary**, not in place of `ProcessRunner`.
  Mocking one layer up leaves the streaming, timeout, drain and kill logic
  untested — the code most likely to deadlock and least likely to be noticed
  doing it.
- **Two runtime dependencies: `pydantic` and `httpx`.** Adding a third is a
  decision to raise, not to make. `pytest` is dev-only.
- Prefer refusing a plan over degrading silently. A zeroed usage record tells the
  governor a call was free, which is worse than reporting that usage could not be
  found.

## Security

`plan.json` is **executable content** — `CommandCheck` runs arbitrary shell from
it. Never load a plan from an untrusted source, and never add a feature that
fetches or shares plans without addressing this first.

The OpenRouter adapter materialises files from model output. That write path is
confined to the attempt directory, and a block claiming a path like
`../../.ssh/authorized_keys` is dropped. There is a test for it. Keep it.

Every attempt workspace is agent-controlled. Never follow symlinks when reading
summaries, declared outputs, repository inputs, or dependency artifacts; doing
so can move a host file into a provider prompt or the orchestrator's bounded
summary. Task outputs also may not collide with harness-owned workspace files.

Agent CLI subprocesses receive a credential-stripped environment. The official
Claude and Codex CLIs use their own credential stores; passing the operator's
whole environment would unnecessarily expose OpenRouter, GitHub and CI secrets
to delegated tool execution.
On Linux, real CLI children must stay behind `process_guard.py`; its
`PR_SET_PDEATHSIG` contract prevents a provider CLI from continuing to spend
after an uncatchable executor `SIGKILL`. Keep both the normal process-group
TERM/KILL path and the parent-death regression test.

The sparse control brain may see only `Manifest` plus the constant-bounded
frontier task drill-down in `orchestrator.py`. Never include artifact content,
worker transcripts, or the full DAG in a control prompt. Revision payloads are
untrusted model output: apply them only through `revisions.apply_revision`, and
never accept model-supplied `superseded` or `staled` blast-radius lists.
Semantic/edge/add/remove revisions require explicit operator review by default;
only a routing-preserving retarget may auto-apply. Applied proposal files are
retained with `.applied` suffix so the TUI counts only pending JSON proposals.
`STALE` and `SUPERSEDED` are executable revision work, not terminal success:
rerun the changed upstream task first, then stale descendants with freshly
`DONE` dependencies. Never add either status to orchestration completion.
Completed control calls—valid decision or invalid output—must append a bounded
`sleipnir-control` terminal record to `results.jsonl`. Projection ignores the
non-plan task id, while quota/notional accounting must include it.

## The console and host control (Phase 8)

- **Capabilities are an operator lane, never a worker lane.** `capabilities/`
  deliberately breaks the sandbox the executor builds. Worker tasks keep the
  credential-stripped environment and confined workspace; only the console, and
  the brain acting on an operator instruction, may reach these. Never hand a
  capability to a dispatched task.
- **Every privileged call is audited, and the redactor runs at the boundary.**
  `audit.record` strips secret-shaped keys itself rather than trusting callers.
  Typed text is logged as a character count. Do not add a code path that logs
  the content of keystrokes, a form fill, or a credential.
- **A `Secret` is a `bytearray`, and every rendering hook is overridden.** One
  `print`, one f-string, one traceback would otherwise put a password into a
  transcript forever. It wipes on consume and raises on reuse — reuse means a
  caller stashed the value, which is the failure the class exists to prevent.
  Do not add a getter that returns the plaintext without wiping.
- **The console never answers for the model.** It renders and it routes. If it
  ever starts composing replies itself, the thing the user is talking to stops
  being Claude and nobody will be able to tell.
- **The duty officer sees the manifest and nothing else.** Its system prompt
  forbids task output, and a plan change comes back as a `QUEUE:` line that is
  shown to the operator and handed to the brain as *text*. It is never executed
  and never mutates the plan; revisions still go through
  `revisions.apply_revision` and its operator-review gate.
- **`grim` must not be selected on KDE.** It is present on this machine and is
  wlroots-only, so it fails on KWin. Screenshot selection prefers `spectacle`
  explicitly; `test_grim_is_not_selected_on_kde` pins it.
- **Capability tests may never touch the real desktop.** A suite that types
  into whatever window has focus is a hazard. Every host call is intercepted at
  the subprocess boundary, the same way provider spawns are.
- **Terminal chrome is a pure function of an explicit frame number.** No hidden
  clock, no global RNG. That is what makes the flicker and the splash testable
  without a terminal, and `theme._fit` measures *visible* width so a coloured
  line cannot silently break the border.

## The phase gate (Phase 9)

- **A gate verdict is counts, never content.** `evaluate_gate` returns per-group
  totals and the ids of what failed. If a field is ever added that grows with
  the plan — a summary, a path, a report excerpt — the brain's context becomes
  linear in module count and the run's cost becomes quadratic.
  `test_verdict_size_does_not_grow_with_task_count` is the executable form.
- **The brain is woken only when work stopped *and* something is wrong.**
  Quiescent-and-complete needs no decision, and a spawn to confirm success is a
  spawn wasted. `needs_brain` encodes both halves; do not relax it to "quiescent".
- **Escalation changes tier *and* `retry.max_attempts`.** Only the pair works: a
  FAILED task will not be dispatched again without a fresh attempt, so a
  tier-only escalation is a silent no-op. Both are outside `spec_hash`, which is
  what keeps the retarget routing-only and auto-appliable.
- **Never escalate a SKIPPED or CANCELLED task.** Neither lost on merit, and
  escalating a skipped task re-routes its whole downstream subtree because one
  upstream task failed.
- **The escalation ladder must stay finite.** It walks up `DOWNSHIFT_LADDER`,
  stops at the top tier, and stops at the schema's six-attempt ceiling.
  `test_the_ladder_terminates` pins it. A wrap-around or a counter reset turns
  the gate into an infinite spend loop.
- **Console brain-wakefulness is derived from the run lock**, never stored. It
  is the same rule as task status, for the same reason: no derived state on disk
  means crash recovery is an ordinary read.

## Lessons from the first real console session

- **A full-screen redraw loop must own the alternate screen buffer.**
  `theme.ENTER_FULLSCREEN` / `EXIT_FULLSCREEN` are not cosmetic: without them
  every frame lands in the operator's scrollback, and exiting looks like the
  program launched itself hundreds of times.
- **The shared browser outlives the command.** Never wrap a CLI browser action
  in a context manager that closes Chromium; `Browser.close` detaches, and only
  `shutdown()` ends it. A browser that dies with the command makes every
  multi-step web flow impossible — which is the only reason the capability
  exists.
- **Closing a CDP connection does not close the browser.** `stop_browser`
  signals the recorded process group. If you make `close` "tidier" by killing
  the process, you reintroduce bug 2.
- **A tool subprocess has no TTY.** Anything that needs the operator's fingers
  must go through `capabilities/handoff.py` and be answered by the console.
  `getpass` in a model-spawned process fails with "No such device or address",
  and it fails at the worst possible moment — mid sign-in.
- **A credential answer carries a status, never a value.** `await_answer`
  returns `supplied`/`cancelled`/`failed`. A caller that could read the
  plaintext is a caller that could log it.
- **Capability checks must be physically tool-free.** The console invokes the
  Haiku assessment with `--tools ""`; prompt instructions alone do not force a
  model to admit uncertainty before acting. Only the exact one-turn affirmative
  verdict opens Haiku's action lane. Everything malformed fails closed to
  Sonnet, and a post-action failure is never replayed automatically.
- **`/project` is the complex-work boundary.** Ordinary messages use guarded
  chat. `/project <goal>` runs the real `plan` then `orchestrate` pipeline; do
  not replace it with a second planner or a prose complexity heuristic. Its
  child process group must die when the console task is cancelled.
- **Clipboard payloads are MIME, not strings.** Agent copy/paste injects the
  requested Ctrl+Shift+C/V chords and lets the focused application preserve
  text or image ownership. Console text uses bracketed paste; image data is
  read with `wl-paste` into a private attachment because a PTY cannot carry
  pixels. Audit metadata only—never clipboard text or bytes.
- **Draw the whole emblem or none of it.** `logo_lines` is all-or-nothing;
  slicing rows of terminal art renders as debris. The mark stays letter-free
  and keeps four leg pairs; the border title is where the name belongs.
- **A provider total already includes its server tools.** Preserve
  `server_tool_use` request counts and freeze live catalogue rates for fallback
  estimates, but never add an estimated search charge on top of
  `reported_cost_usd`. Web fetch currently has no separate Anthropic request
  fee; its returned content is already represented in token usage.
- **Do not make configuration convenient by coercion.** Boolean and fractional
  values are not integers, and a string is not a one-item list. Reject these at
  load time so a typo cannot silently change routing or concurrency.
- **The workspace is untrusted after provider launch.** Harness metadata writes
  require an already-claimed directory and must not follow a provider-created
  symlink. Validate workspace roots before creating children; a rejection must
  not leave mutations through an external symlink.
- **The parent-death guard owns hard escalation.** ProcessRunner may be gone
  after executor `SIGKILL`, so the guard itself must follow group `SIGTERM` with
  `SIGKILL`; otherwise a provider descendant can ignore termination and spend
  indefinitely.
- **Interactive calls use ProcessRunner too.** Do not regress console chat or
  `/project` stages to raw `create_subprocess_exec`: cancellation, timeouts and
  executor death must terminate the whole provider group, and response capture
  belongs in bounded private files rather than unbounded `communicate()` memory.
- **Never signal a PID merely because a file names it.** Detached browser state
  can be stale or tampered with. Verify the live `/proc` argv, expected profile,
  debug port and session leadership before killing the process group; publish
  replacement PID state atomically without following symlinks.
- **A credential request file is untrusted input.** Require a bounded regular
  file, matching filename/ID and a live same-user requester PID before showing
  a prompt. Answer only with the closed status vocabulary in a private,
  write-once regular file; never follow request or answer symlinks.
- **Host-state paths are not exempt from confinement.** Audit logs use private
  no-follow append, while clipboard destinations and browser profiles must be
  real directories. Validate before creation so rejecting a symlink does not
  mutate whatever it targets.
- **Bare `/project` never uses the current source directory as a run.** Allocate
  a fresh sibling under the console's `runs/` base and carry discovered config;
  preserve an exact path only when `--run-root` was explicitly supplied.
- **The live gate fixtures are evidence, not reusable state.** The verified
  behavior is: one failed module, one routing-only tier/attempt revision, then
  a real accepted provider artifact. `/project` was separately typed through a
  PTY and completed reason/code tasks; keep future smoke runs disposable too.

## Checkpoint discipline

At the end of every stage or phase, in this order: refresh graphify if structure
changed → update `project.md` (phase, decisions, next steps) → refresh
`overview.md` → add anything durable here. Then ask before committing. Never
push unprompted.
