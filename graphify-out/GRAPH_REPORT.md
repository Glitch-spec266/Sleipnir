# Graph Report - Sleipnir  (2026-08-18)

## Corpus Check
- 36 files · ~45,931 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 995 nodes · 2900 edges · 36 communities (35 shown, 1 thin omitted)
- Extraction: 84% EXTRACTED · 16% INFERRED · 0% AMBIGUOUS · INFERRED: 451 edges (avg confidence: 0.51)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `2fd7d15e`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- cli.py
- ProcessRunner
- test_pricing.py
- test_adapters.py
- AttemptWorkspace
- make_task
- test_budget.py
- Adapter
- test_schema.py
- _manifest_for
- Tier
- BillingMode
- parse_usage_line
- BudgetGovernor
- projection.py
- DispatchOutcome
- DispatchRequest
- ValueError
- schema.py
- Sleipnir — Phase 1 design
- Sleipnir — Overview
- Sleipnir — project instructions
- Task
- Sleipnir — Project State
- fetch_window_utilization
- TokenUsage
- scan_usage
- InputContract
- current_window
- conftest.py
- WindowUtilization
- Plan
- PriceSnapshot
- _HttpFailure
- extract_plan_json
- sleipnir

## God Nodes (most connected - your core abstractions)
1. `make_task()` - 80 edges
2. `Tier` - 75 edges
3. `Task` - 57 edges
4. `Executor` - 50 edges
5. `ScriptedAdapter` - 49 edges
6. `Adapter` - 46 edges
7. `Plan` - 42 edges
8. `FailureKind` - 39 edges
9. `DispatchRequest` - 38 edges
10. `AttemptStatus` - 38 edges

## Surprising Connections (you probably didn't know these)
- `test_artifact_ref_rejects_path_escape()` --uses--> `ArtifactRef`  [INFERRED]
  tests/test_schema.py → src/sleipnir/schema.py
- `test_thinking_tokens_cannot_exceed_output()` --uses--> `TokenUsage`  [INFERRED]
  tests/test_schema.py → src/sleipnir/schema.py
- `PlanningAdapter` --uses--> `DispatchRequest`  [INFERRED]
  tests/test_cli.py → src/sleipnir/adapters/base.py
- `ScriptedAdapter` --uses--> `DispatchRequest`  [INFERRED]
  tests/test_executor.py → src/sleipnir/adapters/base.py
- `PlanningAdapter` --uses--> `DispatchOutcome`  [INFERRED]
  tests/test_cli.py → src/sleipnir/adapters/base.py

## Import Cycles
- None detected.

## Communities (36 total, 1 thin omitted)

### Community 0 - "cli.py"
Cohesion: 0.05
Nodes (75): ArgumentParser, Namespace, DownshiftDecision, Budget governor: what the 5-hour window has cost, and what the plan will. Two…, # NOTE: `iterations` is deliberately ignored. It repeats the same counts, render_decisions(), build_adapters(), build_parser() (+67 more)

### Community 1 - "ProcessRunner"
Cohesion: 0.06
Nodes (38): Signals, _default_spawn(), ProcessResult, ProcessRunner, _pump(), Any, Path, Protocol (+30 more)

### Community 2 - "test_pricing.py"
Cohesion: 0.08
Nodes (48): CatalogUnavailableError, _first_int(), _float(), ModelCatalog, parse_models(), _per_mtok(), Any, ClientFactory (+40 more)

### Community 3 - "test_adapters.py"
Cohesion: 0.12
Nodes (50): Deterministic within a run, unique across runs. The run_id is load-bearing, not…, FailureKind, Why an attempt did not fully succeed. Separated from AttemptStatus so retry…, claude_adapter(), openrouter(), parametrize, Path, Adapter tests. Every adapter is driven end to end against a fake. The Claude… (+42 more)

### Community 4 - "AttemptWorkspace"
Cohesion: 0.07
Nodes (33): AcceptanceCheck, AttemptWorkspace, Any, Path, The subagent's self-written summary, if it produced one., Match what is on disk against what the task promised. Returns (produced,…, Files the task wrote but never declared. Recorded with an empty ``name`` rather…, Filesystem home for one attempt. Paths recorded in results.jsonl are always… (+25 more)

