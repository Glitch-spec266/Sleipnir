# Graph Report - Sleipnir  (2026-08-19)

## Corpus Check
- 60 files · ~80,436 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1571 nodes · 4527 edges · 58 communities (55 shown, 3 thin omitted)
- Extraction: 84% EXTRACTED · 16% INFERRED · 0% AMBIGUOUS · INFERRED: 723 edges (avg confidence: 0.51)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `b409e2e4`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- make_task
- cli.py
- TaskStatus
- executor.py
- test_pricing.py
- schema.py
- test_adapters.py
- Adapter
- DispatchRequest
- Tier
- ProcessRunner
- ConsoleState
- Sleipnir — Phase 1 design
- BudgetGovernor
- test_budget.py
- ValueError
- _canonical_json
- theme.py
- console.py
- budget.py
- SleipnirConfig
- Executor
- test_capabilities.py
- chat.py
- test_console.py
- clipboard.py
- apply_revision
- fold_results
- orchestrator.py
- AttemptWorkspace
- Browser
- test_handoff.py
- fetch_window_utilization
- Secret
- context.py
- TerminalInputDecoder
- computer.py
- .__init__
- Task
- test_schema.py
- checks.py
- budget
- OpenRouterAdapter
- screenshot
- TokenUsage
- browser.py
- Sleipnir — Overview
- fakes.py
- Plan
- InputContract
- Sleipnir — project instructions
- UnsupportedCheckError
- ._artifact_dir_for
- process_guard.py
- process.py
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

## Communities (58 total, 3 thin omitted)

### Community 0 - "make_task"
Cohesion: 0.08
Nodes (90): RuntimeError, An attempt path existed before the harness claimed this attempt., WorkspaceCollisionError, ExecutorConfig, Append-only reader/writer for ``results.jsonl``. Deliberately synchronous.…, Append-only attempt log. The single source of truth for run state., Append one record and fsync it. fsync per record is the cost of the recovery…, Read every record, tolerating exactly one torn trailing line. A crash mid-… (+82 more)

### Community 1 - "cli.py"
Cohesion: 0.06
Nodes (72): ArgumentParser, Namespace, render_decisions(), build_adapters(), build_parser(), CliError, cmd_apply_revision(), cmd_browser() (+64 more)

### Community 2 - "TaskStatus"
Cohesion: 0.06
Nodes (85): escalation_changes(), evaluate_gate(), GateVerdict, GroupState, GroupVerdict, StrEnum, The phase gate: what the brain is allowed to know when it wakes up. The…, Every group passed. The phase may be merged and the next one begun. (+77 more)

### Community 3 - "executor.py"
Cohesion: 0.11
Nodes (32): DispatchOutcome, What the adapter observed. Raw facts only, no derived accounting., clip_summary(), Enforce the schema's hard summary cap at the write site. The schema *rejects*…, Put sparse-brain spend on the same durable accounting stream., _record_control_result(), cost_from_outcome(), datetime (+24 more)

### Community 4 - "test_pricing.py"
Cohesion: 0.08
Nodes (47): _first_int(), _float(), ModelCatalog, _nonnegative_float(), parse_models(), _per_mtok(), Any, ClientFactory (+39 more)

### Community 5 - "schema.py"
Cohesion: 0.09
Nodes (24): ABC, AdapterError, BaseAdapter, DispatchPreview, RuntimeError, The adapter interface. An adapter's job is narrow on purpose: take a fully-…, One dispatch backend. Auth is never implemented here. The `claude` and `codex`…, Describe the dispatch without performing it. No network, no spawn. (+16 more)

### Community 6 - "test_adapters.py"
Cohesion: 0.13
Nodes (54): claude_adapter(), openrouter(), parametrize, Path, Adapter tests. Every adapter is driven end to end against a fake. The Claude…, The whole point: `usage.input_tokens` is 10, `modelUsage` is 907., Prompts carry file contents; argv has a length limit and is world-readable., Regression: seeding on (task, attempt) alone made every resume collide with… (+46 more)

