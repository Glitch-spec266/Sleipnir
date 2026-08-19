# Graph Report - Sleipnir  (2026-08-19)

## Corpus Check
- 51 files · ~66,070 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1225 nodes · 3709 edges · 45 communities (44 shown, 1 thin omitted)
- Extraction: 84% EXTRACTED · 16% INFERRED · 0% AMBIGUOUS · INFERRED: 608 edges (avg confidence: 0.51)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- CLI Command Surface
- Executor Test Suite
- Console Chat Transport
- Live Price Catalogue
- Backend & Tier Config
- Attempt Workspaces
- Plan Generation
- Task & Routing Schema
- Adapter Test Suite
- Adapter Base Contract
- Subprocess Runner
- Artifacts & Executor Core
- Package Root & Console Tests
- Budget Governor Core
- Budget Test Suite
- OpenRouter Adapter
- Bounded Manifest Projection
- Append-Only Result Log
- Schema Validators
- Executor Dispatch Loop
- Router Candidate Ranking
- Plan Revisions
- Status Folding
- Capability Test Suite
- Sparse Control Brain
- Claude Adapter
- Dispatch Request & Preview
- Usage Record Parsing
- OAuth Window Meter
- Budget Snapshot Rendering
- Governor & Router Protocols
- Browser Automation
- One-Shot Secrets
- Keyboard & Mouse Injection
- Host Computer Control
- Capability Package Surface
- Privileged Action Audit
- Cost Recording & Static Router
- Window Utilisation Maths
- Five-Hour Window Anchoring
- File Block Materialisation
- Codex Invocation
- Parent-Death Guard
- Spec Hashing
- Package Root Node

## God Nodes (most connected - your core abstractions)
1. `make_task()` - 109 edges
2. `Tier` - 89 edges
3. `Adapter` - 62 edges
4. `ScriptedAdapter` - 62 edges
5. `Task` - 59 edges
6. `Executor` - 56 edges
7. `plan_of()` - 55 edges
8. `Plan` - 52 edges
9. `AttemptFinished` - 51 edges
10. `AttemptStatus` - 47 edges

## Surprising Connections (you probably didn't know these)
- `test_thinking_tokens_cannot_exceed_output()` --uses--> `TokenUsage`  [INFERRED]
  tests/test_schema.py → src/sleipnir/schema.py
- `PlanningAdapter` --uses--> `DispatchRequest`  [INFERRED]
  tests/test_cli.py → src/sleipnir/adapters/base.py
- `ScriptedAdapter` --uses--> `DispatchRequest`  [INFERRED]
  tests/test_executor.py → src/sleipnir/adapters/base.py
- `PlanningAdapter` --uses--> `DispatchOutcome`  [INFERRED]
  tests/test_cli.py → src/sleipnir/adapters/base.py
- `test_orchestrate_applies_brain_revision_and_resumes_failed_work()` --uses--> `DispatchOutcome`  [INFERRED]
  tests/test_cli.py → src/sleipnir/adapters/base.py

## Import Cycles
- None detected.

## Communities (45 total, 1 thin omitted)

### Community 0 - "CLI Command Surface"
Cohesion: 0.07
Nodes (66): ArgumentParser, Namespace, render_decisions(), build_adapters(), build_parser(), CliError, cmd_apply_revision(), cmd_browser() (+58 more)

### Community 1 - "Executor Test Suite"
Cohesion: 0.14
Nodes (63): ExecutorConfig, build(), plan_of(), Path, Executor: dependency order, concurrency cap, dry run, recovery, cancellation., A crash between the two must leave evidence that money was committed., Partial means *some* of the work exists. Nothing is a failure., The half-worked case from DESIGN.md Q2, end to end. (+55 more)

### Community 2 - "Console Chat Transport"
Cohesion: 0.05
Nodes (56): ask_claude(), ask_router(), ChatError, claude_argv(), extract_queued_instruction(), Path, RuntimeError, Where a typed message goes. Sleipnir is a harness, not a model. This module is… (+48 more)

### Community 3 - "Live Price Catalogue"
Cohesion: 0.07
Nodes (49): CatalogSnapshot, CatalogUnavailableError, _first_int(), _float(), ModelCatalog, parse_models(), _per_mtok(), Any (+41 more)

### Community 4 - "Backend & Tier Config"
Cohesion: 0.09
Nodes (52): Backend, ConfigError, ModelOption, _opt_float(), _opt_int(), _parse_backends(), _parse_models(), _parse_tiers() (+44 more)

