# Sleipnir — Phase 1 design

Schema only. No executor, no router, no governor, no CLI.

Everything here follows from one invariant:

> **Subtask output never re-enters the orchestrator's context.**

If that holds, delegation is sublinear in cost. If it leaks anywhere — even
once, even "just this summary" — cost goes quadratic and the whole design is
worse than doing the work in one long Opus session. So the schema is built to
make the leak *structurally impossible* rather than merely discouraged: there
is no field anywhere in `Manifest` that can carry artifact content, and the
only free text that reaches it is a summary capped in characters at
construction time.

## Files

| File | Role | Mutability |
|---|---|---|
| `plan.json` | task DAG, declares **tiers** never models | versioned; edited only via a logged revision |
| `results.jsonl` | one record per attempt lifecycle event | strictly append-only |
| `revisions.jsonl` | audit log of mid-run re-planning | strictly append-only |
| `artifacts/task-<id>/attempt-NN/` | full transcripts and outputs | write-once per attempt |
| `Manifest` | the orchestrator's entire world view | **derived, never stored as truth** |

The keystone: **task status is never a stored field.** It is recomputed every
time by folding `results.jsonl` over `plan.json` (`projection.fold_results`).
There is no state file that can desync from the log, which is what makes crash
recovery a non-event rather than a repair job.

---

## The manifest size math

Measured, not estimated — `test_manifest_size_is_constant_in_task_count`
asserts this and will fail if a later phase reintroduces growth.

| tasks | manifest tokens | bytes | frontier | evidence | groups |
|---:|---:|---:|---:|---:|---:|
| 5 | 550 | 1,977 | 5 | 0 | 5 |
| 60 | 2,689 | 9,680 | 12 | 16 | 10 |
| 600 | 2,696 | 9,704 | 12 | 16 | 10 |
| 2,000 | 2,698 | 9,710 | 12 | 16 | 10 |
| 10,000 | 2,706 | 9,738 | 12 | 16 | 10 |

**From 60 to 10,000 tasks the manifest grows 17 tokens — 0.6%.** The residual
growth is digits: `t0060` becoming `t9999` costs a fraction of a token.

Where the 2,696 tokens go at n=600:

```
evidence   1610      16 dependency summaries × ~240 chars      <- the lever
frontier    624      12 actionable tasks × ~140 chars
groups      280      10 rollups
budget       61
totals       30
other        91      goal, ids, timestamps, alerts, truncation note
```

Each section is bounded by a cap in `ManifestCaps`, and `Manifest` **validates
against its own caps on construction** — an over-budget manifest cannot be
built, so the bound is an invariant rather than a convention. `evidence`
dominates; if the orchestrator needs a cheaper cycle, `evidence_summary_chars`
is the dial, and halving it removes ~800 tokens.

### Why this matters at run scale

The orchestrator is re-invoked once per cycle. Cumulative *input* tokens across
a full run, assuming one cycle per task and a 2,000-token base prompt:

| tasks | bounded manifest | naive (inline every completed summary) | |
|---:|---:|---:|---:|
| 60 | 281,760 | 595,800 | 2.1× |
| 200 | 939,200 | 5,626,000 | 6.0× |
| 600 | 2,817,600 | 48,078,000 | 17.1× |

Bounded is Θ(n). Naive is Θ(n²) — cycle *i* re-reads all *i* prior summaries.
At 60 tasks the naive approach merely wastes money; at 600 it is arithmetically
impossible inside any usage window. **The manifest is the entire reason this
project can exist**, which is why it gets the strictest validation in the
schema.

### The escape hatch, and its price

A constant-size manifest means the orchestrator **cannot see the whole DAG**.
It sees 12 actionable tasks, 10 group rollups, and counts. For scheduling that
is sufficient. For *re-planning* it is not — rewriting a DAG you cannot see is
guesswork.

Two options:

- **(A) Inline a compressed DAG skeleton** (`id: [deps] + status char`, ~8
  tokens/task). Cheap at n=60 (480 tokens), fatal at n=600 (4,800 tokens, past
  the ceiling). Reintroduces Θ(n) — quietly, which is the dangerous kind.
- **(B) Group rollups in the manifest; drill-down on demand.** The orchestrator
  sees per-group aggregates and calls a `read_plan(group=...)` tool when it
  actually intends to re-plan. Constant by default, expensive only when
  re-planning — which is rare.

