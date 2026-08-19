# Graph Report - Sleipnir  (2026-08-19)

## Corpus Check
- 60 files · ~82,817 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1585 nodes · 4554 edges · 67 communities (59 shown, 8 thin omitted)
- Extraction: 84% EXTRACTED · 16% INFERRED · 0% AMBIGUOUS · INFERRED: 724 edges (avg confidence: 0.51)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `065c1ef3`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- make_task
- cli.py
- TaskStatus
- schema.py
- test_pricing.py
- DispatchRequest
- test_adapters.py
- Adapter
- ClaudeAdapter
- Tier
- ProcessRunner
- console.py
- Sleipnir — Phase 1 design
- BudgetGovernor
- test_budget.py
- ValueError
- planner.py
- theme.py
- checks.py
- BaseModel
- context.py
- Task
- test_capabilities.py
- chat.py
- test_console.py
- clipboard.py
- _manifest_for
- contained_regular_file
- Plan
- AttemptWorkspace
- Browser
- test_handoff.py
- budget.py
- Secret
- _canonical_json
- TerminalInputDecoder
- computer.py
- DispatchOutcome
- TierRouter
- test_schema.py
- run_digest
- budget
- ._call
- current_window
- WindowUtilization
- browser.py
- Sleipnir — Overview
- fakes.py
- SleipnirConfig
- test_executor_run_ids_are_unique
- Sleipnir — project instructions
- test_theme.py
- PriceSnapshot
- CodexInvocation
- process_guard.py
- .run
- _widths
- Sleipnir — Project State
- handoff.py
- UnsupportedCheckError
- sleipnir
- RetryPolicy
- ._artifact_dir_for
- test_file_blocks_cannot_escape_the_attempt_directory
- test_codex_says_so_when_usage_is_unknown
- test_decline_or_malformed_check_routes_to_strong_model
- test_spec_hash_ignores_routing_fields

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

## Communities (67 total, 8 thin omitted)

### Community 0 - "make_task"
Cohesion: 0.09
Nodes (83): ExecutorConfig, Append-only attempt log. The single source of truth for run state., Append one record and fsync it. fsync per record is the cost of the recovery…, Read every record, tolerating exactly one torn trailing line. A crash mid-…, Attempts with a start and no finish — in flight when the process died., Raised when a non-final line fails to parse — that is real corruption, not the…, ResultLog, TornRecordError (+75 more)

### Community 1 - "cli.py"
Cohesion: 0.06
Nodes (81): ArgumentParser, Namespace, render_decisions(), build_adapters(), build_parser(), CliError, cmd_apply_revision(), cmd_browser() (+73 more)

### Community 2 - "TaskStatus"
Cohesion: 0.07
Nodes (81): escalation_changes(), evaluate_gate(), GateVerdict, GroupState, GroupVerdict, StrEnum, The phase gate: what the brain is allowed to know when it wakes up. The…, Every group passed. The phase may be merged and the next one begun. (+73 more)

### Community 3 - "schema.py"
Cohesion: 0.10
Nodes (32): Claude adapter — shells out to `claude -p` headless. Auth is entirely the…, # NOTE: a non-empty `permission_denials` on an otherwise clean run does, clip_summary(), Attempt workspace layout and output collection. One directory per attempt,…, Enforce the schema's hard summary cap at the write site. The schema *rejects*…, Concurrency-capped DAG execution. The executor owns everything the adapters…, Combine what the provider said with what actually landed on disk. The…, Async subprocess execution with timeout, streaming capture, and tree kill.… (+24 more)

### Community 4 - "test_pricing.py"
Cohesion: 0.07
Nodes (50): CatalogUnavailableError, _first_int(), _float(), ModelCatalog, _nonnegative_float(), parse_models(), _per_mtok(), Any (+42 more)

### Community 5 - "DispatchRequest"
Cohesion: 0.08
Nodes (27): ABC, Response, AdapterError, BaseAdapter, DispatchPreview, DispatchRequest, RuntimeError, The adapter interface. An adapter's job is narrow on purpose: take a fully-… (+19 more)

### Community 6 - "test_adapters.py"
Cohesion: 0.15
Nodes (48): claude_adapter(), openrouter(), Path, Adapter tests. Every adapter is driven end to end against a fake. The Claude…, The whole point: `usage.input_tokens` is 10, `modelUsage` is 907., Prompts carry file contents; argv has a length limit and is world-readable., Regression: seeding on (task, attempt) alone made every resume collide with…, Observed live: a subagent was denied one tool, worked around it, and produced… (+40 more)