### Community 5 - "Attempt Workspaces"
Cohesion: 0.06
Nodes (34): ArtifactDirResolver, AttemptWorkspace, contained_regular_file(), Any, Path, RuntimeError, Ensure an already-claimed workspace remains a real local directory., Atomically claim a new attempt directory; never reuse old contents. (+26 more)

### Community 6 - "Plan Generation"
Cohesion: 0.10
Nodes (51): assemble_plan(), extract_plan_json(), generate_plan(), PlanningError, Path, RuntimeError, Pull a JSON object out of a model response. Tries the whole response first,…, Validate the model's task list into a real Plan. The model supplies only… (+43 more)

### Community 7 - "Task & Routing Schema"
Cohesion: 0.05
Nodes (47): ArtifactRef, PriceSnapshot, A request for another task's *full* output rather than its summary. Three…, Tier to use on ``attempt`` (1-indexed). Falls back to ``base_tier``., Per-million-token prices as fetched at dispatch time. Never populated from…, RetryPolicy, budget(), _manifest_for() (+39 more)

### Community 8 - "Adapter Test Suite"
Cohesion: 0.15
Nodes (48): claude_adapter(), openrouter(), Path, Adapter tests. Every adapter is driven end to end against a fake. The Claude…, The whole point: `usage.input_tokens` is 10, `modelUsage` is 907., Prompts carry file contents; argv has a length limit and is world-readable., Two executors started in the same second must not share a run_id., Observed live: a subagent was denied one tool, worked around it, and produced… (+40 more)

### Community 9 - "Adapter Base Contract"
Cohesion: 0.08
Nodes (30): ABC, AdapterError, BaseAdapter, DispatchOutcome, RuntimeError, The adapter interface. An adapter's job is narrow on purpose: take a fully-…, One dispatch backend. Auth is never implemented here. The `claude` and `codex`…, Run the request to completion, a timeout, or a cancellation. Implementations… (+22 more)

### Community 10 - "Subprocess Runner"
Cohesion: 0.10
Nodes (32): Signals, skipif, _default_spawn(), ProcessResult, ProcessRunner, _pump(), Any, Path (+24 more)

### Community 11 - "Artifacts & Executor Core"
Cohesion: 0.08
Nodes (35): clip_summary(), Attempt workspace layout and output collection. One directory per attempt,…, Enforce the schema's hard summary cap at the write site. The schema *rejects*…, Concurrency-capped DAG execution. The executor owns everything the adapters…, Combine what the provider said with what actually landed on disk. The…, build_planner_task(), planning_instructions(), Decomposition: one prompt in, a validated task DAG out. The planner is itself a… (+27 more)

### Community 12 - "Package Root & Console Tests"
Cohesion: 0.07
Nodes (11): Sleipnir — a budget-aware agentic orchestrator. Phases 1–5 provide the schema,…, The console owns the terminal, so its failure modes are visual. Two things are…, test_an_unbroken_token_longer_than_the_pane_is_hard_split(), test_every_rendered_line_is_exactly_the_terminal_width(), test_narrow_terminal_still_renders(), _widths(), The chrome must stay a pure function of the frame number, and must never be…, test_frame_lines_never_exceed_requested_width() (+3 more)

### Community 13 - "Budget Governor Core"
Cohesion: 0.11
Nodes (13): BudgetGovernor, Projection, Estimates consumption and downshifts eligible tasks to stay inside it., The meter's own reading, cached briefly. None if unavailable. Disabled by…, Cost of everything still to run, at the tiers currently assigned., (window tokens, metered dollars) one attempt of ``task`` would cost. Fixed…, Assign a tier to every remaining task, downshifting until it fits. Downshifts…, The costliest task that can still move one rung down the ladder. (+5 more)

### Community 14 - "Budget Test Suite"
Cohesion: 0.20
Nodes (27): config(), governor(), plan_of(), Path, Budget governor: usage parsing, window detection, projection, downshift. The…, Records recur across resumed sessions; 59% of the real corpus was duplicated.…, A trivial task on a subscription backend is not cheap: the spawn alone costs…, The governor must never stop or reroute a run on a number it could not verify. (+19 more)