### Community 5 - "make_task"
Cohesion: 0.12
Nodes (57): ExecutorConfig, Path, RuntimeError, Append-only reader/writer for ``results.jsonl``. Deliberately synchronous.…, Raised when a non-final line fails to parse — that is real corruption, not the…, Append-only attempt log. The single source of truth for run state., Append one record and fsync it. fsync per record is the cost of the recovery…, Read every record, tolerating exactly one torn trailing line. A crash mid-… (+49 more)

### Community 6 - "test_budget.py"
Cohesion: 0.22
Nodes (24): config(), governor(), plan_of(), Path, Budget governor: usage parsing, window detection, projection, downshift. The…, A trivial task on a subscription backend is not cheap: the spawn alone costs…, The governor must never stop or reroute a run on a number it could not verify., Moving a task off longctx is a correctness failure, not a saving. (+16 more)

### Community 7 - "Adapter"
Cohesion: 0.18
Nodes (29): Sleipnir — a budget-aware agentic orchestrator. Phases 1–5 provide the schema,…, Adapter, Dispatch backends. Auth is always delegated to the official tool., invoke(), PlanningAdapter, fixture, Path, CLI: the five commands, end to end, with no network and no spend. (+21 more)

### Community 8 - "test_schema.py"
Cohesion: 0.09
Nodes (39): fold_results(), Recompute every task's status from the append-only result log. Records are…, AttemptStatus, Outcome of a single attempt. Deliberately small — *why* lives in FailureKind., RetryPolicy, budget(), finished(), make_chain() (+31 more)

### Community 9 - "_manifest_for"
Cohesion: 0.15
Nodes (13): _manifest_for(), parametrize, Manifest for a layered plan with every layer but the last two completed.…, This is the whole design in one assertion. A 600-task run must not cost the…, The orchestrator must never infer completeness from silence., Paths may cross into the manifest. Bytes may not., test_manifest_caps_are_enforced_not_merely_documented(), test_manifest_carries_no_artifact_contents() (+5 more)

### Community 10 - "Tier"
Cohesion: 0.14
Nodes (34): Tier to use on ``attempt`` (1-indexed). Falls back to ``base_tier``., Capability classes. A plan declares a tier; the router resolves a model. Fixed…, Tier, config(), model(), Router: tier -> model, filters, preference order, and explainability., The operator knows their own plan better than a price table does., Missing catalogue metadata is uncertainty, not evidence of insufficiency. (+26 more)

### Community 11 - "BillingMode"
Cohesion: 0.10
Nodes (22): ABC, AdapterError, BaseAdapter, RuntimeError, The adapter interface. An adapter's job is narrow on purpose: take a fully-…, One dispatch backend. Auth is never implemented here. The `claude` and `codex`…, Never let a credential reach a preview, a log, or an artifact., Adapter could not dispatch at all — a bug or a misconfiguration here, not a… (+14 more)

### Community 12 - "parse_usage_line"
Cohesion: 0.11
Nodes (21): parse_usage_line(), One deduplicated, priced-elsewhere assistant turn., Tokens charged against the 5-hour window. ``cache_read_weight`` exists because…, Extract one usage record, or None if this line does not carry usage. Tolerant…, UsageRecord, window_tokens(), assistant_line(), A parser that raises on an unfamiliar line makes the budget unavailable exactly… (+13 more)

### Community 13 - "BudgetGovernor"
Cohesion: 0.11
Nodes (13): BudgetGovernor, Projection, Estimates consumption and downshifts eligible tasks to stay inside it., The meter's own reading, cached briefly. None if unavailable. Disabled by…, Cost of everything still to run, at the tiers currently assigned., (window tokens, metered dollars) one attempt of ``task`` would cost. Fixed…, Assign a tier to every remaining task, downshifting until it fits. Downshifts…, The costliest task that can still move one rung down the ladder. (+5 more)

### Community 14 - "projection.py"
Cohesion: 0.12
Nodes (32): _alerts(), build_manifest(), _clip(), _evidence(), _fold_task(), _frontier(), _group_rollups(), _propagate_dependencies() (+24 more)