**Recommendation: B**, which is what is implemented (`GroupRollup`, `Task.group`).
Re-planning happens a handful of times per run; paying for DAG visibility on
every one of 600 cycles to serve five of them is exactly the trade this project
exists to refuse. The cost of B is that `group` is now a field the planner must
assign sensibly — a bad grouping makes rollups uninformative. If you want A for
small plans, the honest version is a size-conditional: inline the skeleton when
`n ≤ 40`, drop to rollups above. Say the word and I will add it.

---

## Q1 — How does a task declare it needs another task's *full* output? What stops that becoming the default?

Declared via `InputContract.artifacts: list[ArtifactRef]`, versus the cheap
default `InputContract.summaries: list[TaskId]`.

The honest answer to "what stops it" is that **the question is less dangerous
than it looks**, and recognising why shaped the design:

**Full artifacts are fed to the *subagent*, never to the orchestrator.** The
orchestrator's context is unaffected by how much a subtask reads. So an
artifact ref cannot violate the core invariant — it can only cost subagent
input tokens. That reframes the defence from "prevent it" to "price it".

### Phase 15 delivery decision: stage once, reference by path

A declared dependency artifact is copied into the consumer attempt workspace,
then the worker prompt names that local path instead of pasting the file a
second time. This is the right division of responsibility: a worker can open
or execute its declared input, while a prompt should contain only the small
instruction needed to find it. The saved bytes are real provider input-token
headroom on every dependency-consuming attempt.

`ResolvedInput.total_bytes` deliberately still includes the actual staged
artifact bytes. It is the task's resolved-input budget, not a measurement of
prompt bytes; otherwise moving an artifact from the prompt to disk would make
the same declared dependency look artificially cheap. `prompt_bytes` records
the distinct, lower provider payload. A rare ref that would overwrite one of
the consumer's own outputs cannot be staged safely, so it remains inline as
the sole delivery path rather than becoming a false pre-existing output.

Four mechanisms, in order of how much work they do:

1. **It cannot reach the orchestrator.** `EvidenceEntry` carries
   `artifact_paths` — paths, never bytes. There is no field for content.
   Structural, not policy.
2. **It is priced at plan time.** `ArtifactRef.max_bytes` is mandatory and sums
   into `InputContract.declared_input_bytes`, which the Phase 3 router reads to
   pick a tier. A task pulling 400KB routes to `longctx` and is visibly
   expensive in `--explain` before a cent is spent.
3. **It requires a written justification.** `reason` is required, min 16 chars,
   and says why the 200-token summary is insufficient. The planner prompt will
   state that this field is read. Cheap, imperfect, but it converts a silent
   default into a deliberate act.
4. **It cannot be wildcarded.** `path` must name specific outputs; `**` and
   `**/*` are rejected, and exact paths are validated at load time against the
   producer's declared outputs — a typo fails on `Plan` construction rather
   than after a paid dispatch.

Plus an invariant worth more than it looks: **you may not read from a task you
do not declare as a dependency.** Both `summaries` and `artifacts` are
cross-checked against `depends_on`. Without this a task could race its own
input producer, and the failure would be nondeterministic and infuriating.

### Phase 15 graph scope decision

Do **not** point graphify explicitly at `CLAUDE.md`, `project.md`, or
`overview.md`. They are local operator working documents, not repository
source, and keeping them outside the graph preserves the same publication
boundary that keeps them out of Git. Durable architecture belongs in this
tracked design document and remains graphable; the local documents can change
without making private operational context part of the project knowledge graph.

---

## Q2 — How do we represent partial failure?

A task that half-worked is the normal case for long generations, not an edge
case, so it gets first-class representation rather than being flattened into
"failed".

Two orthogonal axes, deliberately separated:

- **`AttemptStatus`** — *what* happened: `succeeded | partial | failed | cancelled`
- **`FailureKind`** — *why*: `timeout | truncated | acceptance_failed | provider_error | tool_error | adapter_error | budget_denied | interrupted | dependency_failed | cancelled`

Collapsing these into one enum was the alternative, and it fails immediately:
retry policy needs to key on cause (a `timeout` is worth retrying, an
`acceptance_failed` is worth *escalating a tier*, a `budget_denied` must never
be retried at the same tier) while status needs to key on outcome. One enum
would force a cross-product.

