# Graph Report - Sleipnir  (2026-08-19)

## Corpus Check
- 60 files · ~81,827 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1579 nodes · 4543 edges · 69 communities (66 shown, 3 thin omitted)
- Extraction: 84% EXTRACTED · 16% INFERRED · 0% AMBIGUOUS · INFERRED: 724 edges (avg confidence: 0.51)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `bc3031bc`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- make_task
- cli.py
- TaskStatus
- AttemptStatus
- test_pricing.py
- DispatchOutcome
- test_adapters.py
- Adapter
- DispatchRequest
- Tier
- test_process.py
- console.py
- Sleipnir — Phase 1 design
- BudgetGovernor
- test_budget.py
- ValueError
- projection.py
- theme.py
- Task
- context.py
- apply_revision
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
- budget.py
- Secret
- _canonical_json
- TerminalInputDecoder
- computer.py
- test_outputs_cannot_overwrite_harness_owned_files
- TierRouter
- test_schema.py
- schema.py
- budget
- OpenRouterAdapter
- parse_usage_line
- fetch_window_utilization
- browser.py
- Sleipnir — Overview
- FakeProcess
- _manifest_for
- InputContract
- Sleipnir — project instructions
- artifacts.py
- _handle
- fold_results
- process_guard.py
- process.py
- Plan
- Sleipnir — Project State
- handoff.py
- WindowUtilization
- sleipnir
- RetryPolicy
- ProcessRunner
- PriceSnapshot
- materialize_file_blocks
- BudgetSnapshot
- RoutingDecision
- OutputContract
- ._artifact_dir_for

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

## Communities (69 total, 3 thin omitted)

### Community 0 - "make_task"
Cohesion: 0.09
Nodes (80): RuntimeError, An attempt path existed before the harness claimed this attempt., WorkspaceCollisionError, ExecutorConfig, Append-only attempt log. The single source of truth for run state., Append one record and fsync it. fsync per record is the cost of the recovery…, Read every record, tolerating exactly one torn trailing line. A crash mid-…, Attempts with a start and no finish — in flight when the process died. (+72 more)

### Community 1 - "cli.py"
Cohesion: 0.10
Nodes (55): ArgumentParser, Namespace, render_decisions(), build_adapters(), build_parser(), CliError, cmd_apply_revision(), cmd_browser() (+47 more)

### Community 2 - "TaskStatus"
Cohesion: 0.11
Nodes (52): escalation_changes(), evaluate_gate(), GateVerdict, GroupState, GroupVerdict, StrEnum, Every group passed. The phase may be merged and the next one begun., Workers have stopped and something is wrong. A quiescent, complete run does not… (+44 more)

### Community 3 - "AttemptStatus"
Cohesion: 0.21
Nodes (11): Combine what the provider said with what actually landed on disk. The…, AttemptStatus, FailureKind, StrEnum, Outcome of a single attempt. Deliberately small — *why* lives in FailureKind., Why an attempt did not fully succeed. Separated from AttemptStatus so retry…, Exception, test_failed_dependency_skips_dependents() (+3 more)

### Community 4 - "test_pricing.py"
Cohesion: 0.07
Nodes (50): CatalogUnavailableError, _first_int(), _float(), ModelCatalog, _nonnegative_float(), parse_models(), _per_mtok(), Any (+42 more)

### Community 5 - "DispatchOutcome"
Cohesion: 0.07
Nodes (38): ABC, AdapterError, BaseAdapter, DispatchOutcome, DispatchPreview, RuntimeError, The adapter interface. An adapter's job is narrow on purpose: take a fully-…, One dispatch backend. Auth is never implemented here. The `claude` and `codex`… (+30 more)

### Community 6 - "test_adapters.py"
Cohesion: 0.14
Nodes (50): fake_spawner(), Any, Test doubles. The fake lives at the *spawn* boundary rather than replacing…, Build a Spawner that yields FakeProcess objects. ``calls`` captures argv and…, claude_adapter(), openrouter(), Path, Adapter tests. Every adapter is driven end to end against a fake. The Claude… (+42 more)

### Community 7 - "Adapter"
Cohesion: 0.13
Nodes (44): extract_plan_json(), Pull a JSON object out of a model response. Tries the whole response first,…, Adapter, Dispatch backends. Auth is always delegated to the official tool., invoke(), PlanningAdapter, fixture, parametrize (+36 more)

