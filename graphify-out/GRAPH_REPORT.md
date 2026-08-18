# Graph Report - Sleipnir  (2026-08-18)

## Corpus Check
- Corpus is ~45,000 words - fits in a single context window. You may not need a graph.

## Summary
- 909 nodes · 2772 edges · 44 communities (40 shown, 4 thin omitted)
- Extraction: 84% EXTRACTED · 16% INFERRED · 0% AMBIGUOUS · INFERRED: 431 edges (avg confidence: 0.51)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Community 0
- Community 1
- Community 2
- Community 3
- Community 4
- Community 5
- Community 6
- Community 7
- Community 8
- Community 9
- Community 10
- Community 11
- Community 12
- Community 13
- Community 14
- Community 15
- Community 16
- Community 17
- Community 18
- Community 19
- Community 20
- Community 21
- Community 22
- Community 23
- Community 24
- Community 25
- Community 26
- Community 27
- Community 28
- Community 29
- Community 30
- Community 31
- Community 32
- Community 33
- Community 34
- Community 35
- Community 36
- Community 37
- Community 38
- Community 39
- Community 40
- Community 41
- Community 42
- Community 43

## God Nodes (most connected - your core abstractions)
1. `make_task()` - 77 edges
2. `Tier` - 72 edges
3. `Task` - 57 edges
4. `Executor` - 47 edges
5. `ScriptedAdapter` - 47 edges
6. `Adapter` - 44 edges
7. `Plan` - 42 edges
8. `DispatchRequest` - 38 edges
9. `AttemptStatus` - 38 edges
10. `FailureKind` - 38 edges

## Surprising Connections (you probably didn't know these)
- `test_thinking_tokens_cannot_exceed_output()` --uses--> `TokenUsage`  [INFERRED]
  tests/test_schema.py → src/sleipnir/schema.py
- `PlanningAdapter` --uses--> `DispatchRequest`  [INFERRED]
  tests/test_cli.py → src/sleipnir/adapters/base.py
- `ScriptedAdapter` --uses--> `DispatchRequest`  [INFERRED]
  tests/test_executor.py → src/sleipnir/adapters/base.py
- `PlanningAdapter` --uses--> `DispatchOutcome`  [INFERRED]
  tests/test_cli.py → src/sleipnir/adapters/base.py
- `ScriptedAdapter` --uses--> `DispatchOutcome`  [INFERRED]
  tests/test_executor.py → src/sleipnir/adapters/base.py

## Import Cycles
- None detected.

## Communities (44 total, 4 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.07
Nodes (55): ArgumentParser, Namespace, render_decisions(), build_parser(), CliError, cmd_explain(), cmd_plan(), cmd_run() (+47 more)

### Community 1 - "Community 1"
Cohesion: 0.06
Nodes (38): Signals, _default_spawn(), ProcessResult, ProcessRunner, _pump(), Any, Path, Protocol (+30 more)

### Community 2 - "Community 2"
Cohesion: 0.08
Nodes (48): CatalogUnavailableError, _first_int(), _float(), ModelCatalog, parse_models(), _per_mtok(), Any, ClientFactory (+40 more)

### Community 3 - "Community 3"
Cohesion: 0.14
Nodes (47): claude_adapter(), openrouter(), parametrize, Path, Adapter tests. Every adapter is driven end to end against a fake. The Claude…, The whole point: `usage.input_tokens` is 10, `modelUsage` is 907., Prompts carry file contents; argv has a length limit and is world-readable., Regression: seeding on (task, attempt) alone made every resume collide with… (+39 more)

### Community 4 - "Community 4"
Cohesion: 0.07
Nodes (26): AttemptWorkspace, Any, Path, The subagent's self-written summary, if it produced one., Match what is on disk against what the task promised. Returns (produced,…, Files the task wrote but never declared. Recorded with an empty ``name`` rather…, Filesystem home for one attempt. Paths recorded in results.jsonl are always…, sha256_file() (+18 more)

### Community 5 - "Community 5"
Cohesion: 0.20
Nodes (39): ExecutorConfig, build(), plan_of(), Path, Executor: dependency order, concurrency cap, dry run, recovery, cancellation., A crash between the two must leave evidence that money was committed., Partial means *some* of the work exists. Nothing is a failure., The half-worked case from DESIGN.md Q2, end to end. (+31 more)

### Community 6 - "Community 6"
Cohesion: 0.12
Nodes (38): assistant_line(), config(), governor(), plan_of(), Path, Budget governor: usage parsing, window detection, projection, downshift. The…, Records recur across resumed sessions; 59% of the real corpus was duplicated.…, A trivial task on a subscription backend is not cheap: the spawn alone costs… (+30 more)

