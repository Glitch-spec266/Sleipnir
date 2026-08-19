# Graph Report - Sleipnir  (2026-08-19)

## Corpus Check
- 60 files · ~80,162 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1568 nodes · 4524 edges · 57 communities (56 shown, 1 thin omitted)
- Extraction: 84% EXTRACTED · 16% INFERRED · 0% AMBIGUOUS · INFERRED: 723 edges (avg confidence: 0.51)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `74bb6269`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- make_task
- cli.py
- TaskStatus
- RoutingDecision
- test_pricing.py
- base.py
- test_adapters.py
- Adapter
- DispatchRequest
- Tier
- test_process.py
- ConsoleState
- Sleipnir — Phase 1 design
- Plan
- test_budget.py
- ValueError
- _canonical_json
- theme.py
- console.py
- scan_usage
- Executor
- test_capabilities.py
- chat.py
- test_console.py
- clipboard.py
- fold_results
- schema.py
- AttemptWorkspace
- Browser
- test_handoff.py
- fetch_window_utilization
- Secret
- current_window
- TerminalInputDecoder
- computer.py
- ProcessRunner
- TierRouter
- _manifest_for
- budget
- OpenRouterAdapter
- screenshot
- executor.py
- browser.py
- Sleipnir — Overview
- WindowUtilization
- test_schema.py
- InputContract
- Sleipnir — project instructions
- PriceSnapshot
- Task
- RetryPolicy
- process_guard.py
- process.py
- parse_usage_line
- Sleipnir — Project State
- handoff.py
- sleipnir

## God Nodes (most connected - your core abstractions)
1. `make_task()` - 110 edges
2. `Tier` - 101 edges
3. `Task` - 67 edges
4. `Adapter` - 65 edges
5. `ScriptedAdapter` - 63 edges
6. `Plan` - 59 edges
7. `Executor` - 56 edges
8. `plan_of()` - 55 edges
9. `AttemptFinished` - 51 edges
10. `TaskStatus` - 49 edges

## Surprising Connections (you probably didn't know these)
- `test_the_brain_is_asleep_exactly_when_a_run_owns_the_directory()` --uses--> `RunLock`  [INFERRED]
  tests/test_console.py → src/sleipnir/runlog.py
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

## Communities (57 total, 1 thin omitted)

### Community 0 - "make_task"
Cohesion: 0.07
Nodes (101): RuntimeError, An attempt path existed before the harness claimed this attempt., WorkspaceCollisionError, ExecutorConfig, apply_revision(), datetime, Validated, auditable plan revision application. The orchestrator may propose…, Append-only attempt log. The single source of truth for run state. (+93 more)

### Community 1 - "cli.py"
Cohesion: 0.05
Nodes (83): ArgumentParser, Namespace, render_decisions(), build_adapters(), build_parser(), CliError, cmd_apply_revision(), cmd_browser() (+75 more)

### Community 2 - "TaskStatus"
Cohesion: 0.10
Nodes (53): escalation_changes(), evaluate_gate(), GateVerdict, GroupState, GroupVerdict, StrEnum, The phase gate: what the brain is allowed to know when it wakes up. The…, Every group passed. The phase may be merged and the next one begun. (+45 more)

### Community 3 - "RoutingDecision"
Cohesion: 0.13
Nodes (12): datetime, Record a dispatch the governor refused. A denial is written to the log as a…, Compose the two-axis cost record. For subscription dispatches ``amount_usd`` is…, Phase 2 placeholder: a fixed tier -> (adapter, model) table from config. Phase…, StaticRouter, RoutingExplanation, CostEstimate, Dollars *and* window quota. Both are scarce; they are not interchangeable. (+4 more)

### Community 4 - "test_pricing.py"
Cohesion: 0.08
Nodes (47): _first_int(), _float(), ModelCatalog, _nonnegative_float(), parse_models(), _per_mtok(), Any, ClientFactory (+39 more)