### Community 8 - "DispatchRequest"
Cohesion: 0.13
Nodes (14): DispatchRequest, Everything an adapter needs. Fully resolved — adapters never route., ClaudeAdapter, Any, Path, Spawner, Map the CLI's own status vocabulary onto FailureKind., Sum `modelUsage` across every model the dispatch actually used. A dispatch can… (+6 more)

### Community 9 - "Tier"
Cohesion: 0.09
Nodes (58): The tier to dispatch ``task`` at, plus why if it moved., ConfigError, ModelOption, _opt_float(), _opt_int(), _parse_backends(), _parse_models(), _parse_tiers() (+50 more)

### Community 10 - "test_process.py"
Cohesion: 0.25
Nodes (16): skipif, Path, ProcessRunner: streaming, timeout, tree kill, cancellation., start_new_session is what makes killpg reach the CLI's children., Pumps must run concurrently with wait(); draining after exit would hang the…, run(), test_cancellation_kills_the_process_and_propagates(), test_large_output_does_not_deadlock() (+8 more)

### Community 11 - "console.py"
Cohesion: 0.11
Nodes (32): _allocate_project_run(), apply_key(), _claude_dirs(), _clean_paste(), ConsoleState, Message, _paint(), paste_system_clipboard() (+24 more)

### Community 12 - "Sleipnir — Phase 1 design"
Cohesion: 0.05
Nodes (38): Dollars and window quota are different resources, Files, Folding a percentage back into tokens, Module layout, Not built, on purpose, Other decisions worth overruling, Phase 2 — executor, Phase 3 — router (+30 more)

### Community 13 - "BudgetGovernor"
Cohesion: 0.17
Nodes (10): BudgetGovernor, Projection, Estimates consumption and downshifts eligible tasks to stay inside it., The meter's own reading, cached briefly. None if unavailable. Disabled by…, Cost of everything still to run, at the tiers currently assigned., (window tokens, metered dollars) one attempt of ``task`` would cost. Fixed…, Assign a tier to every remaining task, downshifting until it fits. Downshifts…, The costliest task that can still move one rung down the ladder. (+2 more)

### Community 14 - "test_budget.py"
Cohesion: 0.20
Nodes (27): config(), governor(), plan_of(), Path, Budget governor: usage parsing, window detection, projection, downshift. The…, Records recur across resumed sessions; 59% of the real corpus was duplicated.…, A trivial task on a subscription backend is not cheap: the spawn alone costs…, The governor must never stop or reroute a run on a number it could not verify. (+19 more)

