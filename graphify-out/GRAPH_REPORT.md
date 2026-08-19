# Graph Report - Sleipnir  (2026-08-19)

## Corpus Check
- 60 files · ~82,086 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1581 nodes · 4550 edges · 70 communities (65 shown, 5 thin omitted)
- Extraction: 84% EXTRACTED · 16% INFERRED · 0% AMBIGUOUS · INFERRED: 724 edges (avg confidence: 0.51)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `85b51bca`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- make_task
- cli.py
- TaskStatus
- Adapter
- test_pricing.py
- base.py
- test_adapters.py
- test_cli.py
- DispatchRequest
- Tier
- ProcessRunner
- console.py
- Sleipnir — Phase 1 design
- BudgetGovernor
- test_budget.py
- ValueError
- schema.py
- theme.py
- Governor
- context.py
- revisions.py
- Executor
- test_capabilities.py
- chat.py
- test_console.py
- clipboard.py
- planner.py
- fold_results
- orchestrator.py
- AttemptWorkspace
- Browser
- test_handoff.py
- budget.py
- Secret
- _canonical_json
- TerminalInputDecoder
- computer.py
- DispatchOutcome
- Task
- test_schema.py
- checks.py
- BudgetSnapshot
- OpenRouterAdapter
- parse_usage_line
- fetch_window_utilization
- browser.py
- Sleipnir — Overview
- fakes.py
- SleipnirConfig
- config.py
- Sleipnir — project instructions
- test_theme.py
- _handle
- AttemptFinished
- process_guard.py
- .run
- Plan
- Sleipnir — Project State
- handoff.py
- WindowUtilization
- sleipnir
- .tier_for_attempt
- .__init__
- WorkspaceCollisionError
- current_window
- CodexInvocation
- fake_ydotool
- UnsupportedCheckError
- sleipnir/__init__.py
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

## Communities (70 total, 5 thin omitted)

### Community 0 - "make_task"
Cohesion: 0.11
Nodes (72): ExecutorConfig, apply_revision(), RevisionChange, RevisionOp, build(), plan_of(), Path, Executor: dependency order, concurrency cap, dry run, recovery, cancellation. (+64 more)

### Community 1 - "cli.py"
Cohesion: 0.08
Nodes (62): ArgumentParser, Namespace, render_decisions(), build_adapters(), build_parser(), CliError, cmd_apply_revision(), cmd_browser() (+54 more)

### Community 2 - "TaskStatus"
Cohesion: 0.10
Nodes (53): escalation_changes(), evaluate_gate(), GateVerdict, GroupState, GroupVerdict, StrEnum, The phase gate: what the brain is allowed to know when it wakes up. The…, Every group passed. The phase may be merged and the next one begun. (+45 more)

### Community 3 - "Adapter"
Cohesion: 0.12
Nodes (34): cost_from_outcome(), Compose the shared dollar/quota axes for worker and control calls., Compose the two-axis cost record. For subscription dispatches ``amount_usd`` is…, Phase 2 placeholder: a fixed tier -> (adapter, model) table from config. Phase…, StaticRouter, Adapter, AttemptStatus, BillingMode (+26 more)

### Community 4 - "test_pricing.py"
Cohesion: 0.07
Nodes (50): CatalogUnavailableError, _first_int(), _float(), ModelCatalog, _nonnegative_float(), parse_models(), _per_mtok(), Any (+42 more)

### Community 5 - "base.py"
Cohesion: 0.10
Nodes (19): ABC, AdapterError, BaseAdapter, DispatchPreview, RuntimeError, The adapter interface. An adapter's job is narrow on purpose: take a fully-…, One dispatch backend. Auth is never implemented here. The `claude` and `codex`…, Describe the dispatch without performing it. No network, no spawn. (+11 more)

