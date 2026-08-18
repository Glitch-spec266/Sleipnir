# Sleipnir — Project State

_Started: 2026-08-18 · Last checkpoint: 2026-08-18, parallel builds merged_

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
| 6 | final gate: end-to-end live run, review, heavy pentest | **next** |
| 7 | live TUI dashboard (optional, post-release) | not started |

## Current phase/stage

Phases 1–5 complete. **217 tests passing.** Next: **Phase 6, the final gate.**

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

## Open questions

- **`codex` adapter flags are still unverified.** `codex` is installed here, so
  this is the last UNVERIFIED caveat in `DESIGN.md` and is cheap to clear.
- **`llm_judge` acceptance checks raise at executor construction**, deliberately.
  Revisit only if a plan needs them.
- **`server_tool_use` is captured but not yet priced.** Web search and fetch
  bill per request ($0.01 in the catalogue); no run has exercised them yet.
- **Should `code`-tier work start on a free model?** Cheapest, and it falls back
  when acceptance checks fail — but it leans hard on those checks.

## Next steps

1. **Phase 6 final gate:** one real end-to-end run — a genuine prompt, planned,
   dispatched, killed and resumed — then a full review and heavy pentest.
2. Verify the `codex` adapter's flags against the installed CLI.
3. Price `server_tool_use` requests into the cost model.
4. **Re-run semantic graphify extraction.** The graph is structurally accurate
   (909 nodes, AST-derived, rebuilt post-merge) but the doc↔code rationale links
   were dropped, because every markdown file was rewritten during the merge and
   the semantic cache invalidated.

## Environment on this machine

| Thing | State |
|---|---|
| `claude` CLI | present; `--model` takes `opus`/`sonnet`/`haiku` aliases |
| `codex` CLI | present, adapter flags unverified |
| `uv` | **not installed** — use `python3 -m venv` + `pip` |
| `.venv` | present, Python 3.14.6 |
| `OPENROUTER_API_KEY` | set in `~/.bashrc`, live-verified against a `:free` model |
| `ANTHROPIC_API_KEY` | deliberately unset — keeps billing on subscription |
| git identity | set **locally** to `Claude <noreply@anthropic.com>`, matching prior commits |
| branches | `parallel-build-local` preserves the superseded local build |