### Community 7 - "Community 7"
Cohesion: 0.14
Nodes (34): Sleipnir — a budget-aware agentic orchestrator. Phase 1 ships the state schema…, extract_plan_json(), Pull a JSON object out of a model response. Tries the whole response first,…, Adapter, Dispatch backends. Auth is always delegated to the official tool., invoke(), PlanningAdapter, fixture (+26 more)

### Community 8 - "Community 8"
Cohesion: 0.12
Nodes (30): fold_results(), _fold_task(), _propagate_dependencies(), Mark tasks blocked by unsatisfied deps, in topological order., Recompute every task's status from the append-only result log. Records are…, AttemptStatus, FailureKind, Folded status. Computed from results.jsonl — never stored in plan.json. (+22 more)

### Community 9 - "Community 9"
Cohesion: 0.08
Nodes (30): make_layered(), _manifest_for(), _plan(), parametrize, Phase 1 schema tests. The load-bearing test is…, The trap found in the real ~/.claude/projects record: input_tokens=2 while…, Manifest for a layered plan with every layer but the last two completed.…, This is the whole design in one assertion. A 600-task run must not cost the… (+22 more)

### Community 10 - "Community 10"
Cohesion: 0.23
Nodes (28): Capability classes. A plan declares a tier; the router resolves a model. Fixed…, Tier, config(), model(), Router: tier -> model, filters, preference order, and explainability., The operator knows their own plan better than a price table does., A subscription model has no catalogue entry and therefore reports no…, longctx sits outside the ladder: moving off it is a correctness failure, not a… (+20 more)

### Community 11 - "Community 11"
Cohesion: 0.13
Nodes (18): ABC, AdapterError, BaseAdapter, DispatchPreview, RuntimeError, The adapter interface. An adapter's job is narrow on purpose: take a fully-…, One dispatch backend. Auth is never implemented here. The `claude` and `codex`…, Never let a credential reach a preview, a log, or an artifact. (+10 more)

### Community 12 - "Community 12"
Cohesion: 0.11
Nodes (24): current_window(), _int(), _parse_bucket(), parse_usage_line(), Any, datetime, Path, Budget governor: what the 5-hour window has cost, and what the plan will. Two… (+16 more)

### Community 13 - "Community 13"
Cohesion: 0.15
Nodes (11): BudgetGovernor, DownshiftDecision, Projection, Estimates consumption and downshifts eligible tasks to stay inside it., The meter's own reading, cached briefly. None if unavailable. Disabled by…, Cost of everything still to run, at the tiers currently assigned., (window tokens, metered dollars) one attempt of ``task`` would cost. Fixed…, Assign a tier to every remaining task, downshifting until it fits. Downshifts… (+3 more)

### Community 14 - "Community 14"
Cohesion: 0.19
Nodes (21): _alerts(), build_manifest(), _clip(), _evidence(), _frontier(), _group_rollups(), datetime, Pure derivation of run state from plan + results. Deliberately I/O-free: no… (+13 more)

### Community 15 - "Community 15"
Cohesion: 0.18
Nodes (9): AsyncClient, Response, materialize_file_blocks(), OpenRouterAdapter, Any, Path, Consume the SSE stream, writing every raw line to disk as it lands. Streaming…, The single place an HTTP status becomes a FailureKind. The distinction is… (+1 more)

### Community 16 - "Community 16"
Cohesion: 0.17
Nodes (11): DispatchOutcome, What the adapter observed. Raw facts only, no derived accounting., ClaudeAdapter, Any, Path, Spawner, Map the CLI's own status vocabulary onto FailureKind., Sum `modelUsage` across every model the dispatch actually used. A dispatch can… (+3 more)