### Community 7 - "Adapter"
Cohesion: 0.13
Nodes (44): extract_plan_json(), Pull a JSON object out of a model response. Tries the whole response first,…, Adapter, Dispatch backends. Auth is always delegated to the official tool., invoke(), PlanningAdapter, fixture, parametrize (+36 more)

### Community 8 - "ClaudeAdapter"
Cohesion: 0.18
Nodes (9): ClaudeAdapter, Any, Path, Spawner, Map the CLI's own status vocabulary onto FailureKind., Sum `modelUsage` across every model the dispatch actually used. A dispatch can…, The model that produced the most output — the one that did the work if a…, Flags verified against `claude --help` (CLI 2.1.234). The prompt goes over… (+1 more)

### Community 9 - "Tier"
Cohesion: 0.17
Nodes (32): Capability classes. A plan declares a tier; the router resolves a model. Fixed…, Tier, config(), model(), Router: tier -> model, filters, preference order, and explainability., The measured ~30k fixed cost of a `claude -p` spawn is why mechanical work…, The operator knows their own plan better than a price table does., Missing catalogue metadata is uncertainty, not evidence of insufficiency. (+24 more)

### Community 10 - "ProcessRunner"
Cohesion: 0.17
Nodes (26): skipif, ProcessRunner, Spawner, Runs one child process to completion, a timeout, or a cancellation., fake_spawner(), Any, Build a Spawner that yields FakeProcess objects. ``calls`` captures argv and…, test_chat_rejects_an_unbounded_response_without_loading_it() (+18 more)

### Community 11 - "console.py"
Cohesion: 0.13
Nodes (26): apply_key(), _clean_paste(), _clip(), ConsoleState, Message, _paint(), paste_system_clipboard(), play_splash() (+18 more)

### Community 12 - "Sleipnir — Phase 1 design"
Cohesion: 0.05
Nodes (38): Dollars and window quota are different resources, Files, Folding a percentage back into tokens, Module layout, Not built, on purpose, Other decisions worth overruling, Phase 2 — executor, Phase 3 — router (+30 more)

### Community 13 - "BudgetGovernor"
Cohesion: 0.11
Nodes (13): BudgetGovernor, Projection, Estimates consumption and downshifts eligible tasks to stay inside it., The meter's own reading, cached briefly. None if unavailable. Disabled by…, Cost of everything still to run, at the tiers currently assigned., (window tokens, metered dollars) one attempt of ``task`` would cost. Fixed…, Assign a tier to every remaining task, downshifting until it fits. Downshifts…, The costliest task that can still move one rung down the ladder. (+5 more)

### Community 14 - "test_budget.py"
Cohesion: 0.12
Nodes (40): Tokens charged against the 5-hour window. ``cache_read_weight`` exists because…, window_tokens(), assistant_line(), config(), governor(), plan_of(), Path, Budget governor: usage parsing, window detection, projection, downshift. The… (+32 more)

### Community 15 - "ValueError"
Cohesion: 0.15
Nodes (6): field_validator, Self, ClientFactory, model_validator, model_validator, ValueError

### Community 16 - "planner.py"
Cohesion: 0.14
Nodes (19): assemble_plan(), build_planner_task(), generate_plan(), planning_instructions(), PlanningError, Path, RuntimeError, Decomposition: one prompt in, a validated task DAG out. The planner is itself a… (+11 more)

### Community 17 - "theme.py"
Cohesion: 0.13
Nodes (20): ease_back_out(), ease_power2_out(), fg(), _fit(), flicker_level(), frame(), logo_lines(), paint() (+12 more)

### Community 18 - "checks.py"
Cohesion: 0.19
Nodes (19): AcceptanceCheck, _check_command(), _check_files(), _check_json_schema(), _dispatch_check(), Any, Acceptance checks. Checks run *after* the adapter returns and decide whether…, A deliberate *subset* of JSON Schema: type, required, properties, items, enum,… (+11 more)

### Community 19 - "BaseModel"
Cohesion: 0.12
Nodes (17): ArtifactRef, EscalationStep, InputContract, PlanDefaults, BaseModel, A request for another task's *full* output rather than its summary. Three…, Everything a task is permitted to read. Nothing else is provided to it., Planner-declared upper bound on input size. Feeds tier selection. (+9 more)

### Community 20 - "context.py"
Cohesion: 0.25
Nodes (14): ArtifactDirResolver, _artifact_section(), _describe_check(), _file_section(), IncludedInput, _output_section(), Path, Resolve a task's InputContract into the exact prompt a subagent receives. This… (+6 more)

### Community 21 - "Task"
Cohesion: 0.08
Nodes (24): assert_checks_supported(), ConcurrentExecutionError, Executor, Governor, _pid_is_alive(), datetime, Protocol, RuntimeError (+16 more)