### Community 6 - "test_adapters.py"
Cohesion: 0.11
Nodes (57): materialize_file_blocks(), Path, Write ```file:<path> blocks into ``target_dir``. Paths are confined to the…, claude_adapter(), openrouter(), parametrize, Path, Adapter tests. Every adapter is driven end to end against a fake. The Claude… (+49 more)

### Community 7 - "test_cli.py"
Cohesion: 0.12
Nodes (42): extract_plan_json(), Pull a JSON object out of a model response. Tries the whole response first,…, invoke(), PlanningAdapter, fixture, parametrize, Path, CLI: the five commands, end to end, with no network and no spend. (+34 more)

### Community 8 - "DispatchRequest"
Cohesion: 0.17
Nodes (11): DispatchRequest, Everything an adapter needs. Fully resolved — adapters never route., ClaudeAdapter, Any, Path, Spawner, Map the CLI's own status vocabulary onto FailureKind., Sum `modelUsage` across every model the dispatch actually used. A dispatch can… (+3 more)

### Community 9 - "Tier"
Cohesion: 0.17
Nodes (32): Capability classes. A plan declares a tier; the router resolves a model. Fixed…, Tier, config(), model(), Router: tier -> model, filters, preference order, and explainability., The measured ~30k fixed cost of a `claude -p` spawn is why mechanical work…, The operator knows their own plan better than a price table does., Missing catalogue metadata is uncertainty, not evidence of insufficiency. (+24 more)

### Community 10 - "ProcessRunner"
Cohesion: 0.20
Nodes (25): skipif, ProcessRunner, Runs one child process to completion, a timeout, or a cancellation., fake_spawner(), Any, Build a Spawner that yields FakeProcess objects. ``calls`` captures argv and…, test_chat_rejects_an_unbounded_response_without_loading_it(), test_chat_timeout_terminates_the_process_group() (+17 more)

### Community 11 - "console.py"
Cohesion: 0.11
Nodes (32): _allocate_project_run(), apply_key(), _claude_dirs(), _clean_paste(), ConsoleState, Message, _paint(), paste_system_clipboard() (+24 more)

### Community 12 - "Sleipnir — Phase 1 design"
Cohesion: 0.05
Nodes (38): Dollars and window quota are different resources, Files, Folding a percentage back into tokens, Module layout, Not built, on purpose, Other decisions worth overruling, Phase 2 — executor, Phase 3 — router (+30 more)

### Community 13 - "BudgetGovernor"
Cohesion: 0.15
Nodes (11): BudgetGovernor, Projection, Estimates consumption and downshifts eligible tasks to stay inside it., The meter's own reading, cached briefly. None if unavailable. Disabled by…, Cost of everything still to run, at the tiers currently assigned., (window tokens, metered dollars) one attempt of ``task`` would cost. Fixed…, Assign a tier to every remaining task, downshifting until it fits. Downshifts…, The costliest task that can still move one rung down the ladder. (+3 more)

### Community 14 - "test_budget.py"
Cohesion: 0.20
Nodes (27): config(), governor(), plan_of(), Path, Budget governor: usage parsing, window detection, projection, downshift. The…, Records recur across resumed sessions; 59% of the real corpus was duplicated.…, A trivial task on a subscription backend is not cheap: the spawn alone costs…, The governor must never stop or reroute a run on a number it could not verify. (+19 more)

### Community 15 - "ValueError"
Cohesion: 0.14
Nodes (8): field_validator, Self, ClientFactory, model_validator, _find_cycle(), model_validator, Return one concrete cycle as a readable path, or None. Iterative (deep DAGs…, ValueError

### Community 16 - "schema.py"
Cohesion: 0.11
Nodes (37): _alerts(), build_manifest(), _clip(), _evidence(), _fold_task(), _frontier(), _group_rollups(), _propagate_dependencies() (+29 more)

### Community 17 - "theme.py"
Cohesion: 0.11
Nodes (24): _clip(), Model and provider text is untrusted; strip anything non-printable. Same trust…, render(), _wrap(), ease_back_out(), ease_power2_out(), fg(), _fit() (+16 more)

### Community 18 - "Governor"
Cohesion: 0.29
Nodes (5): Governor, Protocol, Budget control. Implemented by BudgetGovernor (Phase 4)., Tier -> concrete model. Implemented by TierRouter. ``downshift_reason`` is how…, Router

### Community 19 - "context.py"
Cohesion: 0.17
Nodes (19): ArtifactDirResolver, contained_regular_file(), True only for a non-symlinked file physically beneath ``root``. Subagents…, _artifact_section(), _describe_check(), _file_section(), IncludedInput, _output_section() (+11 more)

### Community 20 - "revisions.py"
Cohesion: 0.40
Nodes (4): datetime, Validated, auditable plan revision application. The orchestrator may propose…, PlanRevision, One append to revisions.jsonl. Makes re-planning auditable. ``superseded`` and…

### Community 21 - "Executor"
Cohesion: 0.10
Nodes (20): clip_summary(), Enforce the schema's hard summary cap at the write site. The schema *rejects*…, assert_checks_supported(), ConcurrentExecutionError, Executor, _pid_is_alive(), datetime, RuntimeError (+12 more)

### Community 22 - "test_capabilities.py"
Cohesion: 0.07
Nodes (3): _entries(), Capability tests are hermetic by construction. Nothing here may inject a real…, test_capture_records_only_the_label_and_length()

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
Cohesion: 0.12
Nodes (21): assemble_plan(), build_planner_task(), generate_plan(), planning_instructions(), PlanningError, Path, RuntimeError, Decomposition: one prompt in, a validated task DAG out. The planner is itself a… (+13 more)

### Community 27 - "fold_results"
Cohesion: 0.24
Nodes (10): fold_results(), Recompute every task's status from the append-only result log. Records are…, make_chain(), t0000 -> t0001 -> ... Simple shape for status-folding tests., Replaying the log must not double-count cost — recovery depends on it., test_completed_task_is_superseded_when_spec_changes(), test_descendants_are_transitive(), test_fold_is_idempotent_over_replayed_records() (+2 more)

### Community 28 - "orchestrator.py"
Cohesion: 0.18
Nodes (16): build_control_task(), control_instructions(), control_plan_context(), ControlDecision, ControlError, _extract_decision(), BaseModel, Path (+8 more)

### Community 29 - "AttemptWorkspace"
Cohesion: 0.12
Nodes (11): AttemptWorkspace, Any, Path, Write one harness-owned top-level file without following symlinks. The…, The subagent's self-written summary, if it produced one., Match what is on disk against what the task promised. Returns (produced,…, Files the task wrote but never declared. Recorded with an empty ``name`` rather…, Filesystem home for one attempt. Paths recorded in results.jsonl are always… (+3 more)

### Community 30 - "Browser"
Cohesion: 0.14
Nodes (9): Browser, Any, An open browser the agent can drive. Deliberately a thin wrapper: it exposes…, Attach to the shared browser, starting it only if nobody has. Attaching rather…, Detach. Deliberately does **not** close the browser. Closing it here is what…, Really end the shared browser, discarding its live tabs. The profile on disk…, CapabilityError, RuntimeError (+1 more)

### Community 31 - "test_handoff.py"
Cohesion: 0.09
Nodes (7): fixture, The credential handoff, and the three live bugs that produced it. Every test…, A full-screen redraw loop that does not switch buffers appends every frame to…, Drawing only one row of the horse emblem renders as debris., requests_dir(), test_the_banner_is_all_or_nothing(), test_the_console_uses_the_alternate_screen()

### Community 32 - "budget.py"
Cohesion: 0.23
Nodes (10): DownshiftDecision, _parse_bucket(), datetime, Path, Budget governor: what the 5-hour window has cost, and what the plan will. Two…, # NOTE: `iterations` is deliberately ignored. It repeats the same counts, Read every project transcript and return deduplicated usage records., scan_usage() (+2 more)

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
Cohesion: 0.15
Nodes (11): DispatchOutcome, Run the request to completion, a timeout, or a cancellation. Implementations…, What the adapter observed. Raw facts only, no derived accounting., CodexAdapter, _first_int(), Any, Path, Walk every event for the last recognisable usage block. Deliberately structure-… (+3 more)

### Community 38 - "Task"
Cohesion: 0.11
Nodes (19): Backend, What a tier requires and which backends it prefers, in order., TierPolicy, CatalogSnapshot, ModelInfo, One comparable number for ranking. Tasks are input-heavy, so a plain average…, CandidateEval, _movement() (+11 more)

### Community 39 - "test_schema.py"
Cohesion: 0.06
Nodes (44): ArtifactRef, PriceSnapshot, A request for another task's *full* output rather than its summary. Three…, Token and server-tool prices as fetched at dispatch time. Never populated from…, Cost of ``usage`` under this snapshot. Missing cache prices fall back to the…, RetryPolicy, _manifest_for(), parametrize (+36 more)

### Community 40 - "checks.py"
Cohesion: 0.22
Nodes (18): AcceptanceCheck, _check_command(), _check_files(), _check_json_schema(), _dispatch_check(), Any, Acceptance checks. Checks run *after* the adapter returns and decide whether…, A deliberate *subset* of JSON Schema: type, required, properties, items, enum,… (+10 more)

### Community 41 - "BudgetSnapshot"
Cohesion: 0.13
Nodes (11): BudgetSnapshot, Governor's view of the current 5-hour window. Recomputed, never stored., no_credential_reads(), no_real_utilization_reads(), fixture, Test-suite guardrails. The budget governor reads real window utilisation from…, Never call the usage endpoint from a test. Returns ``None``, which is the same…, Belt and braces: the token must not be read from disk either. A test that needs… (+3 more)

### Community 42 - "OpenRouterAdapter"
Cohesion: 0.14
Nodes (13): AsyncClient, Response, _HttpFailure, OpenRouterAdapter, Any, Exception, Give a filesystem-less model a way to produce files. Without this the model…, Consume the SSE stream, writing every raw line to disk as it lands. Streaming… (+5 more)

### Community 43 - "parse_usage_line"
Cohesion: 0.11
Nodes (24): _int(), parse_usage_line(), Any, One deduplicated, priced-elsewhere assistant turn., Tokens charged against the 5-hour window. ``cache_read_weight`` exists because…, Extract one usage record, or None if this line does not carry usage. Tolerant…, UsageRecord, window_tokens() (+16 more)

### Community 44 - "fetch_window_utilization"
Cohesion: 0.19
Nodes (16): allow_utilization_reads, fetch_window_utilization(), Read the CLI's OAuth access token, or None. Returns None for every failure…, Ask the meter. Returns None on any failure, never raises, never logs., read_oauth_token(), _creds(), Skip the round trip rather than send a token that will 401., The usage endpoint is itself rate-limited — observed returning 429. A governor… (+8 more)

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
Cohesion: 0.26
Nodes (13): ConfigError, Path, Configuration is unusable. Always raised before anything is dispatched., SleipnirConfig, parametrize, test_catalog_locations_must_be_nonempty_strings(), test_dangerous_numeric_config_is_rejected(), test_fractional_integer_and_string_list_policy_values_are_rejected() (+5 more)

### Community 49 - "config.py"
Cohesion: 0.37
Nodes (12): ModelOption, _opt_float(), _opt_int(), _parse_backends(), _parse_models(), _parse_tiers(), Any, Configuration: backends and per-tier routing policy. TOML via stdlib `tomllib`… (+4 more)

### Community 50 - "Sleipnir — project instructions"
Cohesion: 0.14
Nodes (13): Checkpoint discipline, Environment on this machine, Lessons from the first real console session, Money and resources, Rules that will bite you if ignored, Security, Sleipnir — project instructions, The budget governor (Phase 4) (+5 more)

### Community 51 - "test_theme.py"
Cohesion: 0.19
Nodes (5): The chrome must stay a pure function of the frame number, and must never be…, test_frame_lines_never_exceed_requested_width(), test_splash_ends_fully_revealed(), test_splash_renders_every_frame_at_a_narrow_terminal(), _visible()

### Community 52 - "_handle"
Cohesion: 0.15
Nodes (11): capability_brief(), _handle(), project_goal(), The brain is asleep exactly when a run owns the directory. Derived, never…, Return the goal for an exact ``/project`` command, else ``None``., Send one operator message to whoever is on duty., The brief, with this install's real executable path substituted in. Hard-coding…, refresh_brain_state() (+3 more)

### Community 53 - "AttemptFinished"
Cohesion: 0.13
Nodes (21): RuntimeError, Append-only reader/writer for ``results.jsonl``. Deliberately synchronous.…, Append-only attempt log. The single source of truth for run state., Append one record and fsync it. fsync per record is the cost of the recovery…, Read every record, tolerating exactly one torn trailing line. A crash mid-…, Attempts with a start and no finish — in flight when the process died., Raised when a non-final line fails to parse — that is real corruption, not the…, ResultLog (+13 more)

### Community 54 - "process_guard.py"
Cohesion: 0.50
Nodes (4): _install_parent_death_signal(), main(), Run a provider CLI with a Linux parent-death signal installed. An executor can…, Install SIGTERM-on-parent-death, closing the setup race explicitly.

### Community 55 - ".run"
Cohesion: 0.15
Nodes (12): Signals, _default_spawn(), ProcessResult, _pump(), Any, Path, Protocol, SIGTERM the group, allow a grace period, then SIGKILL. Shielded because this… (+4 more)

### Community 56 - "Plan"
Cohesion: 0.22
Nodes (6): Plan, The task DAG. Validated as acyclic and referentially closed on load., All tasks transitively downstream of ``task_id``., make_layered(), _plan(), A wide layered DAG: every task in layer k depends on three in layer k-1. This…

### Community 57 - "Sleipnir — Project State"
Cohesion: 0.15
Nodes (12): Current phase/stage, Decisions log, Environment on this machine, Goal, Guarded fast lane and `/project` (2026-08-19), Next steps, Open questions, Phase 6 progress (2026-08-18) (+4 more)

### Community 58 - "handoff.py"
Cohesion: 0.18
Nodes (17): answer(), await_answer(), HandoffError, pending(), Path, RuntimeError, Asking the operator for a credential from a process that has no terminal. The…, Block until the console answers, and return its *status* only. Returns one of… (+9 more)

### Community 59 - "WindowUtilization"
Cohesion: 0.25
Nodes (7): What the meter itself reports. Percentages, never tokens., Token limit consistent with ``used_tokens`` being this percentage., WindowUtilization, The reading is a percentage; everything downstream works in tokens. Solving…, Near zero the division explodes and would imply a wildly wrong limit., test_implied_limit_refuses_when_utilisation_is_too_small_to_divide_by(), test_implied_limit_solves_for_the_limit_matching_local_accounting()

### Community 63 - "WorkspaceCollisionError"
Cohesion: 0.33
Nodes (5): RuntimeError, Ensure an already-claimed workspace remains a real local directory., Atomically claim a new attempt directory; never reuse old contents., An attempt path existed before the harness claimed this attempt., WorkspaceCollisionError

### Community 64 - "current_window"
Cohesion: 0.29
Nodes (7): current_window(), The active 5-hour block. Windows are anchored to first use and expire ``hours``…, Reporting full headroom is right; inventing consumption is not., test_a_gap_of_five_hours_starts_a_new_window(), test_empty_history_is_a_fresh_window(), test_no_recent_activity_reports_a_fresh_window(), test_window_is_anchored_to_first_use_not_a_rolling_lookback()

### Community 65 - "CodexInvocation"
Cohesion: 0.40
Nodes (3): CodexInvocation, Spawner, How to call the CLI. Data, not dispatch logic.

### Community 66 - "fake_ydotool"
Cohesion: 0.50
Nodes (4): audit_log(), fake_ydotool(), fixture, Capture ydotool argv instead of running it.

### Community 67 - "UnsupportedCheckError"
Cohesion: 0.67
Nodes (3): RuntimeError, Raised at startup, not per task. A plan that cannot be fully checked must fail…, UnsupportedCheckError

## Knowledge Gaps
- **67 isolated node(s):** `sleipnir`, `The one invariant`, `Rules that will bite you if ignored`, `The router (Phase 3)`, `Money and resources` (+62 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **5 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Tier` connect `Tier` to `make_task`, `cli.py`, `TaskStatus`, `Adapter`, `base.py`, `test_adapters.py`, `DispatchRequest`, `BudgetGovernor`, `test_budget.py`, `schema.py`, `Governor`, `Executor`, `chat.py`, `planner.py`, `orchestrator.py`, `budget.py`, `Task`, `test_schema.py`, `SleipnirConfig`, `config.py`, `.tier_for_attempt`, `test_spec_hash_ignores_routing_fields`?**
  _High betweenness centrality (0.079) - this node is a cross-community bridge._