### Community 15 - "DispatchOutcome"
Cohesion: 0.15
Nodes (12): AsyncClient, Response, DispatchOutcome, Run the request to completion, a timeout, or a cancellation. Implementations…, What the adapter observed. Raw facts only, no derived accounting., materialize_file_blocks(), OpenRouterAdapter, Any (+4 more)

### Community 16 - "DispatchRequest"
Cohesion: 0.12
Nodes (14): DispatchPreview, DispatchRequest, Describe the dispatch without performing it. No network, no spawn., Everything an adapter needs. Fully resolved — adapters never route., What a dry run prints. Must be producible without spending anything., ClaudeAdapter, Any, Path (+6 more)

### Community 17 - "ValueError"
Cohesion: 0.22
Nodes (6): field_validator, model_validator, Self, _find_cycle(), Return one concrete cycle as a readable path, or None. Iterative (deep DAGs…, ValueError

### Community 18 - "schema.py"
Cohesion: 0.11
Nodes (23): BaseModel, assert_checks_supported(), Concurrency-capped DAG execution. The executor owns everything the adapters…, RunReport, AttemptStarted, CostEstimate, EscalationStep, estimate_tokens() (+15 more)

### Community 19 - "Sleipnir — Phase 1 design"
Cohesion: 0.06
Nodes (34): Dollars and window quota are different resources, Files, Folding a percentage back into tokens, Module layout, Not built, on purpose, Other decisions worth overruling, Phase 2 — executor, Phase 3 — router (+26 more)

### Community 20 - "Sleipnir — Overview"
Cohesion: 0.13
Nodes (14): File structure & modularity, Files created while running (not in the repo), How the budget governor decides, How the code works (the walkthrough), How the router chooses a model, How to add code / extend it, How to run / test locally, Known limitations / TODO (+6 more)

### Community 21 - "Sleipnir — project instructions"
Cohesion: 0.18
Nodes (10): Checkpoint discipline, Environment on this machine, Money and resources, Rules that will bite you if ignored, Security, Sleipnir — project instructions, The budget governor (Phase 4), The one invariant (+2 more)

### Community 22 - "Task"
Cohesion: 0.06
Nodes (43): ArtifactDirResolver, clip_summary(), Enforce the schema's hard summary cap at the write site. The schema *rejects*…, _artifact_section(), _describe_check(), _file_section(), IncludedInput, _output_section() (+35 more)

### Community 23 - "Sleipnir — Project State"
Cohesion: 0.18
Nodes (10): Current phase/stage, Decisions log, Environment on this machine, Goal, Next steps, Open questions, Phase 6 progress (2026-08-18), Phases (+2 more)

### Community 24 - "fetch_window_utilization"
Cohesion: 0.16
Nodes (19): allow_utilization_reads, fetch_window_utilization(), _int(), _parse_bucket(), Any, Read the CLI's OAuth access token, or None. Returns None for every failure…, Ask the meter. Returns None on any failure, never raises, never logs., read_oauth_token() (+11 more)

### Community 25 - "TokenUsage"
Cohesion: 0.16
Nodes (8): CodexAdapter, _first_int(), Any, Path, Walk every event for the last recognisable usage block. Deliberately structure-…, Token accounting, shaped to the *real* Claude usage record. Verified against…, Every token that entered the model, however it was billed., TokenUsage

### Community 26 - "scan_usage"
Cohesion: 0.28
Nodes (8): datetime, Path, Read every project transcript and return deduplicated usage records., scan_usage(), UsageScan, _warn(), Records recur across resumed sessions; 59% of the real corpus was duplicated.…, test_duplicate_request_ids_are_dropped()

### Community 27 - "InputContract"
Cohesion: 0.20
Nodes (9): ArtifactRef, InputContract, A request for another task's *full* output rather than its summary. Three…, Everything a task is permitted to read. Nothing else is provided to it., Planner-declared upper bound on input size. Feeds tier selection., test_artifact_budget_must_fit_max_input_bytes(), test_artifact_ref_must_name_a_real_output(), test_artifact_ref_rejects_wildcard_everything() (+1 more)

### Community 28 - "current_window"
Cohesion: 0.29
Nodes (7): current_window(), The active 5-hour block. Windows are anchored to first use and expire ``hours``…, Reporting full headroom is right; inventing consumption is not., test_a_gap_of_five_hours_starts_a_new_window(), test_empty_history_is_a_fresh_window(), test_no_recent_activity_reports_a_fresh_window(), test_window_is_anchored_to_first_use_not_a_rolling_lookback()

### Community 29 - "conftest.py"
Cohesion: 0.29
Nodes (6): no_credential_reads(), no_real_utilization_reads(), fixture, Test-suite guardrails. The budget governor reads real window utilisation from…, Never call the usage endpoint from a test. Returns ``None``, which is the same…, Belt and braces: the token must not be read from disk either. A test that needs…

### Community 30 - "WindowUtilization"
Cohesion: 0.25
Nodes (7): What the meter itself reports. Percentages, never tokens., Token limit consistent with ``used_tokens`` being this percentage., WindowUtilization, The reading is a percentage; everything downstream works in tokens. Solving…, Near zero the division explodes and would imply a wildly wrong limit., test_implied_limit_refuses_when_utilisation_is_too_small_to_divide_by(), test_implied_limit_solves_for_the_limit_matching_local_accounting()

### Community 31 - "Plan"
Cohesion: 0.22
Nodes (6): Plan, The task DAG. Validated as acyclic and referentially closed on load., All tasks transitively downstream of ``task_id``., make_layered(), _plan(), A wide layered DAG: every task in layer k depends on three in layer k-1. This…

### Community 32 - "PriceSnapshot"
Cohesion: 0.33
Nodes (5): PriceSnapshot, Per-million-token prices as fetched at dispatch time. Never populated from…, Cost of ``usage`` under this snapshot. Missing cache prices fall back to the…, test_cache_write_ttls_are_priced_separately(), test_missing_cache_prices_fall_back_without_undercounting()

### Community 33 - "_HttpFailure"
Cohesion: 0.33
Nodes (4): _HttpFailure, ClientFactory, Exception, An HTTP error status, carried out of the streaming path. Streaming used to…

### Community 34 - "extract_plan_json"
Cohesion: 0.40
Nodes (5): extract_plan_json(), Pull a JSON object out of a model response. Tries the whole response first,…, test_extract_plan_json_handles_bare_json(), test_extract_plan_json_handles_fenced_output(), test_extract_plan_json_returns_none_on_prose()

## Knowledge Gaps
- **57 isolated node(s):** `sleipnir`, `The one invariant`, `Rules that will bite you if ignored`, `The router (Phase 3)`, `Money and resources` (+52 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **1 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Tier` connect `Tier` to `cli.py`, `test_adapters.py`, `make_task`, `test_budget.py`, `test_schema.py`, `BillingMode`, `BudgetGovernor`, `DispatchRequest`, `schema.py`, `Task`?**
  _High betweenness centrality (0.076) - this node is a cross-community bridge._
- **Why does `Task` connect `Task` to `cli.py`, `ProcessRunner`, `AttemptWorkspace`, `make_task`, `test_schema.py`, `BillingMode`, `BudgetGovernor`, `projection.py`, `DispatchRequest`, `ValueError`, `schema.py`, `Plan`?**
  _High betweenness centrality (0.066) - this node is a cross-community bridge._
- **Why does `make_task()` connect `make_task` to `test_adapters.py`, `AttemptWorkspace`, `test_budget.py`, `test_schema.py`, `Tier`, `BillingMode`, `Task`, `InputContract`, `Plan`?**
  _High betweenness centrality (0.060) - this node is a cross-community bridge._
- **Are the 5 inferred relationships involving `make_task()` (e.g. with `ExpectedOutput` and `InputContract`) actually correct?**
  _`make_task()` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 50 inferred relationships involving `Tier` (e.g. with `DispatchPreview` and `DispatchRequest`) actually correct?**
  _`Tier` has 50 INFERRED edges - model-reasoned connections that need verification._
- **Are the 19 inferred relationships involving `Task` (e.g. with `DispatchRequest` and `BudgetGovernor`) actually correct?**
  _`Task` has 19 INFERRED edges - model-reasoned connections that need verification._
- **Are the 29 inferred relationships involving `Executor` (e.g. with `BaseAdapter` and `DispatchOutcome`) actually correct?**
  _`Executor` has 29 INFERRED edges - model-reasoned connections that need verification._