### Community 15 - "OpenRouter Adapter"
Cohesion: 0.14
Nodes (12): AsyncClient, Response, _HttpFailure, OpenRouterAdapter, Any, ClientFactory, Exception, Consume the SSE stream, writing every raw line to disk as it lands. Streaming… (+4 more)

### Community 16 - "Bounded Manifest Projection"
Cohesion: 0.17
Nodes (25): _alerts(), build_manifest(), _clip(), _evidence(), _frontier(), _group_rollups(), datetime, Pure derivation of run state from plan + results. Deliberately I/O-free: no… (+17 more)

### Community 17 - "Append-Only Result Log"
Cohesion: 0.14
Nodes (20): Append-only reader/writer for ``results.jsonl``. Deliberately synchronous.…, Append-only attempt log. The single source of truth for run state., Append one record and fsync it. fsync per record is the cost of the recovery…, Read every record, tolerating exactly one torn trailing line. A crash mid-…, Attempts with a start and no finish — in flight when the process died., Raised when a non-final line fails to parse — that is real corruption, not the…, ResultLog, TornRecordError (+12 more)

### Community 18 - "Schema Validators"
Cohesion: 0.16
Nodes (7): field_validator, Self, model_validator, _find_cycle(), model_validator, Return one concrete cycle as a readable path, or None. Iterative (deep DAGs…, ValueError

### Community 19 - "Executor Dispatch Loop"
Cohesion: 0.15
Nodes (12): ConcurrentExecutionError, Executor, _pid_is_alive(), RuntimeError, Everything the run would dispatch, spending nothing. Walks the DAG in…, Execute while holding exclusive ownership of the run directory., Close attempts whose executor died before writing a terminal record. The start…, Cancel in-flight attempts and wait for each to record its own end. Each attempt… (+4 more)

### Community 20 - "Router Candidate Ranking"
Cohesion: 0.13
Nodes (13): What a tier requires and which backends it prefers, in order., TierPolicy, ModelInfo, One comparable number for ranking. Tasks are input-heavy, so a plain average…, CandidateEval, _movement(), Tier -> concrete model resolution. Tasks declare a *tier*. This module turns…, Return (accepted, all-evaluated). Accepted is already ranked. (+5 more)

### Community 21 - "Plan Revisions"
Cohesion: 0.21
Nodes (22): apply_revision(), persist_revision(), datetime, Path, RuntimeError, Validated, auditable plan revision application. The orchestrator may propose…, Append the audit first, then atomically replace the derived plan view., Latest revision that made each completed descendant stale. (+14 more)

### Community 22 - "Status Folding"
Cohesion: 0.15
Nodes (23): fold_results(), _fold_task(), _propagate_dependencies(), Mark tasks blocked by unsatisfied deps, in topological order., Recompute every task's status from the append-only result log. Records are…, Folded status. Computed from results.jsonl — never stored in plan.json., TaskStatus, finished() (+15 more)

### Community 23 - "Capability Test Suite"
Cohesion: 0.09
Nodes (7): audit_log(), _entries(), fake_ydotool(), fixture, Capability tests are hermetic by construction. Nothing here may inject a real…, Capture ydotool argv instead of running it., test_capture_records_only_the_label_and_length()

### Community 24 - "Sparse Control Brain"
Cohesion: 0.16
Nodes (17): build_control_task(), control_instructions(), control_plan_context(), ControlDecision, _extract_decision(), BaseModel, Sparse Claude control cycles over the bounded manifest. Workers execute…, Constant-bounded full specs for urgent frontier tasks only. (+9 more)

### Community 25 - "Claude Adapter"
Cohesion: 0.15
Nodes (11): ClaudeAdapter, Any, Path, Spawner, Map the CLI's own status vocabulary onto FailureKind., Sum `modelUsage` across every model the dispatch actually used. A dispatch can…, The model that produced the most output — the one that did the work if a…, Flags verified against `claude --help` (CLI 2.1.234). The prompt goes over… (+3 more)

### Community 26 - "Dispatch Request & Preview"
Cohesion: 0.15
Nodes (11): DispatchPreview, DispatchRequest, Describe the dispatch without performing it. No network, no spawn., Everything an adapter needs. Fully resolved — adapters never route., What a dry run prints. Must be producible without spending anything., CodexAdapter, _first_int(), Any (+3 more)

### Community 27 - "Usage Record Parsing"
Cohesion: 0.12
Nodes (20): _int(), parse_usage_line(), Any, One deduplicated, priced-elsewhere assistant turn., Extract one usage record, or None if this line does not carry usage. Tolerant…, UsageRecord, assistant_line(), A parser that raises on an unfamiliar line makes the budget unavailable exactly… (+12 more)

### Community 28 - "OAuth Window Meter"
Cohesion: 0.19
Nodes (16): allow_utilization_reads, fetch_window_utilization(), Read the CLI's OAuth access token, or None. Returns None for every failure…, Ask the meter. Returns None on any failure, never raises, never logs., read_oauth_token(), _creds(), Skip the round trip rather than send a token that will 401., The usage endpoint is itself rate-limited — observed returning 429. A governor… (+8 more)

### Community 29 - "Budget Snapshot Rendering"
Cohesion: 0.17
Nodes (13): DownshiftDecision, _parse_bucket(), datetime, Path, Budget governor: what the 5-hour window has cost, and what the plan will. Two…, # NOTE: `iterations` is deliberately ignored. It repeats the same counts, Read every project transcript and return deduplicated usage records., Tokens charged against the 5-hour window. ``cache_read_weight`` exists because… (+5 more)

### Community 30 - "Governor & Router Protocols"
Cohesion: 0.17
Nodes (8): Governor, Protocol, Budget control. Implemented by BudgetGovernor (Phase 4)., Tier -> concrete model. Implemented by TierRouter. ``downshift_reason`` is how…, Router, RunReport, Attempts never share a directory, so a re-run can never clobber evidence from a…, Task

### Community 31 - "Browser Automation"
Cohesion: 0.18
Nodes (4): Browser, Any, Path, An open browser the agent can drive. Deliberately a thin wrapper: it exposes…

### Community 32 - "One-Shot Secrets"
Cohesion: 0.15
Nodes (6): Put a captured credential into a form field and wipe it. Separate from ``fill``…, BaseException, TracebackType, A one-shot credential. Every representation hook is overridden. Without that,…, Yield the plaintext exactly once, then wipe the buffer., Secret

### Community 33 - "Keyboard & Mouse Injection"
Cohesion: 0.23
Nodes (13): CapabilityError, click(), ensure_daemon(), key(), move_mouse(), RuntimeError, Start ``ydotoold`` if it is not already listening. Started detached and left…, Press a chord, e.g. ``key("ctrl", "shift", "t")``. Modifiers are held for the… (+5 more)

### Community 34 - "Host Computer Control"
Cohesion: 0.23
Nodes (10): CompletedProcess, Probe, Path, Keyboard, mouse, screen and shell control of the host machine. Wayland is the…, Capture the full screen to ``path``. The agent reads the resulting image…, Run a shell command as the operator, with the operator's environment. This is…, What this machine can actually do, for ``sleipnir doctor``., run() (+2 more)

### Community 35 - "Capability Package Surface"
Cohesion: 0.18
Nodes (9): available(), Real browser control, for the work that only exists behind a login.…, Operator-authorised capabilities: the desk the robot sits at. Everything in…, capture(), RuntimeError, Credentials that live for one keystroke burst and then stop existing. The rule…, A secret was used twice. Deliberately fatal rather than forgiving: re-use…, Prompt the operator for a credential with echo disabled. Reads straight into a… (+1 more)

### Community 36 - "Privileged Action Audit"
Cohesion: 0.27
Nodes (9): Any, Path, Append-only record of every privileged action taken on the host. Same…, record(), redact(), Type into whatever window currently has focus. ``key_delay_ms`` is not…, type_text(), Type a captured credential into whatever window has focus, then wipe. This is… (+1 more)

### Community 37 - "Cost Recording & Static Router"
Cohesion: 0.24
Nodes (6): datetime, Compose the two-axis cost record. For subscription dispatches ``amount_usd`` is…, Phase 2 placeholder: a fixed tier -> (adapter, model) table from config. Phase…, StaticRouter, Everything `sleipnir explain <task-id>` needs. Written once per attempt., RoutingDecision

### Community 38 - "Window Utilisation Maths"
Cohesion: 0.25
Nodes (7): What the meter itself reports. Percentages, never tokens., Token limit consistent with ``used_tokens`` being this percentage., WindowUtilization, The reading is a percentage; everything downstream works in tokens. Solving…, Near zero the division explodes and would imply a wildly wrong limit., test_implied_limit_refuses_when_utilisation_is_too_small_to_divide_by(), test_implied_limit_solves_for_the_limit_matching_local_accounting()

### Community 39 - "Five-Hour Window Anchoring"
Cohesion: 0.29
Nodes (7): current_window(), The active 5-hour block. Windows are anchored to first use and expire ``hours``…, Reporting full headroom is right; inventing consumption is not., test_a_gap_of_five_hours_starts_a_new_window(), test_empty_history_is_a_fresh_window(), test_no_recent_activity_reports_a_fresh_window(), test_window_is_anchored_to_first_use_not_a_rolling_lookback()

### Community 40 - "File Block Materialisation"
Cohesion: 0.33
Nodes (6): materialize_file_blocks(), Path, Write ```file:<path> blocks into ``target_dir``. Paths are confined to the…, parametrize, test_file_blocks_cannot_escape_the_attempt_directory(), test_file_blocks_write_nested_paths()

### Community 41 - "Codex Invocation"
Cohesion: 0.40
Nodes (3): CodexInvocation, Spawner, How to call the CLI. Data, not dispatch logic.

### Community 42 - "Parent-Death Guard"
Cohesion: 0.50
Nodes (4): _install_parent_death_signal(), main(), Run a provider CLI with a Linux parent-death signal installed. An executor can…, Install SIGTERM-on-parent-death, closing the setup race explicitly.

### Community 43 - "Spec Hashing"
Cohesion: 0.40
Nodes (4): _canonical_json(), Any, Stable digest of the task's *meaning*. Completed results are keyed by (task_id,…, Stable JSON encoding for hashing: sorted keys, no incidental whitespace.

## Knowledge Gaps
- **1 isolated node(s):** `sleipnir`
  These have ≤1 connection - possible missing edges or undocumented components.
- **1 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Tier` connect `Backend & Tier Config` to `CLI Command Surface`, `Executor Test Suite`, `Console Chat Transport`, `Cost Recording & Static Router`, `Task & Routing Schema`, `Adapter Test Suite`, `Adapter Base Contract`, `Artifacts & Executor Core`, `Budget Governor Core`, `Budget Test Suite`, `Executor Dispatch Loop`, `Router Candidate Ranking`, `Plan Revisions`, `Status Folding`, `Sparse Control Brain`, `Dispatch Request & Preview`, `Budget Snapshot Rendering`, `Governor & Router Protocols`?**
  _High betweenness centrality (0.072) - this node is a cross-community bridge._
- **Why does `make_task()` connect `Executor Test Suite` to `Backend & Tier Config`, `Attempt Workspaces`, `Task & Routing Schema`, `Adapter Test Suite`, `Artifacts & Executor Core`, `Budget Test Suite`, `Plan Revisions`, `Status Folding`, `Sparse Control Brain`, `Governor & Router Protocols`?**
  _High betweenness centrality (0.061) - this node is a cross-community bridge._
- **Why does `Task` connect `Governor & Router Protocols` to `CLI Command Surface`, `Executor Test Suite`, `Attempt Workspaces`, `Cost Recording & Static Router`, `Task & Routing Schema`, `Adapter Base Contract`, `Subprocess Runner`, `Artifacts & Executor Core`, `Spec Hashing`, `Budget Governor Core`, `Bounded Manifest Projection`, `Schema Validators`, `Executor Dispatch Loop`, `Router Candidate Ranking`, `Status Folding`, `Sparse Control Brain`, `Dispatch Request & Preview`, `Budget Snapshot Rendering`?**
  _High betweenness centrality (0.059) - this node is a cross-community bridge._
- **Are the 5 inferred relationships involving `make_task()` (e.g. with `ExpectedOutput` and `InputContract`) actually correct?**
  _`make_task()` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 61 inferred relationships involving `Tier` (e.g. with `DispatchPreview` and `DispatchRequest`) actually correct?**
  _`Tier` has 61 INFERRED edges - model-reasoned connections that need verification._
- **Are the 47 inferred relationships involving `Adapter` (e.g. with `BaseAdapter` and `DispatchPreview`) actually correct?**
  _`Adapter` has 47 INFERRED edges - model-reasoned connections that need verification._
- **Are the 11 inferred relationships involving `ScriptedAdapter` (e.g. with `test_orchestrate_applies_brain_revision_and_resumes_failed_work()` and `DispatchOutcome`) actually correct?**
  _`ScriptedAdapter` has 11 INFERRED edges - model-reasoned connections that need verification._