### Community 22 - "test_capabilities.py"
Cohesion: 0.06
Nodes (7): audit_log(), _entries(), fake_ydotool(), fixture, Capability tests are hermetic by construction. Nothing here may inject a real…, Capture ydotool argv instead of running it., test_capture_records_only_the_label_and_length()

### Community 23 - "chat.py"
Cohesion: 0.11
Nodes (26): ask_claude(), ask_router(), ChatError, claude_argv(), extract_queued_instruction(), fast_lane_capable(), Path, RuntimeError (+18 more)

### Community 25 - "clipboard.py"
Cohesion: 0.26
Nodes (11): available(), ClipboardError, ClipboardPayload, offered_types(), Path, RuntimeError, Read text or images from the operator's Wayland clipboard. Keyboard-driven…, The desktop clipboard is unavailable or has no supported payload. (+3 more)

### Community 26 - "_manifest_for"
Cohesion: 0.14
Nodes (14): _manifest_for(), parametrize, Manifest for a layered plan with every layer but the last two completed.…, This is the whole design in one assertion. A 600-task run must not cost the…, The orchestrator must never infer completeness from silence., Paths may cross into the manifest. Bytes may not., test_manifest_caps_are_enforced_not_merely_documented(), test_manifest_carries_no_artifact_contents() (+6 more)

### Community 27 - "contained_regular_file"
Cohesion: 0.24
Nodes (6): contained_regular_file(), The subagent's self-written summary, if it produced one., Match what is on disk against what the task promised. Returns (produced,…, Files the task wrote but never declared. Recorded with an empty ``name`` rather…, True only for a non-symlinked file physically beneath ``root``. Subagents…, sha256_file()

### Community 28 - "Plan"
Cohesion: 0.15
Nodes (16): build_control_task(), control_instructions(), control_plan_context(), ControlDecision, _extract_decision(), BaseModel, Path, Sparse Claude control cycles over the bounded manifest. Workers execute… (+8 more)

### Community 29 - "AttemptWorkspace"
Cohesion: 0.15
Nodes (10): AttemptWorkspace, Any, Path, RuntimeError, Ensure an already-claimed workspace remains a real local directory., Atomically claim a new attempt directory; never reuse old contents., Write one harness-owned top-level file without following symlinks. The…, An attempt path existed before the harness claimed this attempt. (+2 more)

### Community 30 - "Browser"
Cohesion: 0.14
Nodes (9): Browser, Any, An open browser the agent can drive. Deliberately a thin wrapper: it exposes…, Attach to the shared browser, starting it only if nobody has. Attaching rather…, Detach. Deliberately does **not** close the browser. Closing it here is what…, Really end the shared browser, discarding its live tabs. The profile on disk…, CapabilityError, RuntimeError (+1 more)

### Community 31 - "test_handoff.py"
Cohesion: 0.09
Nodes (7): fixture, The credential handoff, and the three live bugs that produced it. Every test…, A full-screen redraw loop that does not switch buffers appends every frame to…, Drawing only one row of the horse emblem renders as debris., requests_dir(), test_the_banner_is_all_or_nothing(), test_the_console_uses_the_alternate_screen()

### Community 32 - "budget.py"
Cohesion: 0.08
Nodes (37): allow_utilization_reads, DownshiftDecision, fetch_window_utilization(), _int(), _parse_bucket(), parse_usage_line(), Any, datetime (+29 more)

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
Cohesion: 0.11
Nodes (33): CompletedProcess, Any, Path, Append-only record of every privileged action taken on the host. Same…, record(), redact(), click(), copy() (+25 more)

### Community 37 - "DispatchOutcome"
Cohesion: 0.12
Nodes (20): DispatchOutcome, What the adapter observed. Raw facts only, no derived accounting., Put sparse-brain spend on the same durable accounting stream., _record_control_result(), cost_from_outcome(), Compose the shared dollar/quota axes for worker and control calls., Compose the two-axis cost record. For subscription dispatches ``amount_usd`` is…, Phase 2 placeholder: a fixed tier -> (adapter, model) table from config. Phase… (+12 more)

### Community 38 - "TierRouter"
Cohesion: 0.13
Nodes (16): What a tier requires and which backends it prefers, in order., TierPolicy, CatalogSnapshot, ModelInfo, One comparable number for ranking. Tasks are input-heavy, so a plain average…, CandidateEval, _movement(), Tier -> concrete model resolution. Tasks declare a *tier*. This module turns… (+8 more)

