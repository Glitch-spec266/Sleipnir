# Graph Report - Sleipnir  (2026-08-19)

## Corpus Check
- 60 files · ~81,445 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1576 nodes · 4537 edges · 58 communities (56 shown, 2 thin omitted)
- Extraction: 84% EXTRACTED · 16% INFERRED · 0% AMBIGUOUS · INFERRED: 724 edges (avg confidence: 0.51)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `461630b2`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- make_task
- cli.py
- TaskStatus
- AttemptStatus
- test_pricing.py
- DispatchRequest
- test_adapters.py
- Adapter
- ClaudeAdapter
- Tier
- fake_spawner
- console.py
- Sleipnir — Phase 1 design
- budget.py
- test_budget.py
- ValueError
- Plan
- theme.py
- Task
- context.py
- SleipnirConfig
- Executor
- test_capabilities.py
- chat.py
- test_console.py
- clipboard.py
- planner.py
- make_chain
- orchestrator.py
- AttemptWorkspace
- Browser
- test_handoff.py
- ArtifactRef
- Secret
- _canonical_json
- TerminalInputDecoder
- computer.py
- parametrize
- TierRouter
- test_schema.py
- BaseModel
- budget
- DispatchOutcome
- screenshot
- test_total_input_counts_cache_creation_tokens
- browser.py
- Sleipnir — Overview
- fakes.py
- _manifest_for
- schema.py
- Sleipnir — project instructions
- ConsoleState
- process_guard.py
- ProcessRunner
- Sleipnir — Project State
- handoff.py
- sleipnir
- RetryPolicy

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

## Communities (58 total, 2 thin omitted)

### Community 0 - "make_task"
Cohesion: 0.12
Nodes (70): ExecutorConfig, Append-only attempt log. The single source of truth for run state., ResultLog, Two executors started in the same second must not share a run_id., test_executor_run_ids_are_unique(), build(), plan_of(), Path (+62 more)

### Community 1 - "cli.py"
Cohesion: 0.07
Nodes (65): ArgumentParser, Namespace, render_decisions(), build_adapters(), build_parser(), CliError, cmd_apply_revision(), cmd_browser() (+57 more)

### Community 2 - "TaskStatus"
Cohesion: 0.10
Nodes (53): escalation_changes(), evaluate_gate(), GateVerdict, GroupState, GroupVerdict, StrEnum, The phase gate: what the brain is allowed to know when it wakes up. The…, Every group passed. The phase may be merged and the next one begun. (+45 more)

### Community 3 - "AttemptStatus"
Cohesion: 0.23
Nodes (14): Combine what the provider said with what actually landed on disk. The…, AttemptStatus, FailureKind, StrEnum, Outcome of a single attempt. Deliberately small — *why* lives in FailureKind., Why an attempt did not fully succeed. Separated from AttemptStatus so retry…, Exception, finished() (+6 more)

### Community 4 - "test_pricing.py"
Cohesion: 0.07
Nodes (50): CatalogUnavailableError, _first_int(), _float(), ModelCatalog, _nonnegative_float(), parse_models(), _per_mtok(), Any (+42 more)

### Community 5 - "DispatchRequest"
Cohesion: 0.07
Nodes (33): ABC, AdapterError, BaseAdapter, DispatchPreview, DispatchRequest, RuntimeError, The adapter interface. An adapter's job is narrow on purpose: take a fully-…, One dispatch backend. Auth is never implemented here. The `claude` and `codex`… (+25 more)

### Community 6 - "test_adapters.py"
Cohesion: 0.14
Nodes (50): claude_adapter(), openrouter(), parametrize, Path, Adapter tests. Every adapter is driven end to end against a fake. The Claude…, The whole point: `usage.input_tokens` is 10, `modelUsage` is 907., Prompts carry file contents; argv has a length limit and is world-readable., Regression: seeding on (task, attempt) alone made every resume collide with… (+42 more)

### Community 7 - "Adapter"
Cohesion: 0.13
Nodes (44): extract_plan_json(), Pull a JSON object out of a model response. Tries the whole response first,…, Adapter, Dispatch backends. Auth is always delegated to the official tool., invoke(), PlanningAdapter, fixture, parametrize (+36 more)

### Community 8 - "ClaudeAdapter"
Cohesion: 0.17
Nodes (10): ClaudeAdapter, Any, Path, Spawner, Map the CLI's own status vocabulary onto FailureKind., Sum `modelUsage` across every model the dispatch actually used. A dispatch can…, The model that produced the most output — the one that did the work if a…, Flags verified against `claude --help` (CLI 2.1.234). The prompt goes over… (+2 more)