### Community 15 - "ValueError"
Cohesion: 0.16
Nodes (7): field_validator, Self, model_validator, _find_cycle(), model_validator, Return one concrete cycle as a readable path, or None. Iterative (deep DAGs…, ValueError

### Community 16 - "projection.py"
Cohesion: 0.15
Nodes (27): _alerts(), build_manifest(), _clip(), _evidence(), _frontier(), _group_rollups(), _propagate_dependencies(), datetime (+19 more)

### Community 17 - "theme.py"
Cohesion: 0.11
Nodes (24): _clip(), Model and provider text is untrusted; strip anything non-printable. Same trust…, render(), _wrap(), ease_back_out(), ease_power2_out(), fg(), _fit() (+16 more)

### Community 18 - "Task"
Cohesion: 0.21
Nodes (7): Governor, Protocol, Budget control. Implemented by BudgetGovernor (Phase 4)., Tier -> concrete model. Implemented by TierRouter. ``downshift_reason`` is how…, Router, Attempts never share a directory, so a re-run can never clobber evidence from a…, Task

### Community 19 - "context.py"
Cohesion: 0.25
Nodes (14): ArtifactDirResolver, _artifact_section(), _describe_check(), _file_section(), IncludedInput, _output_section(), Path, Resolve a task's InputContract into the exact prompt a subagent receives. This… (+6 more)

### Community 20 - "apply_revision"
Cohesion: 0.18
Nodes (23): The phase gate: what the brain is allowed to know when it wakes up. The…, apply_revision(), persist_revision(), datetime, Path, RuntimeError, Validated, auditable plan revision application. The orchestrator may propose…, Append the audit first, then atomically replace the derived plan view. (+15 more)

### Community 21 - "Executor"
Cohesion: 0.13
Nodes (13): ConcurrentExecutionError, Executor, _pid_is_alive(), datetime, RuntimeError, Everything the run would dispatch, spending nothing. Walks the DAG in…, Execute while holding exclusive ownership of the run directory., Close attempts whose executor died before writing a terminal record. The start… (+5 more)

### Community 22 - "test_capabilities.py"
Cohesion: 0.07
Nodes (7): audit_log(), _entries(), fake_ydotool(), fixture, Capability tests are hermetic by construction. Nothing here may inject a real…, Capture ydotool argv instead of running it., test_capture_records_only_the_label_and_length()

### Community 23 - "chat.py"
Cohesion: 0.14
Nodes (20): ask_claude(), ask_router(), ChatError, claude_argv(), extract_queued_instruction(), fast_lane_capable(), Path, RuntimeError (+12 more)

### Community 24 - "test_console.py"
Cohesion: 0.05
Nodes (8): parametrize, The console owns the terminal, so its failure modes are visual. Two things are…, test_an_unbroken_token_longer_than_the_pane_is_hard_split(), test_decline_or_malformed_check_routes_to_strong_model(), test_every_rendered_line_is_exactly_the_terminal_width(), test_narrow_terminal_still_renders(), test_the_brain_is_asleep_exactly_when_a_run_owns_the_directory(), _widths()

### Community 25 - "clipboard.py"
Cohesion: 0.26
Nodes (11): available(), ClipboardError, ClipboardPayload, offered_types(), Path, RuntimeError, Read text or images from the operator's Wayland clipboard. Keyboard-driven…, The desktop clipboard is unavailable or has no supported payload. (+3 more)

### Community 26 - "planner.py"
Cohesion: 0.21
Nodes (14): assemble_plan(), build_planner_task(), generate_plan(), planning_instructions(), PlanningError, Path, RuntimeError, Decomposition: one prompt in, a validated task DAG out. The planner is itself a… (+6 more)

### Community 27 - "make_chain"
Cohesion: 0.20
Nodes (10): make_chain(), make_layered(), _plan(), t0000 -> t0001 -> ... Simple shape for status-folding tests., A wide layered DAG: every task in layer k depends on three in layer k-1. This…, Replaying the log must not double-count cost — recovery depends on it., test_completed_task_is_superseded_when_spec_changes(), test_descendants_are_transitive() (+2 more)

### Community 28 - "orchestrator.py"
Cohesion: 0.18
Nodes (16): build_control_task(), control_instructions(), control_plan_context(), ControlDecision, ControlError, _extract_decision(), BaseModel, Path (+8 more)

### Community 29 - "AttemptWorkspace"
Cohesion: 0.18
Nodes (7): AttemptWorkspace, Any, Path, Ensure an already-claimed workspace remains a real local directory., Atomically claim a new attempt directory; never reuse old contents., Write one harness-owned top-level file without following symlinks. The…, Filesystem home for one attempt. Paths recorded in results.jsonl are always…

### Community 30 - "Browser"
Cohesion: 0.14
Nodes (9): Browser, Any, An open browser the agent can drive. Deliberately a thin wrapper: it exposes…, Attach to the shared browser, starting it only if nobody has. Attaching rather…, Detach. Deliberately does **not** close the browser. Closing it here is what…, Really end the shared browser, discarding its live tabs. The profile on disk…, CapabilityError, RuntimeError (+1 more)

### Community 31 - "test_handoff.py"
Cohesion: 0.06
Nodes (13): Sleipnir — a budget-aware agentic orchestrator. Phases 1–5 provide the schema,…, fixture, The credential handoff, and the three live bugs that produced it. Every test…, A full-screen redraw loop that does not switch buffers appends every frame to…, Drawing only one row of the horse emblem renders as debris., requests_dir(), test_the_banner_is_all_or_nothing(), test_the_console_uses_the_alternate_screen() (+5 more)

### Community 32 - "budget.py"
Cohesion: 0.11
Nodes (22): current_window(), DownshiftDecision, _int(), _parse_bucket(), Any, datetime, Path, Budget governor: what the 5-hour window has cost, and what the plan will. Two… (+14 more)

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

### Community 37 - "test_outputs_cannot_overwrite_harness_owned_files"
Cohesion: 0.50
Nodes (4): parametrize, test_manifest_never_exceeds_the_ceiling(), test_outputs_cannot_overwrite_harness_owned_files(), test_repository_input_paths_cannot_escape_the_run_root()

### Community 38 - "TierRouter"
Cohesion: 0.12
Nodes (17): Backend, What a tier requires and which backends it prefers, in order., TierPolicy, CatalogSnapshot, ModelInfo, One comparable number for ranking. Tasks are input-heavy, so a plain average…, CandidateEval, _movement() (+9 more)

### Community 39 - "test_schema.py"
Cohesion: 0.12
Nodes (19): finished(), Phase 1 schema tests. The load-bearing test is…, Re-tiering a task must NOT invalidate its completed work., The trap found in the real ~/.claude/projects record: input_tokens=2 while…, routing(), test_attempt_directories_never_collide(), test_downshift_must_be_explained(), test_failed_attempt_requires_a_failure_kind() (+11 more)

### Community 40 - "schema.py"
Cohesion: 0.11
Nodes (35): AcceptanceCheck, assert_checks_supported(), _check_command(), _check_files(), _check_json_schema(), _dispatch_check(), Any, RuntimeError (+27 more)

### Community 41 - "budget"
Cohesion: 0.22
Nodes (9): no_credential_reads(), no_real_utilization_reads(), fixture, Test-suite guardrails. The budget governor reads real window utilisation from…, Never call the usage endpoint from a test. Returns ``None``, which is the same…, Belt and braces: the token must not be read from disk either. A test that needs…, budget(), test_budget_headroom_is_none_when_limit_unknown() (+1 more)

### Community 42 - "OpenRouterAdapter"
Cohesion: 0.12
Nodes (14): AsyncClient, Response, _HttpFailure, OpenRouterAdapter, Any, ClientFactory, Exception, Give a filesystem-less model a way to produce files. Without this the model… (+6 more)

### Community 43 - "parse_usage_line"
Cohesion: 0.13
Nodes (19): parse_usage_line(), Tokens charged against the 5-hour window. ``cache_read_weight`` exists because…, Extract one usage record, or None if this line does not carry usage. Tolerant…, window_tokens(), assistant_line(), Older records carry no cache_creation table. Dropping those tokens would under-…, A parser that raises on an unfamiliar line makes the budget unavailable exactly…, The CLI writes its own messages under model "<synthetic>". They carry a usage… (+11 more)

### Community 44 - "fetch_window_utilization"
Cohesion: 0.19
Nodes (16): allow_utilization_reads, fetch_window_utilization(), Read the CLI's OAuth access token, or None. Returns None for every failure…, Ask the meter. Returns None on any failure, never raises, never logs., read_oauth_token(), _creds(), Skip the round trip rather than send a token that will 401., The usage endpoint is itself rate-limited — observed returning 429. A governor… (+8 more)

### Community 45 - "browser.py"
Cohesion: 0.21
Nodes (13): available(), _cdp_alive(), ensure_browser(), _pid_matches_browser(), _publish_pid(), Path, Real browser control, for the work that only exists behind a login.…, Start the shared browser if it is not already running, and return its endpoint.… (+5 more)

### Community 46 - "Sleipnir — Overview"
Cohesion: 0.11
Nodes (18): File structure & modularity, Files created while running (not in the repo), Host control, in one paragraph, How the budget governor decides, How the code works (the walkthrough), How the router chooses a model, How to add code / extend it, How to run / test locally (+10 more)

### Community 47 - "FakeProcess"
Cohesion: 0.15
Nodes (5): StreamReader, FakeProcess, FakeStdin, Implements the SpawnedProcess protocol., _reader()

### Community 48 - "_manifest_for"
Cohesion: 0.18
Nodes (11): _manifest_for(), Manifest for a layered plan with every layer but the last two completed.…, This is the whole design in one assertion. A 600-task run must not cost the…, The orchestrator must never infer completeness from silence., Paths may cross into the manifest. Bytes may not., test_manifest_caps_are_enforced_not_merely_documented(), test_manifest_carries_no_artifact_contents(), test_manifest_reports_when_it_elided_content() (+3 more)

### Community 49 - "InputContract"
Cohesion: 0.15
Nodes (13): ArtifactRef, InputContract, A request for another task's *full* output rather than its summary. Three…, Everything a task is permitted to read. Nothing else is provided to it., Planner-declared upper bound on input size. Feeds tier selection., Input contracts are enforced as filesystem security boundaries., test_dependency_artifact_symlink_cannot_escape_its_attempt(), test_repository_file_symlink_cannot_escape_the_run_root() (+5 more)

### Community 50 - "Sleipnir — project instructions"
Cohesion: 0.14
Nodes (13): Checkpoint discipline, Environment on this machine, Lessons from the first real console session, Money and resources, Rules that will bite you if ignored, Security, Sleipnir — project instructions, The budget governor (Phase 4) (+5 more)

### Community 51 - "artifacts.py"
Cohesion: 0.18
Nodes (10): clip_summary(), contained_regular_file(), Attempt workspace layout and output collection. One directory per attempt,…, The subagent's self-written summary, if it produced one., Match what is on disk against what the task promised. Returns (produced,…, Files the task wrote but never declared. Recorded with an empty ``name`` rather…, Enforce the schema's hard summary cap at the write site. The schema *rejects*…, True only for a non-symlinked file physically beneath ``root``. Subagents… (+2 more)

### Community 52 - "_handle"
Cohesion: 0.15
Nodes (11): capability_brief(), _handle(), project_goal(), The brain is asleep exactly when a run owns the directory. Derived, never…, Return the goal for an exact ``/project`` command, else ``None``., Send one operator message to whoever is on duty., The brief, with this install's real executable path substituted in. Hard-coding…, refresh_brain_state() (+3 more)

### Community 53 - "fold_results"
Cohesion: 0.24
Nodes (14): fold_results(), _fold_task(), Recompute every task's status from the append-only result log. Records are…, AttemptStarted, Written *before* dispatch, flushed immediately. This record is what makes crash…, _bar(), _clip(), _latest_routes() (+6 more)

### Community 54 - "process_guard.py"
Cohesion: 0.50
Nodes (4): _install_parent_death_signal(), main(), Run a provider CLI with a Linux parent-death signal installed. An executor can…, Install SIGTERM-on-parent-death, closing the setup race explicitly.

### Community 55 - "process.py"
Cohesion: 0.14
Nodes (13): Signals, _default_spawn(), ProcessResult, _pump(), Any, Path, Protocol, Async subprocess execution with timeout, streaming capture, and tree kill.… (+5 more)

### Community 56 - "Plan"
Cohesion: 0.20
Nodes (4): RunReport, Plan, The task DAG. Validated as acyclic and referentially closed on load., All tasks transitively downstream of ``task_id``.

### Community 57 - "Sleipnir — Project State"
Cohesion: 0.15
Nodes (12): Current phase/stage, Decisions log, Environment on this machine, Goal, Guarded fast lane and `/project` (2026-08-19), Next steps, Open questions, Phase 6 progress (2026-08-18) (+4 more)

### Community 58 - "handoff.py"
Cohesion: 0.18
Nodes (17): answer(), await_answer(), HandoffError, pending(), Path, RuntimeError, Asking the operator for a credential from a process that has no terminal. The…, Block until the console answers, and return its *status* only. Returns one of… (+9 more)

### Community 59 - "WindowUtilization"
Cohesion: 0.25
Nodes (7): What the meter itself reports. Percentages, never tokens., Token limit consistent with ``used_tokens`` being this percentage., WindowUtilization, The reading is a percentage; everything downstream works in tokens. Solving…, Near zero the division explodes and would imply a wildly wrong limit., test_implied_limit_refuses_when_utilisation_is_too_small_to_divide_by(), test_implied_limit_solves_for_the_limit_matching_local_accounting()

### Community 61 - "RetryPolicy"
Cohesion: 0.33
Nodes (5): Tier to use on ``attempt`` (1-indexed). Falls back to ``base_tier``., RetryPolicy, test_escalation_ladder_cannot_exceed_retries(), test_retry_policy_rejects_non_retryable_kinds(), test_tier_for_attempt_walks_the_ladder()

### Community 62 - "ProcessRunner"
Cohesion: 0.25
Nodes (7): ProcessRunner, Spawner, Runs one child process to completion, a timeout, or a cancellation., test_chat_rejects_an_unbounded_response_without_loading_it(), test_chat_timeout_terminates_the_process_group(), test_chat_turn_uses_guarded_process_runner_and_stdin(), test_project_stage_uses_guarded_process_runner()

### Community 63 - "PriceSnapshot"
Cohesion: 0.29
Nodes (6): PriceSnapshot, Token and server-tool prices as fetched at dispatch time. Never populated from…, Cost of ``usage`` under this snapshot. Missing cache prices fall back to the…, test_cache_write_ttls_are_priced_separately(), test_missing_cache_prices_fall_back_without_undercounting(), test_server_tool_requests_are_priced_separately_from_tokens()

### Community 64 - "materialize_file_blocks"
Cohesion: 0.33
Nodes (6): materialize_file_blocks(), Path, Write ```file:<path> blocks into ``target_dir``. Paths are confined to the…, parametrize, test_file_blocks_cannot_escape_the_attempt_directory(), test_file_blocks_write_nested_paths()

### Community 66 - "RoutingDecision"
Cohesion: 0.50
Nodes (4): Phase 2 placeholder: a fixed tier -> (adapter, model) table from config. Phase…, StaticRouter, Everything `sleipnir explain <task-id>` needs. Written once per attempt., RoutingDecision

### Community 67 - "OutputContract"
Cohesion: 0.40
Nodes (4): OutputContract, What the task must produce, and how much of it may re-enter the manifest., What the duty officer sees. If this ever grew with the plan, the cheap stand-in…, test_the_run_digest_is_constant_size_and_carries_no_task_output()

## Knowledge Gaps
- **67 isolated node(s):** `sleipnir`, `The one invariant`, `Rules that will bite you if ignored`, `The router (Phase 3)`, `Money and resources` (+62 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **3 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Tier` connect `Tier` to `make_task`, `cli.py`, `TaskStatus`, `AttemptStatus`, `DispatchOutcome`, `test_adapters.py`, `DispatchRequest`, `BudgetGovernor`, `test_budget.py`, `Task`, `apply_revision`, `Executor`, `chat.py`, `planner.py`, `orchestrator.py`, `budget.py`, `TierRouter`, `test_schema.py`, `schema.py`, `RetryPolicy`, `RoutingDecision`, `OutputContract`?**
  _High betweenness centrality (0.101) - this node is a cross-community bridge._
- **Why does `make_task()` connect `make_task` to `OutputContract`, `test_adapters.py`, `test_schema.py`, `schema.py`, `Tier`, `test_budget.py`, `InputContract`, `Task`, `apply_revision`, `planner.py`, `make_chain`?**
  _High betweenness centrality (0.048) - this node is a cross-community bridge._
- **Why does `Plan` connect `Plan` to `make_task`, `cli.py`, `TaskStatus`, `console.py`, `BudgetGovernor`, `test_budget.py`, `ValueError`, `projection.py`, `Task`, `apply_revision`, `Executor`, `planner.py`, `make_chain`, `orchestrator.py`, `budget.py`, `test_schema.py`, `schema.py`, `InputContract`, `fold_results`, `OutputContract`?**
  _High betweenness centrality (0.045) - this node is a cross-community bridge._
- **Are the 5 inferred relationships involving `make_task()` (e.g. with `ExpectedOutput` and `InputContract`) actually correct?**
  _`make_task()` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 73 inferred relationships involving `Tier` (e.g. with `DispatchPreview` and `DispatchRequest`) actually correct?**
  _`Tier` has 73 INFERRED edges - model-reasoned connections that need verification._
- **Are the 25 inferred relationships involving `Task` (e.g. with `DispatchRequest` and `BudgetGovernor`) actually correct?**
  _`Task` has 25 INFERRED edges - model-reasoned connections that need verification._
- **Are the 50 inferred relationships involving `Adapter` (e.g. with `BaseAdapter` and `DispatchPreview`) actually correct?**
  _`Adapter` has 50 INFERRED edges - model-reasoned connections that need verification._