### Community 39 - "test_schema.py"
Cohesion: 0.10
Nodes (24): make_chain(), make_layered(), _plan(), Phase 1 schema tests. The load-bearing test is…, t0000 -> t0001 -> ... Simple shape for status-folding tests., A wide layered DAG: every task in layer k depends on three in layer k-1. This…, Replaying the log must not double-count cost — recovery depends on it., The trap found in the real ~/.claude/projects record: input_tokens=2 while… (+16 more)

### Community 40 - "run_digest"
Cohesion: 0.18
Nodes (12): _allocate_project_run(), _claude_dirs(), _project_argv(), Path, A constant-size picture of the run, for the duty officer. This is the whole…, Build a child CLI invocation using the console's own workspace policy., Choose a collision-resistant workspace for one `/project` invocation., Run one project stage without letting its output corrupt the console. (+4 more)

### Community 41 - "budget"
Cohesion: 0.22
Nodes (9): no_credential_reads(), no_real_utilization_reads(), fixture, Test-suite guardrails. The budget governor reads real window utilisation from…, Never call the usage endpoint from a test. Returns ``None``, which is the same…, Belt and braces: the token must not be read from disk either. A test that needs…, budget(), test_budget_headroom_is_none_when_limit_unknown() (+1 more)

### Community 42 - "._call"
Cohesion: 0.15
Nodes (12): AsyncClient, _HttpFailure, materialize_file_blocks(), Any, Exception, Path, Consume the SSE stream, writing every raw line to disk as it lands. Streaming…, Write ```file:<path> blocks into ``target_dir``. Paths are confined to the… (+4 more)

### Community 43 - "current_window"
Cohesion: 0.29
Nodes (7): current_window(), The active 5-hour block. Windows are anchored to first use and expire ``hours``…, Reporting full headroom is right; inventing consumption is not., test_a_gap_of_five_hours_starts_a_new_window(), test_empty_history_is_a_fresh_window(), test_no_recent_activity_reports_a_fresh_window(), test_window_is_anchored_to_first_use_not_a_rolling_lookback()

### Community 44 - "WindowUtilization"
Cohesion: 0.25
Nodes (7): What the meter itself reports. Percentages, never tokens., Token limit consistent with ``used_tokens`` being this percentage., WindowUtilization, The reading is a percentage; everything downstream works in tokens. Solving…, Near zero the division explodes and would imply a wildly wrong limit., test_implied_limit_refuses_when_utilisation_is_too_small_to_divide_by(), test_implied_limit_solves_for_the_limit_matching_local_accounting()

### Community 45 - "browser.py"
Cohesion: 0.21
Nodes (13): available(), _cdp_alive(), ensure_browser(), _pid_matches_browser(), _publish_pid(), Path, Real browser control, for the work that only exists behind a login.…, Start the shared browser if it is not already running, and return its endpoint.… (+5 more)

### Community 46 - "Sleipnir — Overview"
Cohesion: 0.11
Nodes (18): File structure & modularity, Files created while running (not in the repo), Host control, in one paragraph, How the budget governor decides, How the code works (the walkthrough), How the router chooses a model, How to add code / extend it, How to run / test locally (+10 more)

### Community 47 - "fakes.py"
Cohesion: 0.15
Nodes (6): StreamReader, FakeProcess, FakeStdin, Test doubles. The fake lives at the *spawn* boundary rather than replacing…, Implements the SpawnedProcess protocol., _reader()

### Community 48 - "SleipnirConfig"
Cohesion: 0.16
Nodes (26): Backend, ConfigError, ModelOption, _opt_float(), _opt_int(), _parse_backends(), _parse_models(), _parse_tiers() (+18 more)

### Community 50 - "Sleipnir — project instructions"
Cohesion: 0.14
Nodes (13): Checkpoint discipline, Environment on this machine, Lessons from the first real console session, Money and resources, Rules that will bite you if ignored, Security, Sleipnir — project instructions, The budget governor (Phase 4) (+5 more)

### Community 51 - "test_theme.py"
Cohesion: 0.16
Nodes (6): Sleipnir — a budget-aware agentic orchestrator. Phases 1–5 provide the schema,…, The chrome must stay a pure function of the frame number, and must never be…, test_frame_lines_never_exceed_requested_width(), test_splash_ends_fully_revealed(), test_splash_renders_every_frame_at_a_narrow_terminal(), _visible()

### Community 52 - "PriceSnapshot"
Cohesion: 0.29
Nodes (6): PriceSnapshot, Token and server-tool prices as fetched at dispatch time. Never populated from…, Cost of ``usage`` under this snapshot. Missing cache prices fall back to the…, test_cache_write_ttls_are_priced_separately(), test_missing_cache_prices_fall_back_without_undercounting(), test_server_tool_requests_are_priced_separately_from_tokens()

### Community 53 - "CodexInvocation"
Cohesion: 0.40
Nodes (3): CodexInvocation, Spawner, How to call the CLI. Data, not dispatch logic.

### Community 54 - "process_guard.py"
Cohesion: 0.50
Nodes (4): _install_parent_death_signal(), main(), Run a provider CLI with a Linux parent-death signal installed. An executor can…, Install SIGTERM-on-parent-death, closing the setup race explicitly.

### Community 55 - ".run"
Cohesion: 0.15
Nodes (12): Signals, _default_spawn(), ProcessResult, _pump(), Any, Path, Protocol, SIGTERM the group, allow a grace period, then SIGKILL. Shielded because this… (+4 more)

### Community 56 - "_widths"
Cohesion: 0.50
Nodes (4): test_an_unbroken_token_longer_than_the_pane_is_hard_split(), test_every_rendered_line_is_exactly_the_terminal_width(), test_narrow_terminal_still_renders(), _widths()

### Community 57 - "Sleipnir — Project State"
Cohesion: 0.15
Nodes (12): Current phase/stage, Decisions log, Environment on this machine, Goal, Guarded fast lane and `/project` (2026-08-19), Next steps, Open questions, Phase 6 progress (2026-08-18) (+4 more)

### Community 58 - "handoff.py"
Cohesion: 0.18
Nodes (17): answer(), await_answer(), HandoffError, pending(), Path, RuntimeError, Asking the operator for a credential from a process that has no terminal. The…, Block until the console answers, and return its *status* only. Returns one of… (+9 more)

### Community 59 - "UnsupportedCheckError"
Cohesion: 0.67
Nodes (3): RuntimeError, Raised at startup, not per task. A plan that cannot be fully checked must fail…, UnsupportedCheckError

### Community 61 - "RetryPolicy"
Cohesion: 0.33
Nodes (5): Tier to use on ``attempt`` (1-indexed). Falls back to ``base_tier``., RetryPolicy, test_escalation_ladder_cannot_exceed_retries(), test_retry_policy_rejects_non_retryable_kinds(), test_tier_for_attempt_walks_the_ladder()

## Knowledge Gaps
- **67 isolated node(s):** `sleipnir`, `The one invariant`, `Rules that will bite you if ignored`, `The router (Phase 3)`, `Money and resources` (+62 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **8 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Tier` connect `Tier` to `make_task`, `cli.py`, `TaskStatus`, `schema.py`, `DispatchRequest`, `test_adapters.py`, `BudgetGovernor`, `test_budget.py`, `planner.py`, `Task`, `chat.py`, `Plan`, `budget.py`, `DispatchOutcome`, `TierRouter`, `test_schema.py`, `SleipnirConfig`, `test_executor_run_ids_are_unique`, `RetryPolicy`, `test_spec_hash_ignores_routing_fields`?**
  _High betweenness centrality (0.071) - this node is a cross-community bridge._