- **Why does `Plan` connect `Plan` to `budget.py`, `cli.py`, `TaskStatus`, `make_task`, `Task`, `test_adapters.py`, `test_schema.py`, `console.py`, `BudgetGovernor`, `test_budget.py`, `ValueError`, `schema.py`, `revisions.py`, `Executor`, `AttemptFinished`, `planner.py`, `fold_results`, `orchestrator.py`?**
  _High betweenness centrality (0.056) - this node is a cross-community bridge._
- **Why does `make_task()` connect `make_task` to `Adapter`, `test_spec_hash_ignores_routing_fields`, `test_adapters.py`, `test_schema.py`, `checks.py`, `Tier`, `Task`, `test_budget.py`, `context.py`, `Plan`, `planner.py`, `fold_results`?**
  _High betweenness centrality (0.047) - this node is a cross-community bridge._
- **Are the 5 inferred relationships involving `make_task()` (e.g. with `ExpectedOutput` and `InputContract`) actually correct?**
  _`make_task()` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 73 inferred relationships involving `Tier` (e.g. with `DispatchPreview` and `DispatchRequest`) actually correct?**
  _`Tier` has 73 INFERRED edges - model-reasoned connections that need verification._
- **Are the 25 inferred relationships involving `Task` (e.g. with `DispatchRequest` and `BudgetGovernor`) actually correct?**
  _`Task` has 25 INFERRED edges - model-reasoned connections that need verification._
- **Are the 50 inferred relationships involving `Adapter` (e.g. with `BaseAdapter` and `DispatchPreview`) actually correct?**
  _`Adapter` has 50 INFERRED edges - model-reasoned connections that need verification._