Partial-ness is expressible because **outputs are named**. `OutputContract`
declares `ExpectedOutput` items with `required: bool`; a result records
`artifacts` produced and `missing_outputs` by name, plus per-check
`CheckResult`s. So "wrote the module but not the tests" is a precise state, not
a vibe.

Three invariants are enforced at validation time, because each represents a bug
I would otherwise have to debug from a corrupt log:

- a `succeeded` attempt cannot have `missing_outputs` (that is `partial`)
- a `partial` attempt with zero artifacts is a lie (that is `failed`)
- any non-`succeeded` attempt must carry a `failure_kind`

**Partial work is retained and reused.** Artifacts from a partial attempt stay
on disk, and `RetryPolicy.reuse_partial` (default `true`) feeds them back into
the retry so it *resumes* rather than restarts. This is the main reason
attempts get their own directories.

The folded task status distinguishes "partial with retries left" (→ `READY`,
scheduler picks it up) from "partial, retries exhausted" (→ `PARTIAL`,
orchestrator must decide: accept, re-spec, or escalate).

---

## Q3 — How does the orchestrator revise the plan mid-run without invalidating completed work?

Revision is a **logged diff**, never a rewrite. `plan.json` gets a new
`revision` number and a `PlanRevision` record is appended to `revisions.jsonl`.

The mechanism is `Task.spec_hash()` — a SHA-256 over only the fields that
determine what a task *means*:

```
included:  id, description, depends_on, inputs, outputs, acceptance
excluded:  tier, priority, timeout_s, retry, adapter_hint, group
```

That exclusion list is the whole trick. **Re-routing a task must never throw
away its finished output.** The budget governor downshifts tiers constantly; if
tier were part of the hash, every downshift would invalidate completed work and
the governor would fight the executor. `test_spec_hash_ignores_routing_fields`
pins this.

Results are keyed by `(task_id, spec_hash)`. On revision:

| change | effect on completed work |
|---|---|
| add task, add edge into a done task | none — always safe |
| non-semantic edit (tier, priority, timeout, retry) | none — hash unchanged, work stands |
| semantic edit to task X | X's results → `SUPERSEDED`; kept on disk, status resets |
| semantic edit to X, where descendants already completed | descendants → `STALE` |
| remove task | its results remain in the log; consumers must be revised too |

`STALE` is the interesting one and the reason it exists as a distinct status:
the descendant's output is *probably* still fine but was computed against an
input that has since changed. Auto-rerunning is wasteful; silently accepting is
wrong. So `STALE` is treated as satisfied for scheduling (it does not block
progress) but is surfaced in the manifest as an alert, making re-run an explicit
decision by whoever can actually judge it. `PlanRevision.superseded` and
`.staled` are computed by the applier rather than supplied by the model, so the
blast radius is recorded even when the orchestrator did not anticipate it.

### Sparse control cycles (implemented in Phase 7)

The executor does not wake Claude after every task. Workers run through every
safe automatic retry first; a reason-tier control call happens only when the DAG
reaches a terminal impasse. That call receives the constant-size `Manifest`
plus an on-demand drill-down capped at four urgent frontier task specs and
24,000 characters. It never receives artifacts, transcripts, or the full DAG.

The model returns `continue`, `stop`, or typed revision operations. Full task
payloads are required for add/retarget/respec, edge payloads are explicit, and
all changes are applied to a copy and revalidated as a complete DAG. The model
does not calculate which work became invalid: Sleipnir compares semantic hashes
and revision history locally, fsyncs the audit, then atomically replaces the
plan view. A maximum control-cycle count prevents an autonomous revision loop.

---

## Q4 — What if the process dies at task 40 of 60?

Nothing special happens, by construction.

1. **No derived state on disk.** Status is a fold of the log. There is no
   checkpoint to be stale or corrupt.
2. **`results.jsonl` is append-only with one JSON object per line**, fsynced per
   record. A crash mid-write leaves at most one torn trailing line; the reader
   discards an unparseable *final* line and logs it. A torn line anywhere else
   means real corruption and should fail loudly, not be repaired silently.
3. **In-flight tasks are visible.** This is why `results.jsonl` carries two
   record types rather than one: `AttemptStarted` is written *before* dispatch,
   `AttemptFinished` after. An attempt with a start and no finish is exactly a
   task that was running when the process died. With only terminal records —
   which is what the brief literally asked for — an in-flight task is
   indistinguishable from one never started, and `resume` cannot tell whether
   money was already spent. **This is a deliberate deviation from the spec's
   "one record per task attempt"; flagging it rather than quietly doing it.**
   Cost: `results.jsonl` is a tagged union and roughly doubles in line count.
