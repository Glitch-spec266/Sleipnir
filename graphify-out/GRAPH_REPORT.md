# Graph Report - Sleipnir  (2026-08-19)

## Corpus Check
- 60 files · ~79,327 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1552 nodes · 4495 edges · 57 communities (55 shown, 2 thin omitted)
- Extraction: 84% EXTRACTED · 16% INFERRED · 0% AMBIGUOUS · INFERRED: 723 edges (avg confidence: 0.51)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `792e1cdf`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- make_task
- cli.py
- TaskStatus
- apply_revision
- test_pricing.py
- DispatchRequest
- test_adapters.py
- test_cli.py
- ClaudeAdapter
- Tier
- ProcessRunner
- run_is_active
- Sleipnir — Phase 1 design
- projection.py
- test_budget.py
- ValueError
- fakes.py
- theme.py
- console.py
- budget.py
- Plan
- Task
- test_capabilities.py
- chat.py
- test_console.py
- clipboard.py
- BudgetGovernor
- schema.py
- orchestrator.py
- AttemptWorkspace
- Browser
- test_handoff.py
- fetch_window_utilization
- Secret
- current_window
- TerminalInputDecoder
- computer.py
- .__init__
- test_schema.py
- conftest.py
- AttemptFinished
- screenshot
- secrets.py
- browser.py
- Sleipnir — Overview
- WindowUtilization
- fold_results
- InputContract
- Sleipnir — project instructions
- planner.py
- _canonical_json
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
- `test_artifact_ref_rejects_path_escape()` --uses--> `ArtifactRef`  [INFERRED]
  tests/test_schema.py → src/sleipnir/schema.py
- `test_artifact_ref_rejects_wildcard_everything()` --uses--> `ArtifactRef`  [INFERRED]
  tests/test_schema.py → src/sleipnir/schema.py
- `test_thinking_tokens_cannot_exceed_output()` --uses--> `TokenUsage`  [INFERRED]
  tests/test_schema.py → src/sleipnir/schema.py
- `PlanningAdapter` --uses--> `DispatchRequest`  [INFERRED]
  tests/test_cli.py → src/sleipnir/adapters/base.py

## Import Cycles
- None detected.

## Communities (57 total, 2 thin omitted)

### Community 0 - "make_task"
Cohesion: 0.13
Nodes (64): RuntimeError, An attempt path existed before the harness claimed this attempt., WorkspaceCollisionError, ExecutorConfig, build(), plan_of(), Path, Executor: dependency order, concurrency cap, dry run, recovery, cancellation. (+56 more)

### Community 1 - "cli.py"
Cohesion: 0.06
Nodes (66): ArgumentParser, Namespace, render_decisions(), build_adapters(), build_parser(), CliError, cmd_apply_revision(), cmd_browser() (+58 more)

### Community 2 - "TaskStatus"
Cohesion: 0.10
Nodes (57): escalation_changes(), evaluate_gate(), GateVerdict, GroupState, GroupVerdict, StrEnum, The phase gate: what the brain is allowed to know when it wakes up. The…, Every group passed. The phase may be merged and the next one begun. (+49 more)

### Community 3 - "apply_revision"
Cohesion: 0.21
Nodes (22): apply_revision(), persist_revision(), datetime, Path, RuntimeError, Validated, auditable plan revision application. The orchestrator may propose…, Append the audit first, then atomically replace the derived plan view., Latest revision that made each completed descendant stale. (+14 more)

### Community 4 - "test_pricing.py"
Cohesion: 0.07
Nodes (50): CatalogUnavailableError, _first_int(), _float(), ModelCatalog, _nonnegative_float(), parse_models(), _per_mtok(), Any (+42 more)

### Community 5 - "DispatchRequest"
Cohesion: 0.07
Nodes (31): ABC, AdapterError, BaseAdapter, DispatchPreview, DispatchRequest, RuntimeError, The adapter interface. An adapter's job is narrow on purpose: take a fully-…, One dispatch backend. Auth is never implemented here. The `claude` and `codex`… (+23 more)

### Community 6 - "test_adapters.py"
Cohesion: 0.07
Nodes (69): AsyncClient, Response, _HttpFailure, materialize_file_blocks(), OpenRouterAdapter, Any, ClientFactory, Exception (+61 more)