### Community 9 - "Tier"
Cohesion: 0.17
Nodes (32): Capability classes. A plan declares a tier; the router resolves a model. Fixed…, Tier, config(), model(), Router: tier -> model, filters, preference order, and explainability., The measured ~30k fixed cost of a `claude -p` spawn is why mechanical work…, The operator knows their own plan better than a price table does., Missing catalogue metadata is uncertainty, not evidence of insufficiency. (+24 more)

### Community 10 - "fake_spawner"
Cohesion: 0.24
Nodes (19): skipif, fake_spawner(), Any, Build a Spawner that yields FakeProcess objects. ``calls`` captures argv and…, Path, ProcessRunner: streaming, timeout, tree kill, cancellation., start_new_session is what makes killpg reach the CLI's children., Pumps must run concurrently with wait(); draining after exit would hang the… (+11 more)

### Community 11 - "console.py"
Cohesion: 0.15
Nodes (21): apply_key(), _clean_paste(), _clip(), _paint(), paste_system_clipboard(), play_splash(), poll_secret_request(), The Sleipnir console: the window you actually talk to. What this is,… (+13 more)

### Community 12 - "Sleipnir — Phase 1 design"
Cohesion: 0.05
Nodes (38): Dollars and window quota are different resources, Files, Folding a percentage back into tokens, Module layout, Not built, on purpose, Other decisions worth overruling, Phase 2 — executor, Phase 3 — router (+30 more)

### Community 13 - "budget.py"
Cohesion: 0.09
Nodes (21): BudgetGovernor, DownshiftDecision, _int(), _parse_bucket(), Projection, Any, datetime, Path (+13 more)

### Community 14 - "test_budget.py"
Cohesion: 0.05
Nodes (80): allow_utilization_reads, current_window(), fetch_window_utilization(), parse_usage_line(), Read every project transcript and return deduplicated usage records., The active 5-hour block. Windows are anchored to first use and expire ``hours``…, Read the CLI's OAuth access token, or None. Returns None for every failure…, Ask the meter. Returns None on any failure, never raises, never logs. (+72 more)