4. **Re-running is always safe.** Artifacts go to
   `artifacts/task-<id>/attempt-NN/`, so a retry can never clobber a prior
   attempt's evidence. `resume` treats an orphaned attempt as `INTERRUPTED` and
   re-dispatches.
5. **Orphan subprocesses.** A `run.lock` carries pid + start time; `resume`
   checks liveness before assuming the old process is gone. Phase 2 concern,
   noted here so it does not get lost.
6. **Replay is idempotent.** Duplicate `(task_id, attempt)` records are
   last-write-wins, not summed, so cost accounting survives a replayed log
   (`test_fold_is_idempotent_over_replayed_records`).

Recovery at task 40 of 60 is therefore: read the log, fold, discover 39 done and
1 interrupted, re-dispatch that one, continue. Zero completed work is lost and
zero money is re-spent on it.

---

## What inspecting the real usage records changed

The brief said to inspect `~/.claude/projects/*.jsonl` before writing the Phase
4 parser and not assume its shape. I looked now, because it changes the *schema*
and not just the parser. From this session's own record (CLI 2.1.234):

```json
{"input_tokens": 2,
 "cache_creation_input_tokens": 47052,
 "cache_read_input_tokens": 0,
 "output_tokens": 901,
 "output_tokens_details": {"thinking_tokens": 611},
 "cache_creation": {"ephemeral_1h_input_tokens": 47052,
                    "ephemeral_5m_input_tokens": 0},
 "service_tier": "standard",
 "iterations": [ ... ]}
```

Five findings, four of which would have produced a silently wrong budget:

1. **`input_tokens` is 2 while cache-creation is 47,052.** A parser summing
   `input_tokens` under-counts this turn by ~23,000×. Nearly all input arrives
   as cache-creation tokens. `TokenUsage.total_input_tokens` sums all four
   input channels; a test pins it.
2. **Cache writes are split by TTL** (`ephemeral_1h` vs `ephemeral_5m`) and are
   priced differently. One `cache_write_tokens` field *cannot* produce a correct
   cost, so the schema keeps them separate.
3. **`iterations[]` repeats the same counts.** Summing both the top level and
   the iterations double-counts every turn.
4. **`requestId` and `isSidechain` exist**, so records can be deduped and
   subagent turns attributed. Records recur across resumed sessions; blind
   summing over-counts.
5. **There is no cost field at all.** Cost must be computed, which makes the
   OpenRouter pricing fetch load-bearing for the governor rather than
   decorative.

The parser will still be written defensively in Phase 4 — this is one CLI
version on one machine, and `BudgetSnapshot.parse_warnings` exists so
unrecognised shapes are *surfaced rather than swallowed*. A silently wrong
budget is worse than no budget.

### Dollars and window quota are different resources

`CostEstimate` carries `billing_mode`, `amount_usd`, **and** `window_tokens`.
A subscription-backed `claude -p` call costs ~$0 marginal but consumes the
5-hour window; an OpenRouter call costs dollars and consumes no window. The
governor is optimising over two scarce resources that are not interchangeable,
and a single "cost" number cannot express the trade. This is the thing that
makes "downshift to a cheaper tier" a real decision rather than an obvious one:
the cheapest option in dollars may be the one that runs you out of window.

---

## Things I decided that you should overrule if you disagree

- **Package is `sleipnir`; the brief says `orch`.** Phase 5 will expose both
  console scripts pointing at the same entry point unless you'd rather pick one.
- **`projection.py` exists in Phase 1.** Strictly it is derivation, not schema.
  Without it the bounded-manifest claim is unfalsifiable — you asked to see the
  size math, and a table I typed by hand is not evidence. It is pure: no I/O,
  no subprocess, no network. Delete it if you consider it scope creep.
- **`pytest` is the one dependency added beyond the sanctioned list.** Dev-only.
  Say so and I will drop it.
- **`CommandCheck` executes arbitrary shell from `plan.json`.** Fine on your own
  machine, but it means a plan file is executable content and must never be
  accepted from an untrusted source. Worth a line in the README before this
  grows a "share your plan" feature.