### Community 7 - "test_cli.py"
Cohesion: 0.12
Nodes (42): extract_plan_json(), Pull a JSON object out of a model response. Tries the whole response first,…, invoke(), PlanningAdapter, fixture, parametrize, Path, CLI: the five commands, end to end, with no network and no spend. (+34 more)

### Community 8 - "ClaudeAdapter"
Cohesion: 0.18
Nodes (9): ClaudeAdapter, Any, Path, Spawner, Map the CLI's own status vocabulary onto FailureKind., Sum `modelUsage` across every model the dispatch actually used. A dispatch can…, The model that produced the most output — the one that did the work if a…, Flags verified against `claude --help` (CLI 2.1.234). The prompt goes over… (+1 more)

### Community 9 - "Tier"
Cohesion: 0.07
Nodes (66): The tier to dispatch ``task`` at, plus why if it moved., Backend, ConfigError, ModelOption, _opt_float(), _opt_int(), _parse_backends(), _parse_models() (+58 more)

### Community 10 - "ProcessRunner"
Cohesion: 0.20
Nodes (25): skipif, ProcessRunner, Runs one child process to completion, a timeout, or a cancellation., fake_spawner(), Any, Build a Spawner that yields FakeProcess objects. ``calls`` captures argv and…, test_chat_rejects_an_unbounded_response_without_loading_it(), test_chat_timeout_terminates_the_process_group() (+17 more)

### Community 11 - "run_is_active"
Cohesion: 0.29
Nodes (5): The brain is asleep exactly when a run owns the directory. Derived, never…, refresh_brain_state(), Path, Whether another file description currently owns the run lock., run_is_active()

### Community 12 - "Sleipnir — Phase 1 design"
Cohesion: 0.05
Nodes (38): Dollars and window quota are different resources, Files, Folding a percentage back into tokens, Module layout, Not built, on purpose, Other decisions worth overruling, Phase 2 — executor, Phase 3 — router (+30 more)

### Community 13 - "projection.py"
Cohesion: 0.11
Nodes (29): _alerts(), build_manifest(), _clip(), _evidence(), _frontier(), _group_rollups(), datetime, Pure derivation of run state from plan + results. Deliberately I/O-free: no… (+21 more)

### Community 14 - "test_budget.py"
Cohesion: 0.20
Nodes (27): config(), governor(), plan_of(), Path, Budget governor: usage parsing, window detection, projection, downshift. The…, Records recur across resumed sessions; 59% of the real corpus was duplicated.…, A trivial task on a subscription backend is not cheap: the spawn alone costs…, The governor must never stop or reroute a run on a number it could not verify. (+19 more)

### Community 15 - "ValueError"
Cohesion: 0.19
Nodes (5): field_validator, Self, model_validator, model_validator, ValueError

### Community 16 - "fakes.py"
Cohesion: 0.15
Nodes (6): StreamReader, FakeProcess, FakeStdin, Test doubles. The fake lives at the *spawn* boundary rather than replacing…, Implements the SpawnedProcess protocol., _reader()

### Community 17 - "theme.py"
Cohesion: 0.11
Nodes (24): _clip(), Model and provider text is untrusted; strip anything non-printable. Same trust…, render(), _wrap(), ease_back_out(), ease_power2_out(), fg(), _fit() (+16 more)

### Community 18 - "console.py"
Cohesion: 0.11
Nodes (30): apply_key(), _claude_dirs(), _clean_paste(), ConsoleState, Message, _paint(), paste_system_clipboard(), play_splash() (+22 more)

### Community 19 - "budget.py"
Cohesion: 0.13
Nodes (17): DownshiftDecision, _int(), _parse_bucket(), Any, datetime, Path, Budget governor: what the 5-hour window has cost, and what the plan will. Two…, # NOTE: `iterations` is deliberately ignored. It repeats the same counts (+9 more)

### Community 20 - "Plan"
Cohesion: 0.20
Nodes (6): Plan, The task DAG. Validated as acyclic and referentially closed on load., All tasks transitively downstream of ``task_id``., make_layered(), _plan(), A wide layered DAG: every task in layer k depends on three in layer k-1. This…

### Community 21 - "Task"
Cohesion: 0.08
Nodes (29): clip_summary(), Enforce the schema's hard summary cap at the write site. The schema *rejects*…, assert_checks_supported(), run_checks(), ConcurrentExecutionError, Executor, Governor, _pid_is_alive() (+21 more)