### Community 17 - "Community 17"
Cohesion: 0.22
Nodes (6): field_validator, model_validator, Self, _find_cycle(), Return one concrete cycle as a readable path, or None. Iterative (deep DAGs…, ValueError

### Community 18 - "Community 18"
Cohesion: 0.14
Nodes (17): BaseModel, EscalationStep, estimate_tokens(), EvidenceEntry, LlmJudgeCheck, PlanDefaults, PlanRevision, PriceSnapshot (+9 more)

### Community 19 - "Community 19"
Cohesion: 0.16
Nodes (12): assert_checks_supported(), Governor, Protocol, Budget control. Implemented by BudgetGovernor (Phase 4)., Tier -> concrete model. Implemented by TierRouter. ``downshift_reason`` is how…, Phase 2 placeholder: a fixed tier -> (adapter, model) table from config. Phase…, Router, StaticRouter (+4 more)

### Community 20 - "Community 20"
Cohesion: 0.22
Nodes (7): Executor, Everything the run would dispatch, spending nothing. Walks the DAG in…, Cancel in-flight attempts and wait for each to record its own end. Each attempt…, Which tier this attempt runs at, and why if it moved. Retry escalation outranks…, RunReport, Folded state for one task. Never persisted — always recomputed., TaskState

### Community 21 - "Community 21"
Cohesion: 0.24
Nodes (16): AcceptanceCheck, _check_command(), _check_files(), _check_json_schema(), _dispatch_check(), Any, Acceptance checks. Checks run *after* the adapter returns and decide whether…, A deliberate *subset* of JSON Schema: type, required, properties, items, enum,… (+8 more)

### Community 22 - "Community 22"
Cohesion: 0.25
Nodes (14): ArtifactDirResolver, _artifact_section(), _describe_check(), _file_section(), IncludedInput, _output_section(), Path, Resolve a task's InputContract into the exact prompt a subagent receives. This… (+6 more)

### Community 23 - "Community 23"
Cohesion: 0.16
Nodes (12): Path, RuntimeError, Append-only reader/writer for ``results.jsonl``. Deliberately synchronous.…, Raised when a non-final line fails to parse — that is real corruption, not the…, Append-only attempt log. The single source of truth for run state., Append one record and fsync it. fsync per record is the cost of the recovery…, Read every record, tolerating exactly one torn trailing line. A crash mid-…, Attempts with a start and no finish — in flight when the process died. (+4 more)

### Community 24 - "Community 24"
Cohesion: 0.19
Nodes (16): allow_utilization_reads, fetch_window_utilization(), Read the CLI's OAuth access token, or None. Returns None for every failure…, Ask the meter. Returns None on any failure, never raises, never logs., read_oauth_token(), _creds(), Skip the round trip rather than send a token that will 401., The usage endpoint is itself rate-limited — observed returning 429. A governor… (+8 more)

### Community 25 - "Community 25"
Cohesion: 0.15
Nodes (10): CodexAdapter, CodexInvocation, _first_int(), Any, Path, Spawner, Walk every event for the last recognisable usage block. Deliberately structure-…, How to call the CLI. Data, not code — correct this after verifying. (+2 more)

### Community 26 - "Community 26"
Cohesion: 0.21
Nodes (10): clip_summary(), Enforce the schema's hard summary cap at the write site. The schema *rejects*…, run_checks(), datetime, Concurrency-capped DAG execution. The executor owns everything the adapters…, Combine what the provider said with what actually landed on disk. The…, AttemptFinished, CheckResult (+2 more)

### Community 27 - "Community 27"
Cohesion: 0.16
Nodes (12): ArtifactRef, InputContract, A request for another task's *full* output rather than its summary. Three…, Everything a task is permitted to read. Nothing else is provided to it., Planner-declared upper bound on input size. Feeds tier selection., Using max_input_bytes would demand a 70k window for a task that reads nothing., test_required_context_follows_declared_inputs_not_the_global_cap(), test_artifact_budget_must_fit_max_input_bytes() (+4 more)

### Community 28 - "Community 28"
Cohesion: 0.20
Nodes (5): DispatchRequest, Run the request to completion, a timeout, or a cancellation. Implementations…, Describe the dispatch without performing it. No network, no spawn., Everything an adapter needs. Fully resolved — adapters never route., Give a filesystem-less model a way to produce files. Without this the model…

### Community 29 - "Community 29"
Cohesion: 0.22
Nodes (9): no_credential_reads(), no_real_utilization_reads(), fixture, Test-suite guardrails. The budget governor reads real window utilisation from…, Never call the usage endpoint from a test. Returns ``None``, which is the same…, Belt and braces: the token must not be read from disk either. A test that needs…, budget(), test_budget_headroom_is_none_when_limit_unknown() (+1 more)

### Community 30 - "Community 30"
Cohesion: 0.25
Nodes (7): What the meter itself reports. Percentages, never tokens., Token limit consistent with ``used_tokens`` being this percentage., WindowUtilization, The reading is a percentage; everything downstream works in tokens. Solving…, Near zero the division explodes and would imply a wildly wrong limit., test_implied_limit_refuses_when_utilisation_is_too_small_to_divide_by(), test_implied_limit_solves_for_the_limit_matching_local_accounting()

### Community 31 - "Community 31"
Cohesion: 0.25
Nodes (3): Plan, The task DAG. Validated as acyclic and referentially closed on load., All tasks transitively downstream of ``task_id``.

### Community 32 - "Community 32"
Cohesion: 0.29
Nodes (5): Record a dispatch the governor refused. A denial is written to the log as a…, Compose the two-axis cost record. For subscription dispatches ``amount_usd`` is…, CostEstimate, Dollars *and* window quota. Both are scarce; they are not interchangeable., test_partial_attempt_with_no_artifacts_is_a_failure()

### Community 33 - "Community 33"
Cohesion: 0.33
Nodes (4): _HttpFailure, ClientFactory, Exception, An HTTP error status, carried out of the streaming path. Streaming used to…

### Community 35 - "Community 35"
Cohesion: 0.33
Nodes (5): Tier to use on ``attempt`` (1-indexed). Falls back to ``base_tier``., RetryPolicy, test_escalation_ladder_cannot_exceed_retries(), test_retry_policy_rejects_non_retryable_kinds(), test_tier_for_attempt_walks_the_ladder()

### Community 36 - "Community 36"
Cohesion: 0.33
Nodes (3): Token accounting, shaped to the *real* Claude usage record. Verified against…, Every token that entered the model, however it was billed., TokenUsage

### Community 37 - "Community 37"
Cohesion: 0.40
Nodes (4): _canonical_json(), Any, Stable digest of the task's *meaning*. Completed results are keyed by (task_id,…, Stable JSON encoding for hashing: sorted keys, no incidental whitespace.

### Community 38 - "Community 38"
Cohesion: 0.50
Nodes (3): Manifest, The orchestrator's entire view of the world on re-invocation. Deliberately…, Exact bytes handed to the orchestrator. Size math measures this.

### Community 39 - "Community 39"
Cohesion: 0.67
Nodes (3): Tokens charged against the 5-hour window. ``cache_read_weight`` exists because…, window_tokens(), test_cache_read_weight_lowers_counted_consumption()

### Community 40 - "Community 40"
Cohesion: 0.67
Nodes (3): RuntimeError, Raised at startup, not per task. A plan that cannot be fully checked must fail…, UnsupportedCheckError

## Knowledge Gaps
- **1 isolated node(s):** `sleipnir`
  These have ≤1 connection - possible missing edges or undocumented components.
- **4 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Tier` connect `Community 10` to `Community 0`, `Community 3`, `Community 4`, `Community 6`, `Community 8`, `Community 9`, `Community 11`, `Community 12`, `Community 13`, `Community 18`, `Community 19`, `Community 20`, `Community 26`, `Community 27`, `Community 28`, `Community 32`, `Community 35`, `Community 41`, `Community 42`?**
  _High betweenness centrality (0.086) - this node is a cross-community bridge._
- **Why does `Task` connect `Community 19` to `Community 0`, `Community 1`, `Community 4`, `Community 8`, `Community 9`, `Community 10`, `Community 11`, `Community 12`, `Community 13`, `Community 14`, `Community 17`, `Community 18`, `Community 20`, `Community 21`, `Community 22`, `Community 26`, `Community 28`, `Community 31`, `Community 32`, `Community 37`, `Community 41`?**
  _High betweenness centrality (0.079) - this node is a cross-community bridge._
- **Why does `make_task()` connect `Community 10` to `Community 3`, `Community 4`, `Community 5`, `Community 6`, `Community 8`, `Community 9`, `Community 42`, `Community 19`, `Community 21`, `Community 27`?**
  _High betweenness centrality (0.069) - this node is a cross-community bridge._
- **Are the 5 inferred relationships involving `make_task()` (e.g. with `ExpectedOutput` and `InputContract`) actually correct?**
  _`make_task()` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 47 inferred relationships involving `Tier` (e.g. with `DispatchPreview` and `DispatchRequest`) actually correct?**
  _`Tier` has 47 INFERRED edges - model-reasoned connections that need verification._
- **Are the 19 inferred relationships involving `Task` (e.g. with `DispatchRequest` and `BudgetGovernor`) actually correct?**
  _`Task` has 19 INFERRED edges - model-reasoned connections that need verification._
- **Are the 27 inferred relationships involving `Executor` (e.g. with `BaseAdapter` and `DispatchOutcome`) actually correct?**
  _`Executor` has 27 INFERRED edges - model-reasoned connections that need verification._