### Community 7 - "Adapter"
Cohesion: 0.13
Nodes (44): extract_plan_json(), Pull a JSON object out of a model response. Tries the whole response first,…, Adapter, Dispatch backends. Auth is always delegated to the official tool., invoke(), PlanningAdapter, fixture, parametrize (+36 more)

### Community 8 - "DispatchRequest"
Cohesion: 0.14
Nodes (12): DispatchRequest, Run the request to completion, a timeout, or a cancellation. Implementations…, Everything an adapter needs. Fully resolved — adapters never route., ClaudeAdapter, Any, Path, Spawner, Map the CLI's own status vocabulary onto FailureKind. (+4 more)

### Community 9 - "Tier"
Cohesion: 0.15
Nodes (33): Tier to use on ``attempt`` (1-indexed). Falls back to ``base_tier``., Capability classes. A plan declares a tier; the router resolves a model. Fixed…, Tier, config(), model(), Router: tier -> model, filters, preference order, and explainability., The measured ~30k fixed cost of a `claude -p` spawn is why mechanical work…, The operator knows their own plan better than a price table does. (+25 more)

### Community 10 - "ProcessRunner"
Cohesion: 0.20
Nodes (25): skipif, ProcessRunner, Runs one child process to completion, a timeout, or a cancellation., fake_spawner(), Any, Build a Spawner that yields FakeProcess objects. ``calls`` captures argv and…, test_chat_rejects_an_unbounded_response_without_loading_it(), test_chat_timeout_terminates_the_process_group() (+17 more)

### Community 11 - "ConsoleState"
Cohesion: 0.15
Nodes (15): _claude_dirs(), ConsoleState, Message, _project_argv(), Path, Everything the renderer needs, and nothing it does not. Notably absent: any…, The brain is asleep exactly when a run owns the directory. Derived, never…, A constant-size picture of the run, for the duty officer. This is the whole… (+7 more)

### Community 12 - "Sleipnir — Phase 1 design"
Cohesion: 0.05
Nodes (38): Dollars and window quota are different resources, Files, Folding a percentage back into tokens, Module layout, Not built, on purpose, Other decisions worth overruling, Phase 2 — executor, Phase 3 — router (+30 more)

### Community 13 - "BudgetGovernor"
Cohesion: 0.11
Nodes (13): BudgetGovernor, Projection, Estimates consumption and downshifts eligible tasks to stay inside it., The meter's own reading, cached briefly. None if unavailable. Disabled by…, Cost of everything still to run, at the tiers currently assigned., (window tokens, metered dollars) one attempt of ``task`` would cost. Fixed…, Assign a tier to every remaining task, downshifting until it fits. Downshifts…, The costliest task that can still move one rung down the ladder. (+5 more)

### Community 14 - "test_budget.py"
Cohesion: 0.10
Nodes (47): parse_usage_line(), Tokens charged against the 5-hour window. ``cache_read_weight`` exists because…, Extract one usage record, or None if this line does not carry usage. Tolerant…, window_tokens(), assistant_line(), config(), governor(), plan_of() (+39 more)

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

### Community 19 - "budget.py"
Cohesion: 0.11
Nodes (21): current_window(), DownshiftDecision, _int(), _parse_bucket(), Any, datetime, Path, Budget governor: what the 5-hour window has cost, and what the plan will. Two… (+13 more)

### Community 20 - "SleipnirConfig"
Cohesion: 0.18
Nodes (25): ConfigError, ModelOption, _opt_float(), _opt_int(), _parse_backends(), _parse_models(), _parse_tiers(), Any (+17 more)

### Community 21 - "Executor"
Cohesion: 0.11
Nodes (16): assert_checks_supported(), ConcurrentExecutionError, Executor, _pid_is_alive(), RuntimeError, Everything the run would dispatch, spending nothing. Walks the DAG in…, Execute while holding exclusive ownership of the run directory., Close attempts whose executor died before writing a terminal record. The start… (+8 more)

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