### Community 22 - "test_capabilities.py"
Cohesion: 0.08
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

### Community 26 - "BudgetGovernor"
Cohesion: 0.17
Nodes (10): BudgetGovernor, Projection, Estimates consumption and downshifts eligible tasks to stay inside it., The meter's own reading, cached briefly. None if unavailable. Disabled by…, Cost of everything still to run, at the tiers currently assigned., (window tokens, metered dollars) one attempt of ``task`` would cost. Fixed…, Assign a tier to every remaining task, downshifting until it fits. Downshifts…, The costliest task that can still move one rung down the ladder. (+2 more)

### Community 27 - "schema.py"
Cohesion: 0.11
Nodes (36): DispatchOutcome, What the adapter observed. Raw facts only, no derived accounting., Put sparse-brain spend on the same durable accounting stream., _record_control_result(), cost_from_outcome(), Compose the shared dollar/quota axes for worker and control calls., Combine what the provider said with what actually landed on disk. The…, Compose the two-axis cost record. For subscription dispatches ``amount_usd`` is… (+28 more)

### Community 28 - "orchestrator.py"
Cohesion: 0.18
Nodes (16): build_control_task(), control_instructions(), control_plan_context(), ControlDecision, ControlError, _extract_decision(), BaseModel, Path (+8 more)

### Community 29 - "AttemptWorkspace"
Cohesion: 0.05
Nodes (50): AcceptanceCheck, ArtifactDirResolver, AttemptWorkspace, contained_regular_file(), Any, Path, Ensure an already-claimed workspace remains a real local directory., Atomically claim a new attempt directory; never reuse old contents. (+42 more)

### Community 30 - "Browser"
Cohesion: 0.15
Nodes (9): Browser, Any, An open browser the agent can drive. Deliberately a thin wrapper: it exposes…, Attach to the shared browser, starting it only if nobody has. Attaching rather…, Detach. Deliberately does **not** close the browser. Closing it here is what…, Really end the shared browser, discarding its live tabs. The profile on disk…, CapabilityError, RuntimeError (+1 more)

### Community 31 - "test_handoff.py"
Cohesion: 0.07
Nodes (13): Sleipnir — a budget-aware agentic orchestrator. Phases 1–5 provide the schema,…, fixture, The credential handoff, and the three live bugs that produced it. Every test…, A full-screen redraw loop that does not switch buffers appends every frame to…, Drawing only one row of the horse emblem renders as debris., requests_dir(), test_the_banner_is_all_or_nothing(), test_the_console_uses_the_alternate_screen() (+5 more)

### Community 32 - "fetch_window_utilization"
Cohesion: 0.19
Nodes (16): allow_utilization_reads, fetch_window_utilization(), Read the CLI's OAuth access token, or None. Returns None for every failure…, Ask the meter. Returns None on any failure, never raises, never logs., read_oauth_token(), _creds(), Skip the round trip rather than send a token that will 401., The usage endpoint is itself rate-limited — observed returning 429. A governor… (+8 more)

### Community 33 - "Secret"
Cohesion: 0.15
Nodes (6): Put a captured credential into a form field and wipe it. Separate from ``fill``…, BaseException, TracebackType, A one-shot credential. Every representation hook is overridden. Without that,…, Yield the plaintext exactly once, then wipe the buffer., Secret

### Community 34 - "current_window"
Cohesion: 0.29
Nodes (7): current_window(), The active 5-hour block. Windows are anchored to first use and expire ``hours``…, Reporting full headroom is right; inventing consumption is not., test_a_gap_of_five_hours_starts_a_new_window(), test_empty_history_is_a_fresh_window(), test_no_recent_activity_reports_a_fresh_window(), test_window_is_anchored_to_first_use_not_a_rolling_lookback()

### Community 35 - "TerminalInputDecoder"
Cohesion: 0.40
Nodes (3): PastedText, Turn a byte stream into keys and atomic bracketed-paste events., TerminalInputDecoder

### Community 36 - "computer.py"
Cohesion: 0.15
Nodes (23): Any, Path, Append-only record of every privileged action taken on the host. Same…, record(), redact(), click(), copy(), ensure_daemon() (+15 more)