- **Token caps are enforced in characters** (`SUMMARY_MAX_CHARS = 720`) using a
  conservative 3.6 chars/token estimate, not a real tokenizer. Exact, cheap, no
  dependency, and over-estimates — which is the safe direction. If you want true
  token counts, that is a dependency decision and I will ask first.
- **Five tiers, unchanged.** `DOWNSHIFT_LADDER` orders four of them for the
  governor; `longctx` is deliberately excluded from the ladder because
  downshifting a task that needs a large context window is not a cost decision,
  it is a correctness failure.

---

# Phase 2 — executor

One adapter interface, three implementations, plus the machinery around them:
per-task timeout, concurrency cap (default 3), graceful cancellation,
structured stderr capture, and a dry-run mode.

**No Phase 1 schema changes were needed.** Every result the executor composes
fits the approved models as written. That is the strongest evidence available
that the schema was right.

## The one deliberate deviation from the brief

The brief says an adapter "returns a result record". Adapters return a
`DispatchOutcome` — raw observed facts — and the **executor** composes the
`AttemptFinished` record.

An adapter cannot build a correct record. It does not know the attempt's cost
(metered pricing is Phase 3's price snapshot), and it does not know whether
acceptance checks passed, because those run after it returns. Building the
record in the adapter would either duplicate that logic three times or drag
pricing into the adapter layer. So: adapters report, the executor decides.

## Module layout

```
adapters/base.py       DispatchRequest / DispatchOutcome / DispatchPreview
adapters/claude.py     `claude -p` headless      (verified against real output)
adapters/codex.py      `codex exec`              (verified against real output)
adapters/openrouter.py plain HTTP via httpx      (MockTransport-tested)
process.py             async subprocess: streaming, timeout, process-group kill
context.py             InputContract -> the exact prompt a subagent receives
artifacts.py           attempt workspace layout, output collection
checks.py              acceptance checks
runlog.py              append-only results.jsonl, fsync per record
executor.py            readiness, concurrency, cancellation, record composition
```

The fake used in tests sits at the **spawn boundary**, not in place of
`ProcessRunner`. Mocking one layer up would leave the streaming, timeout, drain
and kill logic — the code most likely to deadlock, and least likely to be
noticed doing it — completely untested.

## What the live run found that the fakes could not

118 tests passed against fakes. Then I ran it end to end against the real CLI
with two dependent tasks. It found three real defects.

**1. Session ids collided on every re-run.** The Claude adapter seeded its
`--session-id` from `uuid5(task, attempt)` — deterministic, for traceability.
Re-dispatching attempt 1 of a task therefore reused an id the CLI already knew:

```
Error: Session ID 150180bb-... is already in use.
```

Every resume and every re-run failed instantly with `provider_error`, burning a
retry before any work started. With `max_attempts=1` the task would simply die.
This is the recovery path the entire Phase 1 design exists to protect, and it
was broken in a way no fake would ever reproduce. Session ids now fold in a
per-execution `run_id`. Verified by clearing the log and re-dispatching attempt
1: 2/2 succeeded, no collision.

**2. Tool denials were downgrading successful work.** A subagent was denied one
tool, worked around it, and produced correct output — and the adapter marked it
`PARTIAL`/`tool_error` because `permission_denials` was non-empty, which would
trigger a retry that doubles the cost for nothing. Denials are now recorded in
`provider_meta` but do not change status. **Whether the work is good is decided
by what landed on disk**, via the output contract and acceptance checks — never
by provider chatter.

**3. The run report read `cost=$0.0000` after doing real work**, because
subscription spend is not metered spend. True but useless. `RunReport` now
carries `notional_usd` alongside `cost_usd`.

One further bug was caught by the fakes and is worth recording: on the
streaming path, every HTTP error funnelled through a generic `httpx.HTTPError`
handler and came out as retryable `PROVIDER_ERROR`. A permanent 400 would have
consumed the entire retry ladder on a request that could never succeed. Status
classification now has exactly one home.

## Two measured facts that should change Phase 3 and 4

**Every `claude -p` spawn costs ~30k cache-creation tokens before it does any
work** — about $0.022–0.06 on Haiku for a one-word answer. Two trivial tasks in
the smoke run cost $0.073 notional. That is a *floor*, independent of task
size.

The routing consequence is direct: **dispatching a `mechanical` task to
`claude -p` can cost more than the work is worth.** A rename or a formatting
pass should almost certainly go to OpenRouter, which has no system-prompt
overhead. Phase 3's router should treat per-dispatch fixed cost as a first-class
input, not just per-token price. (`--bare` may cut this overhead substantially,
but it requires `ANTHROPIC_API_KEY` and so changes the billing mode from
subscription to metered — worth measuring before relying on it.)

**Window-token accounting is currently ~10x too pessimistic.** Two trivial
tasks consumed ~300,000 `window_tokens`. Breaking down one:

```
input 1,130 + cache_write 7,284 + output 1,929 + cache_read 150,941 = 161,284
```

Cache reads are **94%** of it. The executor currently counts a cache-read token
as equal to an input token, when it is priced at roughly a tenth. This is the
top open question for Phase 4, and I did not change it unilaterally because it
touches the meaning of a Phase 1 field:

- **(A) Keep 1:1.** Over-estimates consumption, which is the safe direction for
  a governor — it downshifts too eagerly rather than blowing the window.
- **(B) Weight by price ratio** (cache reads at ~0.1). Much closer to true
  economic consumption, but if the real subscription limit counts raw tokens
  rather than weighted ones, this under-estimates and the governor overruns.

**Recommendation: (B), but only once Phase 4 has inspected what the 5-hour
window actually meters.** That inspection is already on the Phase 4 list, and
guessing before it is exactly the mistake the usage-record findings warn
against. Until then (A) stands, and it is stated in the field docs so nobody
reads the number as economic truth.

## Other decisions worth overruling

- **`codex` was verified against CLI 0.148.0 on 2026-08-18.** `exec`, optional
  `--model`, `--json`, and stdin prompt delivery match `CodexInvocation`.
  Configuring `@cli-default` omits the model override and lets the authenticated
  CLI choose an account-supported default; this avoids turning a deprecated
  alias into an outage while still permitting explicit pins. A
  live JSONL smoke call also established that `cached_input_tokens` is a subset
  of `input_tokens`; the adapter normalizes those into disjoint `TokenUsage`
  channels so the governor does not double-count cache reads. The parser still
  recurses rather than depending on an event envelope, and explicitly reports
  missing usage rather than pretending an unmeasured call was free.
- **Subscription pools are not interchangeable.** Codex outcomes carry
  `quota_pool="codex"` and aggregate into `codex_tokens`; they contribute zero
  to Claude's five-hour `window_tokens` projection and zero metered dollars. A
  live file-producing gate observed 48,456 Codex tokens while both other axes
  remained zero.
- **A hard-killed executor must not leave a spending orphan.** A live drill
  showed that `start_new_session=True` helps normal cancellation but lets the
  provider CLI survive when the executor itself receives `SIGKILL`. On Linux,
  real subprocesses now pass through `process_guard.py`, which installs
  `PR_SET_PDEATHSIG` and forwards parent death to the provider process group.
- **Revision invalidation must cause execution.** `SUPERSEDED` means the task's
  own contract changed; `STALE` means an upstream contract changed. The
  executor schedules both as work and requires freshly `DONE` dependencies,
  preventing a stale descendant chain from racing on pre-revision artifacts.
- **One terminal surface owns both worker and brain modes.** `tui --run` owns
  ordinary execution; `tui --orchestrate` owns the sparse control loop. Static
  and watch-only views do no catalogue/network work, and every untrusted value
  is reduced to printable characters before terminal rendering.
- **Sparse does not mean unaccounted.** Completed control calls append a
  `sleipnir-control` terminal record to the ordinary result log, including
  usage, quota pool, notional cost, and the decision artifact hash. Projection
  ignores that non-plan id; aggregate budget views intentionally include it.
- **OpenRouter models have no filesystem**, so they cannot write the files an
  `OutputContract` demands. The adapter appends a `file:<path>` fenced-block
  protocol to the prompt and materialises what comes back, confined to the
  attempt directory — a block claiming `../../.ssh/authorized_keys` is dropped,
  and there is a test for it.
- **`llm_judge` acceptance checks raise at executor construction**, not at task
  time. A plan that cannot be fully checked must fail before anything is
  dispatched; discovering at task 40 that a check silently passed because it
  was unimplemented is strictly worse than refusing the plan.
- **`json_schema` checks implement a documented subset** (type, required,
  properties, items, enum, bounds). Full JSON Schema means the `jsonschema`
  dependency, which is not on the sanctioned list. Anything richer should use a
  `CommandCheck` running a real validator, which keeps the dependency in the
  plan rather than in Sleipnir. Say the word if you want the real thing.
- **`httpx` was added** — sanctioned by constraint 2, but it is a new runtime
  dependency and you asked to be told.
- **`StaticRouter` is a placeholder** implementing the `Router` protocol from a
  fixed config table. It exists so the executor could be finished and tested
  without hardcoding a single model name in the executor itself. Phase 3
  replaces it.
- **The budget governor's seam is `Executor._launch`.** Phase 4 consults it
  before dispatch; nothing else in the executor needs to change.

## Not built, on purpose

No router (Phase 3), no budget governor (Phase 4), no CLI (Phase 5).

---

# Phases 3–5 — router, budget governor, CLI

## Phase 3 — router

`pricing.py` fetches the OpenRouter catalogue at runtime and caches it with a
TTL; `config.py` reads a TOML policy file; `router.py` resolves tier → model.
**No model name and no price appears anywhere in the source.**

Three refusals worth stating plainly:

- **A model with no usable price is dropped, never defaulted to zero.** A
  zero-priced model is one the router would always choose.
- **No catalogue and no cache is a hard error**, not a fallback to guesses. A
  stale cache *is* used (with `stale=True` surfaced), because an expired price
  beats no price.
- **An implausible price is treated as a units change, not a fact.** Prices are
  documented as USD per token; if that ever became per-million, every number
  would be 1e6 too high. Anything over $10,000/Mtok is dropped with a warning.

`--explain` prints every candidate with its accept/reject reason, not just the
winner. A router you cannot interrogate is a router you cannot trust with money.

The measured ~30k spawn overhead is encoded as `dispatch_overhead_tokens`, and
the shipped example config deliberately points `mechanical` at metered models
first for exactly that reason.

## Phase 4 — budget governor

Reading the real records changed the numbers by orders of magnitude. Against the
transcripts on this machine:

| | |
|---|---|
| naive sum of `input_tokens` | **436 tokens** |
| actual window consumption | **16,195,657 tokens** |
| duplicate records dropped | **173 of 294 (59%)** |

A parser that sums the obvious field under-reports by ~37,000×, and one that
skips deduplication over-reports by ~2.4×. Both traps are now covered by tests
built from the verified record shape.

Windows are **anchored to first use**, not a rolling lookback: a block starts at
the first turn following a gap of five hours. With no activity in range the
governor reports a fresh window rather than inventing consumption.

Downshift walks the ladder one rung at a time, most expensive task first,
recomputing after each step, and logs every decision with its reason.
`no_downshift` tasks are never moved, and `longctx` is never moved — leaving
that tier is a correctness failure, not a saving.

**The governor never acts on a number it could not verify.** With
`window_tokens_limit` unset there is no headroom, so it neither downshifts nor
denies. Denial is reserved for a known limit with zero headroom left.

## Phase 5 — CLI

`plan` / `run` / `status` / `resume` / `explain`, plus `--dry-run` and
`--explain`. `run` and `resume` are the same operation: status is a fold of the
append-only log, so recovery is the normal path rather than a special mode.

The planner is itself a dispatched task — a synthetic `Task` whose declared
output is `plan.json`, sent through the ordinary adapter path. It inherits the
same artifact layout, timeout handling and cost accounting as any other
dispatch, and the generated DAG is validated against the full Phase 1 schema, so
a cycle or a dangling dependency fails at planning time rather than at task 40.

Verified end to end against the real `claude` CLI: `plan` decomposed a prompt
into a 2-task DAG, `--dry-run --explain` showed the routing without spending,
`run` executed in dependency order, and `status` reported burn rate and a
441-token manifest.

## Still open

- **The OpenRouter catalogue shape is unverified.** This environment's egress
  policy denies CONNECT to openrouter.ai, so the parser was written defensively
  rather than confirmed. Verify on a machine with network access.
- **`codex` is verified** against CLI 0.148.0, including its JSONL usage shape.
- **`cache_read_weight` defaults to 1.0**, which over-estimates window
  consumption roughly tenfold. Still awaiting a decision on what the 5-hour
  window actually meters.

---

# The window is a percentage, not a token count

Phase 4 left one question open: does the 5-hour window meter raw tokens or
price-weighted ones? The two differ by **6.44×** on the local corpus, so
choosing wrong meant being six times out on the only resource that binds a
subscription run.

The question turned out to be unanswerable from the client side, and the reason
matters more than the answer.

Claude Code does not estimate window consumption. The binary contains
`fetchUtilization: GET /api/oauth/usage`, with buckets `five_hour`,
`seven_day`, `seven_day_opus`, `seven_day_sonnet`, `seven_day_overage_included`
and `org_spend_cap_reached`. A live call returns:

```json
{"five_hour": {"utilization": 77.0,
               "resets_at": "2026-08-18T18:20:00+00:00",
               "limit_dollars": null,
               "used_dollars": null,
               "remaining_dollars": null}}
```

**On a subscription every dollar field is null.** There is no token count and no
limit anywhere in the response — the true figure is a percentage and nothing
else. No amount of local summing could ever have reconstructed it, so both
candidate weightings were answers to a question that has no client-side form.

## Folding a percentage back into tokens

Everything downstream — `window_headroom_tokens`, `will_exhaust_window`, the
projection — works in tokens. Rather than introduce a second unit, the reading
is converted by solving for the limit that makes local accounting agree with the
true utilisation:

```
implied_limit = locally_measured_used / (utilisation / 100)
```

This is self-calibrating. Whatever weight the real meter gives cache reads is
absorbed into the implied limit, so the 1:1-versus-price-weighted question stops
mattering rather than being resolved. Below 5% utilisation the division is
numerically unstable and no limit is derived.

## The cost of reading it

The endpoint needs the OAuth token in `~/.claude/.credentials.json`, which is a
deliberate, operator-approved exception to the rule that Sleipnir never touches
provider credentials. It is kept narrow:

- read-only, and only `claudeAiOauth.accessToken` — the same file also holds
  unrelated plugin secrets, which are never read;
- the token is never logged, never persisted, never placed in an exception
  message, and never reaches a `BudgetSnapshot` or the `Manifest`;
- every failure — missing file, expired token, changed shape, HTTP error, no
  network — falls back to local estimation rather than raising.

Two facts found by using it, neither reachable from a fake:

- **The usage endpoint is itself rate-limited.** It returned 429 after a handful
  of calls in quick succession. A governor consulting it per dispatch would
  throttle itself out of the reading it depends on, which makes the TTL cache
  load-bearing rather than an optimisation. Failures are cached as hard as
  successes so a 429 cannot start a retry storm against the endpoint that
  reports throttling.
- **`expiresAt` is milliseconds**, and the token is checked against it before
  any request, so an expired credential costs no round trip.

The test suite is hermetic by default: `tests/conftest.py` patches both the
credential read and the endpoint call out, and a test that exercises them must
opt in with `@pytest.mark.allow_utilization_reads` and a mock transport. Before
that guard existed the suite made 18 authenticated calls per run, putting a
bearer token on the wire every time anyone typed `pytest`.

# What the second parallel build contributed

Phases 3–5 were built twice, independently, from the same design document. The
convergence was near-total — tier→model routing, transcript-derived budgets,
deduplication on `requestId`, ignoring `iterations[]` — which is good evidence
the architecture is determined by the problem rather than by taste.

The divergences were all in places the document was silent and only measurement
could settle:

- **The `-1` price sentinel.** Five live models (`openrouter/auto`, `fusion`,
  `pareto-code`, `bodybuilder`, `auto-beta`) price at `-1`, meaning "cost
  depends which model this routes to". The implausible-price guard is a `>`
  test and does not catch a negative, so unguarded they read as
  −$1,000,000/Mtok and win every routing decision forever.
- **Non-finite prices.** `float()` accepts `"Infinity"`, `"1e400"` and `"NaN"`.
  NaN is the dangerous one: every comparison against it is False, so it slips
  past both the negative and implausible guards and then silently destroys any
  ordering built on it.
- **`<synthetic>` records.** The CLI writes its own generated messages under
  that model name. They carry a usage block but were never API calls.
- **Attempt rotation.** `resolve()` now takes the *n*-th cheapest accepted
  candidate on attempt *n*. Free models rate-limit individually — one returned
  429 while its neighbour answered instantly — so an identical retry fails
  identically. It also yields tier escalation with no escalation ladder.
- **A refusal that did not refuse.** `test_no_catalogue_and_no_network_refuses_to_run`
  simulated "no network" by deleting the cache without blocking the fetch, so on
  any networked machine the live fetch succeeded and the refusal never fired.
  One of the project's stated safety guarantees was passing by accident.