### Community 26 - "apply_revision"
Cohesion: 0.21
Nodes (22): apply_revision(), persist_revision(), datetime, Path, RuntimeError, Validated, auditable plan revision application. The orchestrator may propose…, Append the audit first, then atomically replace the derived plan view., Latest revision that made each completed descendant stale. (+14 more)

### Community 27 - "fold_results"
Cohesion: 0.18
Nodes (18): fold_results(), Recompute every task's status from the append-only result log. Records are…, finished(), make_chain(), t0000 -> t0001 -> ... Simple shape for status-folding tests., Replaying the log must not double-count cost — recovery depends on it., routing(), test_completed_task_is_superseded_when_spec_changes() (+10 more)

### Community 28 - "orchestrator.py"
Cohesion: 0.15
Nodes (18): build_control_task(), control_instructions(), control_plan_context(), ControlDecision, ControlError, _extract_decision(), BaseModel, Path (+10 more)

### Community 29 - "AttemptWorkspace"
Cohesion: 0.14
Nodes (10): AttemptWorkspace, Any, Path, Ensure an already-claimed workspace remains a real local directory., Atomically claim a new attempt directory; never reuse old contents., Write one harness-owned top-level file without following symlinks. The…, Match what is on disk against what the task promised. Returns (produced,…, Files the task wrote but never declared. Recorded with an empty ``name`` rather… (+2 more)

### Community 30 - "Browser"
Cohesion: 0.15
Nodes (9): Browser, Any, An open browser the agent can drive. Deliberately a thin wrapper: it exposes…, Attach to the shared browser, starting it only if nobody has. Attaching rather…, Detach. Deliberately does **not** close the browser. Closing it here is what…, Really end the shared browser, discarding its live tabs. The profile on disk…, CapabilityError, RuntimeError (+1 more)

### Community 31 - "test_handoff.py"
Cohesion: 0.06
Nodes (13): Sleipnir — a budget-aware agentic orchestrator. Phases 1–5 provide the schema,…, fixture, The credential handoff, and the three live bugs that produced it. Every test…, A full-screen redraw loop that does not switch buffers appends every frame to…, Drawing only one row of the horse emblem renders as debris., requests_dir(), test_the_banner_is_all_or_nothing(), test_the_console_uses_the_alternate_screen() (+5 more)

### Community 32 - "fetch_window_utilization"
Cohesion: 0.11
Nodes (23): allow_utilization_reads, fetch_window_utilization(), What the meter itself reports. Percentages, never tokens., Token limit consistent with ``used_tokens`` being this percentage., Read the CLI's OAuth access token, or None. Returns None for every failure…, Ask the meter. Returns None on any failure, never raises, never logs., read_oauth_token(), WindowUtilization (+15 more)

### Community 33 - "Secret"
Cohesion: 0.10
Nodes (13): Put a captured credential into a form field and wipe it. Separate from ``fill``…, Operator-authorised capabilities: the desk the robot sits at. Everything in…, capture(), BaseException, RuntimeError, TracebackType, Credentials that live for one keystroke burst and then stop existing. The rule…, A secret was used twice. Deliberately fatal rather than forgiving: re-use… (+5 more)

### Community 34 - "context.py"
Cohesion: 0.19
Nodes (17): ArtifactDirResolver, contained_regular_file(), The subagent's self-written summary, if it produced one., True only for a non-symlinked file physically beneath ``root``. Subagents…, _artifact_section(), _describe_check(), _file_section(), IncludedInput (+9 more)

### Community 35 - "TerminalInputDecoder"
Cohesion: 0.40
Nodes (3): PastedText, Turn a byte stream into keys and atomic bracketed-paste events., TerminalInputDecoder

### Community 36 - "computer.py"
Cohesion: 0.16
Nodes (24): Any, Path, Append-only record of every privileged action taken on the host. Same…, record(), redact(), click(), copy(), ensure_daemon() (+16 more)

### Community 38 - "Task"
Cohesion: 0.08
Nodes (26): Backend, What a tier requires and which backends it prefers, in order., TierPolicy, Governor, Budget control. Implemented by BudgetGovernor (Phase 4)., Phase 2 placeholder: a fixed tier -> (adapter, model) table from config. Phase…, StaticRouter, CatalogSnapshot (+18 more)

### Community 39 - "test_schema.py"
Cohesion: 0.07
Nodes (35): RetryPolicy, _manifest_for(), parametrize, Phase 1 schema tests. The load-bearing test is…, Re-tiering a task must NOT invalidate its completed work., The trap found in the real ~/.claude/projects record: input_tokens=2 while…, Manifest for a layered plan with every layer but the last two completed.…, This is the whole design in one assertion. A 600-task run must not cost the… (+27 more)

### Community 40 - "checks.py"
Cohesion: 0.22
Nodes (17): AcceptanceCheck, _check_command(), _check_files(), _check_json_schema(), _dispatch_check(), Any, Acceptance checks. Checks run *after* the adapter returns and decide whether…, A deliberate *subset* of JSON Schema: type, required, properties, items, enum,… (+9 more)

### Community 41 - "budget"
Cohesion: 0.22
Nodes (9): no_credential_reads(), no_real_utilization_reads(), fixture, Test-suite guardrails. The budget governor reads real window utilisation from…, Never call the usage endpoint from a test. Returns ``None``, which is the same…, Belt and braces: the token must not be read from disk either. A test that needs…, budget(), test_budget_headroom_is_none_when_limit_unknown() (+1 more)

### Community 42 - "OpenRouterAdapter"
Cohesion: 0.11
Nodes (17): AsyncClient, Response, _HttpFailure, materialize_file_blocks(), OpenRouterAdapter, Any, ClientFactory, Exception (+9 more)

### Community 43 - "screenshot"
Cohesion: 0.22
Nodes (9): CompletedProcess, Probe, Path, Capture the full screen to ``path``. The agent reads the resulting image…, Run a shell command as the operator, with the operator's environment. This is…, What this machine can actually do, for ``sleipnir doctor``., run(), screenshot() (+1 more)

### Community 44 - "TokenUsage"
Cohesion: 0.12
Nodes (11): CodexAdapter, CodexInvocation, _first_int(), Any, Path, Spawner, Walk every event for the last recognisable usage block. Deliberately structure-…, How to call the CLI. Data, not dispatch logic. (+3 more)

### Community 45 - "browser.py"
Cohesion: 0.21
Nodes (13): available(), _cdp_alive(), ensure_browser(), _pid_matches_browser(), _publish_pid(), Path, Real browser control, for the work that only exists behind a login.…, Start the shared browser if it is not already running, and return its endpoint.… (+5 more)

### Community 46 - "Sleipnir — Overview"
Cohesion: 0.11
Nodes (18): File structure & modularity, Files created while running (not in the repo), Host control, in one paragraph, How the budget governor decides, How the code works (the walkthrough), How the router chooses a model, How to add code / extend it, How to run / test locally (+10 more)

### Community 47 - "fakes.py"
Cohesion: 0.15
Nodes (6): StreamReader, FakeProcess, FakeStdin, Test doubles. The fake lives at the *spawn* boundary rather than replacing…, Implements the SpawnedProcess protocol., _reader()

### Community 48 - "Plan"
Cohesion: 0.20
Nodes (6): Plan, The task DAG. Validated as acyclic and referentially closed on load., All tasks transitively downstream of ``task_id``., make_layered(), _plan(), A wide layered DAG: every task in layer k depends on three in layer k-1. This…

### Community 49 - "InputContract"
Cohesion: 0.15
Nodes (13): ArtifactRef, InputContract, A request for another task's *full* output rather than its summary. Three…, Everything a task is permitted to read. Nothing else is provided to it., Planner-declared upper bound on input size. Feeds tier selection., Input contracts are enforced as filesystem security boundaries., test_dependency_artifact_symlink_cannot_escape_its_attempt(), test_repository_file_symlink_cannot_escape_the_run_root() (+5 more)

### Community 50 - "Sleipnir — project instructions"
Cohesion: 0.14
Nodes (13): Checkpoint discipline, Environment on this machine, Lessons from the first real console session, Money and resources, Rules that will bite you if ignored, Security, Sleipnir — project instructions, The budget governor (Phase 4) (+5 more)

### Community 51 - "UnsupportedCheckError"
Cohesion: 0.67
Nodes (3): RuntimeError, Raised at startup, not per task. A plan that cannot be fully checked must fail…, UnsupportedCheckError

### Community 54 - "process_guard.py"
Cohesion: 0.50
Nodes (4): _install_parent_death_signal(), main(), Run a provider CLI with a Linux parent-death signal installed. An executor can…, Install SIGTERM-on-parent-death, closing the setup race explicitly.

### Community 55 - "process.py"
Cohesion: 0.14
Nodes (13): Signals, _default_spawn(), ProcessResult, _pump(), Any, Path, Protocol, Async subprocess execution with timeout, streaming capture, and tree kill.… (+5 more)

### Community 57 - "Sleipnir — Project State"
Cohesion: 0.15
Nodes (12): Current phase/stage, Decisions log, Environment on this machine, Goal, Guarded fast lane and `/project` (2026-08-19), Next steps, Open questions, Phase 6 progress (2026-08-18) (+4 more)

### Community 58 - "handoff.py"
Cohesion: 0.18
Nodes (17): answer(), await_answer(), HandoffError, pending(), Path, RuntimeError, Asking the operator for a credential from a process that has no terminal. The…, Block until the console answers, and return its *status* only. Returns one of… (+9 more)

## Knowledge Gaps
- **67 isolated node(s):** `sleipnir`, `The one invariant`, `Rules that will bite you if ignored`, `The router (Phase 3)`, `Money and resources` (+62 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **3 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Tier` connect `Tier` to `make_task`, `cli.py`, `TaskStatus`, `executor.py`, `schema.py`, `Task`, `test_adapters.py`, `DispatchRequest`, `test_schema.py`, `BudgetGovernor`, `test_budget.py`, `budget.py`, `SleipnirConfig`, `Executor`, `chat.py`, `apply_revision`, `fold_results`, `orchestrator.py`?**
  _High betweenness centrality (0.077) - this node is a cross-community bridge._
- **Why does `make_task()` connect `make_task` to `schema.py`, `test_adapters.py`, `test_schema.py`, `checks.py`, `Tier`, `Task`, `test_budget.py`, `Plan`, `InputContract`, `apply_revision`, `fold_results`, `orchestrator.py`?**
  _High betweenness centrality (0.039) - this node is a cross-community bridge._
- **Why does `Plan` connect `Plan` to `make_task`, `cli.py`, `TaskStatus`, `executor.py`, `schema.py`, `test_adapters.py`, `test_schema.py`, `ConsoleState`, `BudgetGovernor`, `test_budget.py`, `ValueError`, `InputContract`, `console.py`, `budget.py`, `Executor`, `apply_revision`, `fold_results`, `orchestrator.py`?**
  _High betweenness centrality (0.039) - this node is a cross-community bridge._
- **Are the 5 inferred relationships involving `make_task()` (e.g. with `ExpectedOutput` and `InputContract`) actually correct?**
  _`make_task()` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 73 inferred relationships involving `Tier` (e.g. with `DispatchPreview` and `DispatchRequest`) actually correct?**
  _`Tier` has 73 INFERRED edges - model-reasoned connections that need verification._
- **Are the 25 inferred relationships involving `Task` (e.g. with `DispatchRequest` and `BudgetGovernor`) actually correct?**
  _`Task` has 25 INFERRED edges - model-reasoned connections that need verification._
- **Are the 50 inferred relationships involving `Adapter` (e.g. with `BaseAdapter` and `DispatchPreview`) actually correct?**
  _`Adapter` has 50 INFERRED edges - model-reasoned connections that need verification._