### Community 39 - "test_schema.py"
Cohesion: 0.06
Nodes (41): PriceSnapshot, Token and server-tool prices as fetched at dispatch time. Never populated from…, Cost of ``usage`` under this snapshot. Missing cache prices fall back to the…, RetryPolicy, budget(), _manifest_for(), parametrize, Phase 1 schema tests. The load-bearing test is… (+33 more)

### Community 41 - "conftest.py"
Cohesion: 0.29
Nodes (6): no_credential_reads(), no_real_utilization_reads(), fixture, Test-suite guardrails. The budget governor reads real window utilisation from…, Never call the usage endpoint from a test. Returns ``None``, which is the same…, Belt and braces: the token must not be read from disk either. A test that needs…

### Community 42 - "AttemptFinished"
Cohesion: 0.13
Nodes (22): _fold_task(), RuntimeError, Append-only reader/writer for ``results.jsonl``. Deliberately synchronous.…, Append-only attempt log. The single source of truth for run state., Append one record and fsync it. fsync per record is the cost of the recovery…, Read every record, tolerating exactly one torn trailing line. A crash mid-…, Attempts with a start and no finish — in flight when the process died., Raised when a non-final line fails to parse — that is real corruption, not the… (+14 more)

### Community 43 - "screenshot"
Cohesion: 0.22
Nodes (9): CompletedProcess, Probe, Path, Capture the full screen to ``path``. The agent reads the resulting image…, Run a shell command as the operator, with the operator's environment. This is…, What this machine can actually do, for ``sleipnir doctor``., run(), screenshot() (+1 more)

### Community 44 - "secrets.py"
Cohesion: 0.22
Nodes (7): Operator-authorised capabilities: the desk the robot sits at. Everything in…, capture(), RuntimeError, Credentials that live for one keystroke burst and then stop existing. The rule…, A secret was used twice. Deliberately fatal rather than forgiving: re-use…, Prompt the operator for a credential with echo disabled. Reads straight into a…, SecretConsumed

### Community 45 - "browser.py"
Cohesion: 0.24
Nodes (8): available(), _cdp_alive(), ensure_browser(), Path, Real browser control, for the work that only exists behind a login.…, Terminate the detached browser, if one is running. True if it stopped., Start the shared browser if it is not already running, and return its endpoint.…, stop_browser()

### Community 46 - "Sleipnir — Overview"
Cohesion: 0.11
Nodes (18): File structure & modularity, Files created while running (not in the repo), Host control, in one paragraph, How the budget governor decides, How the code works (the walkthrough), How the router chooses a model, How to add code / extend it, How to run / test locally (+10 more)

### Community 47 - "WindowUtilization"
Cohesion: 0.25
Nodes (7): What the meter itself reports. Percentages, never tokens., Token limit consistent with ``used_tokens`` being this percentage., WindowUtilization, The reading is a percentage; everything downstream works in tokens. Solving…, Near zero the division explodes and would imply a wildly wrong limit., test_implied_limit_refuses_when_utilisation_is_too_small_to_divide_by(), test_implied_limit_solves_for_the_limit_matching_local_accounting()

### Community 48 - "fold_results"
Cohesion: 0.18
Nodes (18): fold_results(), Recompute every task's status from the append-only result log. Records are…, finished(), make_chain(), t0000 -> t0001 -> ... Simple shape for status-folding tests., Replaying the log must not double-count cost — recovery depends on it., routing(), test_completed_task_is_superseded_when_spec_changes() (+10 more)

### Community 49 - "InputContract"
Cohesion: 0.19
Nodes (10): ArtifactRef, InputContract, A request for another task's *full* output rather than its summary. Three…, Everything a task is permitted to read. Nothing else is provided to it., Planner-declared upper bound on input size. Feeds tier selection., Input contracts are enforced as filesystem security boundaries., test_dependency_artifact_symlink_cannot_escape_its_attempt(), test_repository_file_symlink_cannot_escape_the_run_root() (+2 more)

### Community 50 - "Sleipnir — project instructions"
Cohesion: 0.14
Nodes (13): Checkpoint discipline, Environment on this machine, Lessons from the first real console session, Money and resources, Rules that will bite you if ignored, Security, Sleipnir — project instructions, The budget governor (Phase 4) (+5 more)

### Community 51 - "planner.py"
Cohesion: 0.14
Nodes (19): Attempt workspace layout and output collection. One directory per attempt,…, assemble_plan(), build_planner_task(), generate_plan(), planning_instructions(), PlanningError, Path, RuntimeError (+11 more)