- **Why does `make_task()` connect `make_task` to `cli.py`, `test_spec_hash_ignores_routing_fields`, `schema.py`, `DispatchOutcome`, `test_adapters.py`, `test_schema.py`, `Tier`, `test_budget.py`, `planner.py`, `test_executor_run_ids_are_unique`, `checks.py`, `BaseModel`, `Task`?**
  _High betweenness centrality (0.056) - this node is a cross-community bridge._
- **Why does `Plan` connect `Plan` to `budget.py`, `cli.py`, `TaskStatus`, `schema.py`, `make_task`, `test_schema.py`, `run_digest`, `console.py`, `BudgetGovernor`, `test_budget.py`, `ValueError`, `planner.py`, `test_executor_run_ids_are_unique`, `BaseModel`, `Task`?**
  _High betweenness centrality (0.053) - this node is a cross-community bridge._
- **Are the 5 inferred relationships involving `make_task()` (e.g. with `ExpectedOutput` and `InputContract`) actually correct?**
  _`make_task()` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 73 inferred relationships involving `Tier` (e.g. with `DispatchPreview` and `DispatchRequest`) actually correct?**
  _`Tier` has 73 INFERRED edges - model-reasoned connections that need verification._
- **Are the 25 inferred relationships involving `Task` (e.g. with `DispatchRequest` and `BudgetGovernor`) actually correct?**
  _`Task` has 25 INFERRED edges - model-reasoned connections that need verification._
- **Are the 50 inferred relationships involving `Adapter` (e.g. with `BaseAdapter` and `DispatchPreview`) actually correct?**
  _`Adapter` has 50 INFERRED edges - model-reasoned connections that need verification._