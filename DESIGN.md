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

## Not built, on purpose

No executor, no adapters, no router, no governor, no CLI. Phase 2 begins when
you say go.