### Community 15 - "ValueError"
Cohesion: 0.16
Nodes (7): field_validator, Self, model_validator, _find_cycle(), model_validator, Return one concrete cycle as a readable path, or None. Iterative (deep DAGs…, ValueError

### Community 16 - "Plan"
Cohesion: 0.05
Nodes (75): A constant-size picture of the run, for the duty officer. This is the whole…, run_digest(), _alerts(), build_manifest(), _clip(), _evidence(), fold_results(), _fold_task() (+67 more)

### Community 17 - "theme.py"
Cohesion: 0.13
Nodes (20): ease_back_out(), ease_power2_out(), fg(), _fit(), flicker_level(), frame(), logo_lines(), paint() (+12 more)

### Community 18 - "Task"
Cohesion: 0.09
Nodes (21): The tier to dispatch ``task`` at, plus why if it moved., cost_from_outcome(), Governor, Protocol, Budget control. Implemented by BudgetGovernor (Phase 4)., Compose the shared dollar/quota axes for worker and control calls., Record a dispatch the governor refused. A denial is written to the log as a…, Compose the two-axis cost record. For subscription dispatches ``amount_usd`` is… (+13 more)

### Community 19 - "context.py"
Cohesion: 0.25
Nodes (14): ArtifactDirResolver, _artifact_section(), _describe_check(), _file_section(), IncludedInput, _output_section(), Path, Resolve a task's InputContract into the exact prompt a subagent receives. This… (+6 more)

### Community 20 - "SleipnirConfig"
Cohesion: 0.18
Nodes (25): ConfigError, ModelOption, _opt_float(), _opt_int(), _parse_backends(), _parse_models(), _parse_tiers(), Any (+17 more)

### Community 21 - "Executor"
Cohesion: 0.11
Nodes (18): clip_summary(), Enforce the schema's hard summary cap at the write site. The schema *rejects*…, ConcurrentExecutionError, Executor, _pid_is_alive(), datetime, RuntimeError, Concurrency-capped DAG execution. The executor owns everything the adapters… (+10 more)

### Community 22 - "test_capabilities.py"
Cohesion: 0.07
Nodes (7): audit_log(), _entries(), fake_ydotool(), fixture, Capability tests are hermetic by construction. Nothing here may inject a real…, Capture ydotool argv instead of running it., test_capture_records_only_the_label_and_length()

### Community 23 - "chat.py"
Cohesion: 0.11
Nodes (26): ask_claude(), ask_router(), ChatError, claude_argv(), extract_queued_instruction(), fast_lane_capable(), Path, RuntimeError (+18 more)

### Community 24 - "test_console.py"
Cohesion: 0.05
Nodes (12): parametrize, The console owns the terminal, so its failure modes are visual. Two things are…, test_an_unbroken_token_longer_than_the_pane_is_hard_split(), test_chat_rejects_an_unbounded_response_without_loading_it(), test_chat_timeout_terminates_the_process_group(), test_chat_turn_uses_guarded_process_runner_and_stdin(), test_decline_or_malformed_check_routes_to_strong_model(), test_every_rendered_line_is_exactly_the_terminal_width() (+4 more)

### Community 25 - "clipboard.py"
Cohesion: 0.26
Nodes (11): available(), ClipboardError, ClipboardPayload, offered_types(), Path, RuntimeError, Read text or images from the operator's Wayland clipboard. Keyboard-driven…, The desktop clipboard is unavailable or has no supported payload. (+3 more)

### Community 26 - "planner.py"
Cohesion: 0.25
Nodes (9): build_planner_task(), generate_plan(), planning_instructions(), Path, Decomposition: one prompt in, a validated task DAG out. The planner is itself a…, Dispatch the planning task and return the validated Plan., The decomposition brief. Written to steer toward the economics the whole system…, OutputContract (+1 more)

### Community 27 - "make_chain"
Cohesion: 0.20
Nodes (10): make_chain(), make_layered(), _plan(), t0000 -> t0001 -> ... Simple shape for status-folding tests., A wide layered DAG: every task in layer k depends on three in layer k-1. This…, Replaying the log must not double-count cost — recovery depends on it., test_completed_task_is_superseded_when_spec_changes(), test_descendants_are_transitive() (+2 more)

### Community 28 - "orchestrator.py"
Cohesion: 0.16
Nodes (18): build_control_task(), control_instructions(), control_plan_context(), ControlDecision, ControlError, _extract_decision(), BaseModel, Path (+10 more)

### Community 29 - "AttemptWorkspace"
Cohesion: 0.09
Nodes (20): AttemptWorkspace, contained_regular_file(), Any, Path, RuntimeError, Attempt workspace layout and output collection. One directory per attempt,…, Ensure an already-claimed workspace remains a real local directory., Atomically claim a new attempt directory; never reuse old contents. (+12 more)

### Community 30 - "Browser"
Cohesion: 0.15
Nodes (9): Browser, Any, An open browser the agent can drive. Deliberately a thin wrapper: it exposes…, Attach to the shared browser, starting it only if nobody has. Attaching rather…, Detach. Deliberately does **not** close the browser. Closing it here is what…, Really end the shared browser, discarding its live tabs. The profile on disk…, CapabilityError, RuntimeError (+1 more)

### Community 31 - "test_handoff.py"
Cohesion: 0.06
Nodes (13): Sleipnir — a budget-aware agentic orchestrator. Phases 1–5 provide the schema,…, fixture, The credential handoff, and the three live bugs that produced it. Every test…, A full-screen redraw loop that does not switch buffers appends every frame to…, Drawing only one row of the horse emblem renders as debris., requests_dir(), test_the_banner_is_all_or_nothing(), test_the_console_uses_the_alternate_screen() (+5 more)

### Community 32 - "ArtifactRef"
Cohesion: 0.29
Nodes (6): ArtifactRef, A request for another task's *full* output rather than its summary. Three…, test_artifact_budget_must_fit_max_input_bytes(), test_artifact_ref_must_name_a_real_output(), test_artifact_ref_rejects_path_escape(), test_artifact_ref_rejects_wildcard_everything()

### Community 33 - "Secret"
Cohesion: 0.10
Nodes (13): Put a captured credential into a form field and wipe it. Separate from ``fill``…, Operator-authorised capabilities: the desk the robot sits at. Everything in…, capture(), BaseException, RuntimeError, TracebackType, Credentials that live for one keystroke burst and then stop existing. The rule…, A secret was used twice. Deliberately fatal rather than forgiving: re-use… (+5 more)

### Community 34 - "_canonical_json"
Cohesion: 0.40
Nodes (4): _canonical_json(), Any, Stable digest of the task's *meaning*. Completed results are keyed by (task_id,…, Stable JSON encoding for hashing: sorted keys, no incidental whitespace.

### Community 35 - "TerminalInputDecoder"
Cohesion: 0.40
Nodes (3): PastedText, Turn a byte stream into keys and atomic bracketed-paste events., TerminalInputDecoder

### Community 36 - "computer.py"
Cohesion: 0.16
Nodes (24): Any, Path, Append-only record of every privileged action taken on the host. Same…, record(), redact(), click(), copy(), ensure_daemon() (+16 more)

### Community 37 - "parametrize"
Cohesion: 0.67
Nodes (3): parametrize, test_manifest_never_exceeds_the_ceiling(), test_repository_input_paths_cannot_escape_the_run_root()

### Community 38 - "TierRouter"
Cohesion: 0.10
Nodes (20): Backend, What a tier requires and which backends it prefers, in order., TierPolicy, CatalogSnapshot, ModelInfo, One comparable number for ranking. Tasks are input-heavy, so a plain average…, CandidateEval, _movement() (+12 more)

### Community 39 - "test_schema.py"
Cohesion: 0.11
Nodes (17): Phase 1 schema tests. The load-bearing test is…, Re-tiering a task must NOT invalidate its completed work., test_attempt_directories_never_collide(), test_cache_write_ttls_are_priced_separately(), test_metered_calls_do_not_consume_the_window(), test_missing_cache_prices_fall_back_without_undercounting(), test_plan_rejects_dependency_cycle(), test_plan_rejects_duplicate_task_ids() (+9 more)

### Community 40 - "BaseModel"
Cohesion: 0.16
Nodes (25): AcceptanceCheck, assert_checks_supported(), _check_command(), _check_files(), _check_json_schema(), _dispatch_check(), Any, RuntimeError (+17 more)

### Community 41 - "budget"
Cohesion: 0.22
Nodes (9): no_credential_reads(), no_real_utilization_reads(), fixture, Test-suite guardrails. The budget governor reads real window utilisation from…, Never call the usage endpoint from a test. Returns ``None``, which is the same…, Belt and braces: the token must not be read from disk either. A test that needs…, budget(), test_budget_headroom_is_none_when_limit_unknown() (+1 more)

### Community 42 - "DispatchOutcome"
Cohesion: 0.09
Nodes (20): AsyncClient, Response, DispatchOutcome, What the adapter observed. Raw facts only, no derived accounting., _HttpFailure, materialize_file_blocks(), OpenRouterAdapter, Any (+12 more)

### Community 43 - "screenshot"
Cohesion: 0.22
Nodes (9): CompletedProcess, Probe, Path, Capture the full screen to ``path``. The agent reads the resulting image…, Run a shell command as the operator, with the operator's environment. This is…, What this machine can actually do, for ``sleipnir doctor``., run(), screenshot() (+1 more)

### Community 45 - "browser.py"
Cohesion: 0.21
Nodes (13): available(), _cdp_alive(), ensure_browser(), _pid_matches_browser(), _publish_pid(), Path, Real browser control, for the work that only exists behind a login.…, Start the shared browser if it is not already running, and return its endpoint.… (+5 more)

### Community 46 - "Sleipnir — Overview"
Cohesion: 0.11
Nodes (18): File structure & modularity, Files created while running (not in the repo), Host control, in one paragraph, How the budget governor decides, How the code works (the walkthrough), How the router chooses a model, How to add code / extend it, How to run / test locally (+10 more)

### Community 47 - "fakes.py"
Cohesion: 0.15
Nodes (6): StreamReader, FakeProcess, FakeStdin, Test doubles. The fake lives at the *spawn* boundary rather than replacing…, Implements the SpawnedProcess protocol., _reader()

### Community 48 - "_manifest_for"
Cohesion: 0.18
Nodes (11): _manifest_for(), Manifest for a layered plan with every layer but the last two completed.…, This is the whole design in one assertion. A 600-task run must not cost the…, The orchestrator must never infer completeness from silence., Paths may cross into the manifest. Bytes may not., test_manifest_caps_are_enforced_not_merely_documented(), test_manifest_carries_no_artifact_contents(), test_manifest_reports_when_it_elided_content() (+3 more)

### Community 49 - "schema.py"
Cohesion: 0.13
Nodes (14): EscalationStep, estimate_tokens(), EvidenceEntry, InputContract, PlanDefaults, Sleipnir state schema. Three on-disk shapes plus one derived shape: plan.json…, A completed dependency of a frontier task: its bounded summary plus *paths* to…, Everything a task is permitted to read. Nothing else is provided to it. (+6 more)

### Community 50 - "Sleipnir — project instructions"
Cohesion: 0.14
Nodes (13): Checkpoint discipline, Environment on this machine, Lessons from the first real console session, Money and resources, Rules that will bite you if ignored, Security, Sleipnir — project instructions, The budget governor (Phase 4) (+5 more)

### Community 52 - "ConsoleState"
Cohesion: 0.17
Nodes (15): _allocate_project_run(), _claude_dirs(), ConsoleState, Message, _project_argv(), Path, Everything the renderer needs, and nothing it does not. Notably absent: any…, The brain is asleep exactly when a run owns the directory. Derived, never… (+7 more)

### Community 54 - "process_guard.py"
Cohesion: 0.50
Nodes (4): _install_parent_death_signal(), main(), Run a provider CLI with a Linux parent-death signal installed. An executor can…, Install SIGTERM-on-parent-death, closing the setup race explicitly.

### Community 55 - "ProcessRunner"
Cohesion: 0.13
Nodes (16): Signals, _default_spawn(), ProcessResult, ProcessRunner, _pump(), Any, Path, Protocol (+8 more)

### Community 57 - "Sleipnir — Project State"
Cohesion: 0.15
Nodes (12): Current phase/stage, Decisions log, Environment on this machine, Goal, Guarded fast lane and `/project` (2026-08-19), Next steps, Open questions, Phase 6 progress (2026-08-18) (+4 more)

### Community 58 - "handoff.py"
Cohesion: 0.18
Nodes (17): answer(), await_answer(), HandoffError, pending(), Path, RuntimeError, Asking the operator for a credential from a process that has no terminal. The…, Block until the console answers, and return its *status* only. Returns one of… (+9 more)

### Community 61 - "RetryPolicy"
Cohesion: 0.33
Nodes (5): Tier to use on ``attempt`` (1-indexed). Falls back to ``base_tier``., RetryPolicy, test_escalation_ladder_cannot_exceed_retries(), test_retry_policy_rejects_non_retryable_kinds(), test_tier_for_attempt_walks_the_ladder()

## Knowledge Gaps
- **67 isolated node(s):** `sleipnir`, `The one invariant`, `Rules that will bite you if ignored`, `The router (Phase 3)`, `Money and resources` (+62 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **2 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Tier` connect `Tier` to `make_task`, `cli.py`, `TaskStatus`, `AttemptStatus`, `DispatchRequest`, `test_adapters.py`, `budget.py`, `test_budget.py`, `Plan`, `Task`, `SleipnirConfig`, `Executor`, `chat.py`, `planner.py`, `orchestrator.py`, `TierRouter`, `test_schema.py`, `schema.py`, `RetryPolicy`?**
  _High betweenness centrality (0.089) - this node is a cross-community bridge._
- **Why does `make_task()` connect `make_task` to `ArtifactRef`, `test_adapters.py`, `test_schema.py`, `BaseModel`, `Tier`, `test_budget.py`, `Plan`, `schema.py`, `Task`, `planner.py`, `make_chain`, `orchestrator.py`?**
  _High betweenness centrality (0.052) - this node is a cross-community bridge._
- **Why does `Plan` connect `Plan` to `make_task`, `cli.py`, `TaskStatus`, `ArtifactRef`, `test_schema.py`, `BaseModel`, `console.py`, `budget.py`, `test_budget.py`, `ValueError`, `schema.py`, `Task`, `Executor`, `planner.py`, `make_chain`, `orchestrator.py`?**
  _High betweenness centrality (0.050) - this node is a cross-community bridge._
- **Are the 5 inferred relationships involving `make_task()` (e.g. with `ExpectedOutput` and `InputContract`) actually correct?**
  _`make_task()` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 73 inferred relationships involving `Tier` (e.g. with `DispatchPreview` and `DispatchRequest`) actually correct?**
  _`Tier` has 73 INFERRED edges - model-reasoned connections that need verification._
- **Are the 25 inferred relationships involving `Task` (e.g. with `DispatchRequest` and `BudgetGovernor`) actually correct?**
  _`Task` has 25 INFERRED edges - model-reasoned connections that need verification._
- **Are the 50 inferred relationships involving `Adapter` (e.g. with `BaseAdapter` and `DispatchPreview`) actually correct?**
  _`Adapter` has 50 INFERRED edges - model-reasoned connections that need verification._