### Community 5 - "base.py"
Cohesion: 0.09
Nodes (20): ABC, AdapterError, BaseAdapter, DispatchPreview, RuntimeError, The adapter interface. An adapter's job is narrow on purpose: take a fully-…, One dispatch backend. Auth is never implemented here. The `claude` and `codex`…, Describe the dispatch without performing it. No network, no spawn. (+12 more)

### Community 6 - "test_adapters.py"
Cohesion: 0.07
Nodes (69): Combine what the provider said with what actually landed on disk. The…, AttemptStatus, FailureKind, StrEnum, Outcome of a single attempt. Deliberately small — *why* lives in FailureKind., Why an attempt did not fully succeed. Separated from AttemptStatus so retry…, StreamReader, fake_spawner() (+61 more)

### Community 7 - "Adapter"
Cohesion: 0.13
Nodes (44): extract_plan_json(), Pull a JSON object out of a model response. Tries the whole response first,…, Adapter, Dispatch backends. Auth is always delegated to the official tool., invoke(), PlanningAdapter, fixture, parametrize (+36 more)

### Community 8 - "DispatchRequest"
Cohesion: 0.15
Nodes (12): DispatchRequest, Run the request to completion, a timeout, or a cancellation. Implementations…, Everything an adapter needs. Fully resolved — adapters never route., ClaudeAdapter, Any, Path, Spawner, Map the CLI's own status vocabulary onto FailureKind. (+4 more)

### Community 9 - "Tier"
Cohesion: 0.09
Nodes (57): ConfigError, ModelOption, _opt_float(), _opt_int(), _parse_backends(), _parse_models(), _parse_tiers(), Any (+49 more)

### Community 10 - "test_process.py"
Cohesion: 0.25
Nodes (16): skipif, Path, ProcessRunner: streaming, timeout, tree kill, cancellation., start_new_session is what makes killpg reach the CLI's children., Pumps must run concurrently with wait(); draining after exit would hang the…, run(), test_cancellation_kills_the_process_and_propagates(), test_large_output_does_not_deadlock() (+8 more)

### Community 11 - "ConsoleState"
Cohesion: 0.15
Nodes (15): _claude_dirs(), ConsoleState, Message, _project_argv(), Path, Everything the renderer needs, and nothing it does not. Notably absent: any…, The brain is asleep exactly when a run owns the directory. Derived, never…, A constant-size picture of the run, for the duty officer. This is the whole… (+7 more)

### Community 12 - "Sleipnir — Phase 1 design"
Cohesion: 0.05
Nodes (38): Dollars and window quota are different resources, Files, Folding a percentage back into tokens, Module layout, Not built, on purpose, Other decisions worth overruling, Phase 2 — executor, Phase 3 — router (+30 more)

### Community 13 - "Plan"
Cohesion: 0.06
Nodes (49): BudgetGovernor, DownshiftDecision, Projection, Estimates consumption and downshifts eligible tasks to stay inside it., The meter's own reading, cached briefly. None if unavailable. Disabled by…, Cost of everything still to run, at the tiers currently assigned., (window tokens, metered dollars) one attempt of ``task`` would cost. Fixed…, Assign a tier to every remaining task, downshifting until it fits. Downshifts… (+41 more)

### Community 14 - "test_budget.py"
Cohesion: 0.25
Nodes (22): config(), governor(), plan_of(), Path, Budget governor: usage parsing, window detection, projection, downshift. The…, A trivial task on a subscription backend is not cheap: the spawn alone costs…, The governor must never stop or reroute a run on a number it could not verify., Moving a task off longctx is a correctness failure, not a saving. (+14 more)