### Community 52 - "_canonical_json"
Cohesion: 0.40
Nodes (4): _canonical_json(), Any, Stable digest of the task's *meaning*. Completed results are keyed by (task_id,…, Stable JSON encoding for hashing: sorted keys, no incidental whitespace.

### Community 54 - "process_guard.py"
Cohesion: 0.50
Nodes (4): _install_parent_death_signal(), main(), Run a provider CLI with a Linux parent-death signal installed. An executor can…, Install SIGTERM-on-parent-death, closing the setup race explicitly.

### Community 55 - "process.py"
Cohesion: 0.14
Nodes (13): Signals, _default_spawn(), ProcessResult, _pump(), Any, Path, Protocol, Async subprocess execution with timeout, streaming capture, and tree kill.… (+5 more)

### Community 56 - "parse_usage_line"
Cohesion: 0.13
Nodes (20): parse_usage_line(), Tokens charged against the 5-hour window. ``cache_read_weight`` exists because…, Extract one usage record, or None if this line does not carry usage. Tolerant…, window_tokens(), assistant_line(), Older records carry no cache_creation table. Dropping those tokens would under-…, A parser that raises on an unfamiliar line makes the budget unavailable exactly…, The CLI writes its own messages under model "<synthetic>". They carry a usage… (+12 more)

### Community 57 - "Sleipnir — Project State"
Cohesion: 0.15
Nodes (12): Current phase/stage, Decisions log, Environment on this machine, Goal, Guarded fast lane and `/project` (2026-08-19), Next steps, Open questions, Phase 6 progress (2026-08-18) (+4 more)

### Community 58 - "handoff.py"
Cohesion: 0.21
Nodes (12): answer(), await_answer(), pending(), Path, Asking the operator for a credential from a process that has no terminal. The…, Tell the waiting process what happened. Status only — never the value., A pending ask. Carries a label; never a value., File a request for the console to fulfil. (+4 more)

## Knowledge Gaps
- **67 isolated node(s):** `sleipnir`, `The one invariant`, `Rules that will bite you if ignored`, `The router (Phase 3)`, `Money and resources` (+62 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **2 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Tier` connect `Tier` to `make_task`, `cli.py`, `TaskStatus`, `apply_revision`, `DispatchRequest`, `test_adapters.py`, `test_schema.py`, `test_budget.py`, `fold_results`, `budget.py`, `planner.py`, `Task`, `chat.py`, `BudgetGovernor`, `schema.py`, `orchestrator.py`?**
  _High betweenness centrality (0.074) - this node is a cross-community bridge._
- **Why does `Task` connect `Task` to `make_task`, `cli.py`, `TaskStatus`, `DispatchRequest`, `test_schema.py`, `Tier`, `AttemptFinished`, `projection.py`, `ValueError`, `budget.py`, `planner.py`, `Plan`, `_canonical_json`, `process.py`, `BudgetGovernor`, `schema.py`, `orchestrator.py`, `AttemptWorkspace`?**
  _High betweenness centrality (0.059) - this node is a cross-community bridge._
- **Why does `Plan` connect `Plan` to `make_task`, `cli.py`, `TaskStatus`, `apply_revision`, `Tier`, `projection.py`, `test_budget.py`, `ValueError`, `console.py`, `budget.py`, `Task`, `BudgetGovernor`, `schema.py`, `orchestrator.py`, `test_schema.py`, `AttemptFinished`, `fold_results`, `InputContract`, `planner.py`?**
  _High betweenness centrality (0.054) - this node is a cross-community bridge._
- **Are the 5 inferred relationships involving `make_task()` (e.g. with `ExpectedOutput` and `InputContract`) actually correct?**
  _`make_task()` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 73 inferred relationships involving `Tier` (e.g. with `DispatchPreview` and `DispatchRequest`) actually correct?**
  _`Tier` has 73 INFERRED edges - model-reasoned connections that need verification._
- **Are the 25 inferred relationships involving `Task` (e.g. with `DispatchRequest` and `BudgetGovernor`) actually correct?**
  _`Task` has 25 INFERRED edges - model-reasoned connections that need verification._
- **Are the 50 inferred relationships involving `Adapter` (e.g. with `BaseAdapter` and `DispatchPreview`) actually correct?**
  _`Adapter` has 50 INFERRED edges - model-reasoned connections that need verification._