### Community 15 - "ValueError"
Cohesion: 0.16
Nodes (7): field_validator, Self, model_validator, _find_cycle(), model_validator, Return one concrete cycle as a readable path, or None. Iterative (deep DAGs…, ValueError

### Community 16 - "_canonical_json"
Cohesion: 0.40
Nodes (4): _canonical_json(), Any, Stable digest of the task's *meaning*. Completed results are keyed by (task_id,…, Stable JSON encoding for hashing: sorted keys, no incidental whitespace.

### Community 17 - "theme.py"
Cohesion: 0.13
Nodes (20): ease_back_out(), ease_power2_out(), fg(), _fit(), flicker_level(), frame(), logo_lines(), paint() (+12 more)

### Community 18 - "console.py"
Cohesion: 0.15
Nodes (21): apply_key(), _clean_paste(), _clip(), _paint(), paste_system_clipboard(), play_splash(), poll_secret_request(), The Sleipnir console: the window you actually talk to. What this is,… (+13 more)

### Community 19 - "scan_usage"
Cohesion: 0.18
Nodes (13): _parse_bucket(), datetime, Path, Read every project transcript and return deduplicated usage records., scan_usage(), UsageScan, _warn(), Records recur across resumed sessions; 59% of the real corpus was duplicated.… (+5 more)

### Community 21 - "Executor"
Cohesion: 0.14
Nodes (12): ConcurrentExecutionError, Executor, _pid_is_alive(), RuntimeError, Everything the run would dispatch, spending nothing. Walks the DAG in…, Execute while holding exclusive ownership of the run directory., Close attempts whose executor died before writing a terminal record. The start…, Cancel in-flight attempts and wait for each to record its own end. Each attempt… (+4 more)

### Community 22 - "test_capabilities.py"
Cohesion: 0.07
Nodes (7): audit_log(), _entries(), fake_ydotool(), fixture, Capability tests are hermetic by construction. Nothing here may inject a real…, Capture ydotool argv instead of running it., test_capture_records_only_the_label_and_length()

### Community 23 - "chat.py"
Cohesion: 0.11
Nodes (26): ask_claude(), ask_router(), ChatError, claude_argv(), extract_queued_instruction(), fast_lane_capable(), Path, RuntimeError (+18 more)

### Community 24 - "test_console.py"
Cohesion: 0.06
Nodes (8): parametrize, The console owns the terminal, so its failure modes are visual. Two things are…, test_an_unbroken_token_longer_than_the_pane_is_hard_split(), test_decline_or_malformed_check_routes_to_strong_model(), test_every_rendered_line_is_exactly_the_terminal_width(), test_narrow_terminal_still_renders(), test_the_brain_is_asleep_exactly_when_a_run_owns_the_directory(), _widths()

### Community 25 - "clipboard.py"
Cohesion: 0.26
Nodes (11): available(), ClipboardError, ClipboardPayload, offered_types(), Path, RuntimeError, Read text or images from the operator's Wayland clipboard. Keyboard-driven…, The desktop clipboard is unavailable or has no supported payload. (+3 more)

### Community 27 - "fold_results"
Cohesion: 0.21
Nodes (16): fold_results(), Recompute every task's status from the append-only result log. Records are…, finished(), make_chain(), t0000 -> t0001 -> ... Simple shape for status-folding tests., Replaying the log must not double-count cost — recovery depends on it., routing(), test_completed_task_is_superseded_when_spec_changes() (+8 more)

### Community 28 - "schema.py"
Cohesion: 0.10
Nodes (30): clip_summary(), Attempt workspace layout and output collection. One directory per attempt,…, Enforce the schema's hard summary cap at the write site. The schema *rejects*…, build_control_task(), control_instructions(), control_plan_context(), ControlDecision, ControlError (+22 more)

### Community 29 - "AttemptWorkspace"
Cohesion: 0.05
Nodes (52): AcceptanceCheck, ArtifactDirResolver, AttemptWorkspace, contained_regular_file(), Any, Path, Ensure an already-claimed workspace remains a real local directory., Atomically claim a new attempt directory; never reuse old contents. (+44 more)

### Community 30 - "Browser"
Cohesion: 0.15
Nodes (9): Browser, Any, An open browser the agent can drive. Deliberately a thin wrapper: it exposes…, Attach to the shared browser, starting it only if nobody has. Attaching rather…, Detach. Deliberately does **not** close the browser. Closing it here is what…, Really end the shared browser, discarding its live tabs. The profile on disk…, CapabilityError, RuntimeError (+1 more)

### Community 31 - "test_handoff.py"
Cohesion: 0.06
Nodes (13): Sleipnir — a budget-aware agentic orchestrator. Phases 1–5 provide the schema,…, fixture, The credential handoff, and the three live bugs that produced it. Every test…, A full-screen redraw loop that does not switch buffers appends every frame to…, Drawing only one row of the horse emblem renders as debris., requests_dir(), test_the_banner_is_all_or_nothing(), test_the_console_uses_the_alternate_screen() (+5 more)

### Community 32 - "fetch_window_utilization"
Cohesion: 0.19
Nodes (16): allow_utilization_reads, fetch_window_utilization(), Read the CLI's OAuth access token, or None. Returns None for every failure…, Ask the meter. Returns None on any failure, never raises, never logs., read_oauth_token(), _creds(), Skip the round trip rather than send a token that will 401., The usage endpoint is itself rate-limited — observed returning 429. A governor… (+8 more)

### Community 33 - "Secret"
Cohesion: 0.10
Nodes (13): Put a captured credential into a form field and wipe it. Separate from ``fill``…, Operator-authorised capabilities: the desk the robot sits at. Everything in…, capture(), BaseException, RuntimeError, TracebackType, Credentials that live for one keystroke burst and then stop existing. The rule…, A secret was used twice. Deliberately fatal rather than forgiving: re-use… (+5 more)

### Community 34 - "current_window"
Cohesion: 0.29
Nodes (7): current_window(), The active 5-hour block. Windows are anchored to first use and expire ``hours``…, Reporting full headroom is right; inventing consumption is not., test_a_gap_of_five_hours_starts_a_new_window(), test_empty_history_is_a_fresh_window(), test_no_recent_activity_reports_a_fresh_window(), test_window_is_anchored_to_first_use_not_a_rolling_lookback()

### Community 35 - "TerminalInputDecoder"
Cohesion: 0.40
Nodes (3): PastedText, Turn a byte stream into keys and atomic bracketed-paste events., TerminalInputDecoder

### Community 36 - "computer.py"
Cohesion: 0.16
Nodes (24): Any, Path, Append-only record of every privileged action taken on the host. Same…, record(), redact(), click(), copy(), ensure_daemon() (+16 more)

### Community 37 - "ProcessRunner"
Cohesion: 0.25
Nodes (7): ProcessRunner, Spawner, Runs one child process to completion, a timeout, or a cancellation., test_chat_rejects_an_unbounded_response_without_loading_it(), test_chat_timeout_terminates_the_process_group(), test_chat_turn_uses_guarded_process_runner_and_stdin(), test_project_stage_uses_guarded_process_runner()

### Community 38 - "TierRouter"
Cohesion: 0.15
Nodes (14): Backend, What a tier requires and which backends it prefers, in order., TierPolicy, CatalogSnapshot, ModelInfo, One comparable number for ranking. Tasks are input-heavy, so a plain average…, CandidateEval, _movement() (+6 more)

### Community 39 - "_manifest_for"
Cohesion: 0.14
Nodes (14): _manifest_for(), parametrize, Manifest for a layered plan with every layer but the last two completed.…, This is the whole design in one assertion. A 600-task run must not cost the…, The orchestrator must never infer completeness from silence., Paths may cross into the manifest. Bytes may not., test_manifest_caps_are_enforced_not_merely_documented(), test_manifest_carries_no_artifact_contents() (+6 more)

### Community 41 - "budget"
Cohesion: 0.22
Nodes (9): no_credential_reads(), no_real_utilization_reads(), fixture, Test-suite guardrails. The budget governor reads real window utilisation from…, Never call the usage endpoint from a test. Returns ``None``, which is the same…, Belt and braces: the token must not be read from disk either. A test that needs…, budget(), test_budget_headroom_is_none_when_limit_unknown() (+1 more)

### Community 42 - "OpenRouterAdapter"
Cohesion: 0.11
Nodes (17): AsyncClient, Response, _HttpFailure, materialize_file_blocks(), OpenRouterAdapter, Any, ClientFactory, Exception (+9 more)

### Community 43 - "screenshot"
Cohesion: 0.22
Nodes (9): CompletedProcess, Probe, Path, Capture the full screen to ``path``. The agent reads the resulting image…, Run a shell command as the operator, with the operator's environment. This is…, What this machine can actually do, for ``sleipnir doctor``., run(), screenshot() (+1 more)

### Community 44 - "executor.py"
Cohesion: 0.13
Nodes (18): DispatchOutcome, What the adapter observed. Raw facts only, no derived accounting., CodexAdapter, _first_int(), Any, Path, Spawner, Walk every event for the last recognisable usage block. Deliberately structure-… (+10 more)

### Community 45 - "browser.py"
Cohesion: 0.21
Nodes (13): available(), _cdp_alive(), ensure_browser(), _pid_matches_browser(), _publish_pid(), Path, Real browser control, for the work that only exists behind a login.…, Start the shared browser if it is not already running, and return its endpoint.… (+5 more)

### Community 46 - "Sleipnir — Overview"
Cohesion: 0.11
Nodes (18): File structure & modularity, Files created while running (not in the repo), Host control, in one paragraph, How the budget governor decides, How the code works (the walkthrough), How the router chooses a model, How to add code / extend it, How to run / test locally (+10 more)

### Community 47 - "WindowUtilization"
Cohesion: 0.25
Nodes (7): What the meter itself reports. Percentages, never tokens., Token limit consistent with ``used_tokens`` being this percentage., WindowUtilization, The reading is a percentage; everything downstream works in tokens. Solving…, Near zero the division explodes and would imply a wildly wrong limit., test_implied_limit_refuses_when_utilisation_is_too_small_to_divide_by(), test_implied_limit_solves_for_the_limit_matching_local_accounting()

### Community 48 - "test_schema.py"
Cohesion: 0.11
Nodes (19): make_layered(), _plan(), Phase 1 schema tests. The load-bearing test is…, A wide layered DAG: every task in layer k depends on three in layer k-1. This…, Re-tiering a task must NOT invalidate its completed work., The trap found in the real ~/.claude/projects record: input_tokens=2 while…, test_attempt_directories_never_collide(), test_downshift_must_be_explained() (+11 more)

### Community 49 - "InputContract"
Cohesion: 0.15
Nodes (13): ArtifactRef, InputContract, A request for another task's *full* output rather than its summary. Three…, Everything a task is permitted to read. Nothing else is provided to it., Planner-declared upper bound on input size. Feeds tier selection., Input contracts are enforced as filesystem security boundaries., test_dependency_artifact_symlink_cannot_escape_its_attempt(), test_repository_file_symlink_cannot_escape_the_run_root() (+5 more)

### Community 50 - "Sleipnir — project instructions"
Cohesion: 0.14
Nodes (13): Checkpoint discipline, Environment on this machine, Lessons from the first real console session, Money and resources, Rules that will bite you if ignored, Security, Sleipnir — project instructions, The budget governor (Phase 4) (+5 more)

### Community 51 - "PriceSnapshot"
Cohesion: 0.29
Nodes (6): PriceSnapshot, Token and server-tool prices as fetched at dispatch time. Never populated from…, Cost of ``usage`` under this snapshot. Missing cache prices fall back to the…, test_cache_write_ttls_are_priced_separately(), test_missing_cache_prices_fall_back_without_undercounting(), test_server_tool_requests_are_priced_separately_from_tokens()

### Community 52 - "Task"
Cohesion: 0.15
Nodes (11): Budget governor: what the 5-hour window has cost, and what the plan will. Two…, # NOTE: `iterations` is deliberately ignored. It repeats the same counts, Governor, Protocol, Budget control. Implemented by BudgetGovernor (Phase 4)., Tier -> concrete model. Implemented by TierRouter. ``downshift_reason`` is how…, Router, How much context this task plausibly needs. Driven by what the task *declared*… (+3 more)

### Community 53 - "RetryPolicy"
Cohesion: 0.33
Nodes (5): Tier to use on ``attempt`` (1-indexed). Falls back to ``base_tier``., RetryPolicy, test_escalation_ladder_cannot_exceed_retries(), test_retry_policy_rejects_non_retryable_kinds(), test_tier_for_attempt_walks_the_ladder()

### Community 54 - "process_guard.py"
Cohesion: 0.50
Nodes (4): _install_parent_death_signal(), main(), Run a provider CLI with a Linux parent-death signal installed. An executor can…, Install SIGTERM-on-parent-death, closing the setup race explicitly.

### Community 55 - "process.py"
Cohesion: 0.14
Nodes (13): Signals, _default_spawn(), ProcessResult, _pump(), Any, Path, Protocol, Async subprocess execution with timeout, streaming capture, and tree kill.… (+5 more)

### Community 56 - "parse_usage_line"
Cohesion: 0.11
Nodes (23): _int(), parse_usage_line(), Any, One deduplicated, priced-elsewhere assistant turn., Tokens charged against the 5-hour window. ``cache_read_weight`` exists because…, Extract one usage record, or None if this line does not carry usage. Tolerant…, UsageRecord, window_tokens() (+15 more)

### Community 57 - "Sleipnir — Project State"
Cohesion: 0.15
Nodes (12): Current phase/stage, Decisions log, Environment on this machine, Goal, Guarded fast lane and `/project` (2026-08-19), Next steps, Open questions, Phase 6 progress (2026-08-18) (+4 more)

### Community 58 - "handoff.py"
Cohesion: 0.18
Nodes (17): answer(), await_answer(), HandoffError, pending(), Path, RuntimeError, Asking the operator for a credential from a process that has no terminal. The…, Block until the console answers, and return its *status* only. Returns one of… (+9 more)

## Knowledge Gaps
- **67 isolated node(s):** `sleipnir`, `The one invariant`, `Rules that will bite you if ignored`, `The router (Phase 3)`, `Money and resources` (+62 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **1 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Tier` connect `Tier` to `make_task`, `cli.py`, `TaskStatus`, `RoutingDecision`, `base.py`, `TierRouter`, `test_adapters.py`, `DispatchRequest`, `executor.py`, `Plan`, `test_budget.py`, `test_schema.py`, `Task`, `Executor`, `RetryPolicy`, `chat.py`, `fold_results`, `schema.py`?**
  _High betweenness centrality (0.075) - this node is a cross-community bridge._
- **Why does `Plan` connect `Plan` to `make_task`, `cli.py`, `TaskStatus`, `RoutingDecision`, `ConsoleState`, `executor.py`, `test_budget.py`, `ValueError`, `test_schema.py`, `InputContract`, `console.py`, `Task`, `Executor`, `fold_results`, `schema.py`?**
  _High betweenness centrality (0.048) - this node is a cross-community bridge._
- **Why does `Task` connect `Task` to `make_task`, `cli.py`, `TaskStatus`, `RoutingDecision`, `base.py`, `TierRouter`, `DispatchRequest`, `executor.py`, `Plan`, `ValueError`, `_canonical_json`, `test_schema.py`, `Executor`, `process.py`, `schema.py`, `AttemptWorkspace`?**
  _High betweenness centrality (0.039) - this node is a cross-community bridge._
- **Are the 5 inferred relationships involving `make_task()` (e.g. with `ExpectedOutput` and `InputContract`) actually correct?**
  _`make_task()` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 73 inferred relationships involving `Tier` (e.g. with `DispatchPreview` and `DispatchRequest`) actually correct?**
  _`Tier` has 73 INFERRED edges - model-reasoned connections that need verification._
- **Are the 25 inferred relationships involving `Task` (e.g. with `DispatchRequest` and `BudgetGovernor`) actually correct?**
  _`Task` has 25 INFERRED edges - model-reasoned connections that need verification._
- **Are the 50 inferred relationships involving `Adapter` (e.g. with `BaseAdapter` and `DispatchPreview`) actually correct?**
  _`Adapter` has 50 INFERRED edges - model-reasoned connections that need verification._