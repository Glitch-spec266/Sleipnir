# Graph Report - Sleipnir  (2026-08-19)

## Corpus Check
- 11 files · ~71,166 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1343 nodes · 4132 edges · 57 communities (55 shown, 2 thin omitted)
- Extraction: 83% EXTRACTED · 17% INFERRED · 0% AMBIGUOUS · INFERRED: 688 edges (avg confidence: 0.51)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Attempt Outcome & Failure Kinds
- Artifact Collection & Tier Choice
- Executor Config & Result Log
- Phase Gate & Escalation
- Live Price Catalogue
- Attempt Workspaces
- Plan Extraction & Adapters
- Subprocess Runner
- Acceptance Checks
- Budget Windows
- Package Root & Console Tests
- Budget Test Suite
- Tier Definitions & Router Tests
- Tier Policy & Catalogue Snapshot
- Budget Governor Core
- Adapter Base Contract
- OpenRouter Adapter & File Blocks
- Schema Validators
- Backend & Tier Config
- Bounded Manifest Projection
- CLI Parser & Capability Commands
- Plan Revisions
- Capability Test Suite
- Theme Easing & Palette
- Dispatch Outcome Contract
- Claude Adapter & Dispatch Request
- CLI Command Handlers
- Sparse Control Brain
- Console State & Input
- Schema Test Suite
- OAuth Window Meter
- Append-Only Result Log
- Artifact & Input Contracts
- Browser Automation
- One-Shot Secrets
- Console Chat Transport
- Status Folding
- Host Computer Control
- Privileged Action Audit
- Capability Package Surface
- Test Guardrails
- Manifest Size Bound
- Keyboard & Mouse Injection
- Plan Graph Traversal
- DAG Test Fixtures
- Window Utilisation Maths
- Dispatch Preview
- Duty Officer Routing
- HTTP Streaming Failures
- Retry & Escalation Ladder
- Codex Invocation
- Console Rendering
- Parent-Death Guard
- Workspace Security Tests
- Routing Refusal
- Usage Token Traps
- Package Root Node

## God Nodes (most connected - your core abstractions)
1. `make_task()` - 109 edges
2. `Tier` - 98 edges
3. `Task` - 67 edges
4. `Adapter` - 63 edges
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

## Communities (57 total, 2 thin omitted)

### Community 0 - "Attempt Outcome & Failure Kinds"
Cohesion: 0.07
Nodes (71): Combine what the provider said with what actually landed on disk. The…, AttemptStatus, FailureKind, StrEnum, Outcome of a single attempt. Deliberately small — *why* lives in FailureKind., Why an attempt did not fully succeed. Separated from AttemptStatus so retry…, StreamReader, fake_spawner() (+63 more)

### Community 1 - "Artifact Collection & Tier Choice"
Cohesion: 0.05
Nodes (52): ArtifactDirResolver, clip_summary(), Enforce the schema's hard summary cap at the write site. The schema *rejects*…, The tier to dispatch ``task`` at, plus why if it moved., _artifact_section(), _describe_check(), _file_section(), IncludedInput (+44 more)

### Community 2 - "Executor Config & Result Log"
Cohesion: 0.10
Nodes (74): ExecutorConfig, Append-only attempt log. The single source of truth for run state., Append one record and fsync it. fsync per record is the cost of the recovery…, Read every record, tolerating exactly one torn trailing line. A crash mid-…, Attempts with a start and no finish — in flight when the process died., Raised when a non-final line fails to parse — that is real corruption, not the…, ResultLog, TornRecordError (+66 more)

### Community 3 - "Phase Gate & Escalation"
Cohesion: 0.10
Nodes (53): escalation_changes(), evaluate_gate(), GateVerdict, GroupState, GroupVerdict, StrEnum, The phase gate: what the brain is allowed to know when it wakes up. The…, Every group passed. The phase may be merged and the next one begun. (+45 more)

### Community 4 - "Live Price Catalogue"
Cohesion: 0.08
Nodes (48): CatalogUnavailableError, _first_int(), _float(), ModelCatalog, parse_models(), _per_mtok(), Any, ClientFactory (+40 more)

### Community 5 - "Attempt Workspaces"
Cohesion: 0.06
Nodes (36): AttemptWorkspace, contained_regular_file(), Any, Path, RuntimeError, Ensure an already-claimed workspace remains a real local directory., Atomically claim a new attempt directory; never reuse old contents., The subagent's self-written summary, if it produced one. (+28 more)

### Community 6 - "Plan Extraction & Adapters"
Cohesion: 0.13
Nodes (44): extract_plan_json(), Pull a JSON object out of a model response. Tries the whole response first,…, Adapter, Dispatch backends. Auth is always delegated to the official tool., invoke(), PlanningAdapter, fixture, parametrize (+36 more)

### Community 7 - "Subprocess Runner"
Cohesion: 0.10
Nodes (32): Signals, skipif, _default_spawn(), ProcessResult, ProcessRunner, _pump(), Any, Path (+24 more)

### Community 8 - "Acceptance Checks"
Cohesion: 0.11
Nodes (34): AcceptanceCheck, assert_checks_supported(), _check_command(), _check_files(), _check_json_schema(), _dispatch_check(), Any, RuntimeError (+26 more)

### Community 9 - "Budget Windows"
Cohesion: 0.08
Nodes (33): current_window(), DownshiftDecision, _int(), _parse_bucket(), parse_usage_line(), Any, datetime, Path (+25 more)

### Community 10 - "Package Root & Console Tests"
Cohesion: 0.07
Nodes (12): Sleipnir — a budget-aware agentic orchestrator. Phases 1–5 provide the schema,…, The console owns the terminal, so its failure modes are visual. Two things are…, test_an_unbroken_token_longer_than_the_pane_is_hard_split(), test_every_rendered_line_is_exactly_the_terminal_width(), test_narrow_terminal_still_renders(), test_the_brain_is_asleep_exactly_when_a_run_owns_the_directory(), _widths(), The chrome must stay a pure function of the frame number, and must never be… (+4 more)

### Community 11 - "Budget Test Suite"
Cohesion: 0.15
Nodes (34): assistant_line(), config(), governor(), plan_of(), Path, Budget governor: usage parsing, window detection, projection, downshift. The…, Records recur across resumed sessions; 59% of the real corpus was duplicated.…, A trivial task on a subscription backend is not cheap: the spawn alone costs… (+26 more)

### Community 12 - "Tier Definitions & Router Tests"
Cohesion: 0.16
Nodes (33): Capability classes. A plan declares a tier; the router resolves a model. Fixed…, Tier, config(), model(), parametrize, Router: tier -> model, filters, preference order, and explainability., The operator knows their own plan better than a price table does., Missing catalogue metadata is uncertainty, not evidence of insufficiency. (+25 more)

### Community 13 - "Tier Policy & Catalogue Snapshot"
Cohesion: 0.13
Nodes (16): What a tier requires and which backends it prefers, in order., TierPolicy, CatalogSnapshot, ModelInfo, One comparable number for ranking. Tasks are input-heavy, so a plain average…, CandidateEval, _movement(), Tier -> concrete model resolution. Tasks declare a *tier*. This module turns… (+8 more)

### Community 14 - "Budget Governor Core"
Cohesion: 0.13
Nodes (12): BudgetGovernor, Projection, Estimates consumption and downshifts eligible tasks to stay inside it., The meter's own reading, cached briefly. None if unavailable. Disabled by…, Cost of everything still to run, at the tiers currently assigned., (window tokens, metered dollars) one attempt of ``task`` would cost. Fixed…, Assign a tier to every remaining task, downshifting until it fits. Downshifts…, The costliest task that can still move one rung down the ladder. (+4 more)

### Community 15 - "Adapter Base Contract"
Cohesion: 0.13
Nodes (17): ABC, AdapterError, BaseAdapter, RuntimeError, The adapter interface. An adapter's job is narrow on purpose: take a fully-…, One dispatch backend. Auth is never implemented here. The `claude` and `codex`…, Never let a credential reach a preview, a log, or an artifact., Environment for an agent CLI, stripped of unrelated credentials. The official… (+9 more)

### Community 16 - "OpenRouter Adapter & File Blocks"
Cohesion: 0.14
Nodes (12): AsyncClient, Response, materialize_file_blocks(), OpenRouterAdapter, Any, Path, Give a filesystem-less model a way to produce files. Without this the model…, Consume the SSE stream, writing every raw line to disk as it lands. Streaming… (+4 more)

### Community 17 - "Schema Validators"
Cohesion: 0.16
Nodes (7): field_validator, Self, model_validator, _find_cycle(), model_validator, Return one concrete cycle as a readable path, or None. Iterative (deep DAGs…, ValueError

### Community 18 - "Backend & Tier Config"
Cohesion: 0.19
Nodes (19): Backend, ConfigError, ModelOption, _opt_float(), _opt_int(), _parse_backends(), _parse_models(), _parse_tiers() (+11 more)

### Community 19 - "Bounded Manifest Projection"
Cohesion: 0.17
Nodes (24): _alerts(), build_manifest(), _clip(), _evidence(), _frontier(), _group_rollups(), datetime, Pure derivation of run state from plan + results. Deliberately I/O-free: no… (+16 more)

### Community 20 - "CLI Parser & Capability Commands"
Cohesion: 0.15
Nodes (23): ArgumentParser, Namespace, render_decisions(), build_parser(), cmd_browser(), cmd_computer(), cmd_console(), cmd_doctor() (+15 more)

### Community 21 - "Plan Revisions"
Cohesion: 0.21
Nodes (22): apply_revision(), persist_revision(), datetime, Path, RuntimeError, Validated, auditable plan revision application. The orchestrator may propose…, Append the audit first, then atomically replace the derived plan view., Latest revision that made each completed descendant stale. (+14 more)

### Community 22 - "Capability Test Suite"
Cohesion: 0.09
Nodes (7): audit_log(), _entries(), fake_ydotool(), fixture, Capability tests are hermetic by construction. Nothing here may inject a real…, Capture ydotool argv instead of running it., test_capture_records_only_the_label_and_length()

### Community 23 - "Theme Easing & Palette"
Cohesion: 0.13
Nodes (19): ease_back_out(), ease_power2_out(), fg(), _fit(), flicker_level(), frame(), paint(), Terminal chrome for Sleipnir: green frame, CRT flicker, and the splash. The TUI… (+11 more)

### Community 24 - "Dispatch Outcome Contract"
Cohesion: 0.13
Nodes (12): DispatchOutcome, Run the request to completion, a timeout, or a cancellation. Implementations…, What the adapter observed. Raw facts only, no derived accounting., CodexAdapter, _first_int(), Any, Path, Walk every event for the last recognisable usage block. Deliberately structure-… (+4 more)

### Community 25 - "Claude Adapter & Dispatch Request"
Cohesion: 0.17
Nodes (11): DispatchRequest, Everything an adapter needs. Fully resolved — adapters never route., ClaudeAdapter, Any, Path, Spawner, Map the CLI's own status vocabulary onto FailureKind., Sum `modelUsage` across every model the dispatch actually used. A dispatch can… (+3 more)

### Community 26 - "CLI Command Handlers"
Cohesion: 0.28
Nodes (21): build_adapters(), CliError, cmd_apply_revision(), cmd_explain(), cmd_orchestrate(), cmd_plan(), cmd_run(), cmd_status() (+13 more)

### Community 27 - "Sparse Control Brain"
Cohesion: 0.16
Nodes (18): build_control_task(), control_instructions(), control_plan_context(), ControlAction, ControlDecision, ControlError, _extract_decision(), BaseModel (+10 more)

### Community 28 - "Console State & Input"
Cohesion: 0.17
Nodes (18): apply_key(), capability_brief(), ConsoleState, _handle(), Message, _paint(), play_splash(), The Sleipnir console: the window you actually talk to. What this is,… (+10 more)

### Community 29 - "Schema Test Suite"
Cohesion: 0.12
Nodes (19): finished(), Phase 1 schema tests. The load-bearing test is…, Re-tiering a task must NOT invalidate its completed work., routing(), test_attempt_directories_never_collide(), test_cache_write_ttls_are_priced_separately(), test_downshift_must_be_explained(), test_failed_attempt_requires_a_failure_kind() (+11 more)

### Community 30 - "OAuth Window Meter"
Cohesion: 0.19
Nodes (16): allow_utilization_reads, fetch_window_utilization(), Read the CLI's OAuth access token, or None. Returns None for every failure…, Ask the meter. Returns None on any failure, never raises, never logs., read_oauth_token(), _creds(), Skip the round trip rather than send a token that will 401., The usage endpoint is itself rate-limited — observed returning 429. A governor… (+8 more)

### Community 31 - "Append-Only Result Log"
Cohesion: 0.14
Nodes (11): BaseException, Path, RuntimeError, TracebackType, Append-only reader/writer for ``results.jsonl``. Deliberately synchronous.…, Raised when another process already owns a run directory., Kernel-backed exclusive ownership of a run directory. The result log alone…, Whether another file description currently owns the run lock. (+3 more)

### Community 32 - "Artifact & Input Contracts"
Cohesion: 0.15
Nodes (13): ArtifactRef, InputContract, A request for another task's *full* output rather than its summary. Three…, Everything a task is permitted to read. Nothing else is provided to it., Planner-declared upper bound on input size. Feeds tier selection., Input contracts are enforced as filesystem security boundaries., test_dependency_artifact_symlink_cannot_escape_its_attempt(), test_repository_file_symlink_cannot_escape_the_run_root() (+5 more)

### Community 33 - "Browser Automation"
Cohesion: 0.18
Nodes (4): Browser, Any, Path, An open browser the agent can drive. Deliberately a thin wrapper: it exposes…

### Community 34 - "One-Shot Secrets"
Cohesion: 0.15
Nodes (6): Put a captured credential into a form field and wipe it. Separate from ``fill``…, BaseException, TracebackType, A one-shot credential. Every representation hook is overridden. Without that,…, Yield the plaintext exactly once, then wipe the buffer., Secret

### Community 35 - "Console Chat Transport"
Cohesion: 0.19
Nodes (14): ask_claude(), ask_router(), ChatError, claude_argv(), Path, RuntimeError, Where a typed message goes. Sleipnir is a harness, not a model. This module is…, Pick the duty-officer model from operator policy, never from source. (+6 more)

### Community 36 - "Status Folding"
Cohesion: 0.24
Nodes (14): fold_results(), _fold_task(), Recompute every task's status from the append-only result log. Records are…, AttemptStarted, Written *before* dispatch, flushed immediately. This record is what makes crash…, _bar(), _clip(), _latest_routes() (+6 more)

### Community 37 - "Host Computer Control"
Cohesion: 0.23
Nodes (10): CompletedProcess, Probe, Path, Keyboard, mouse, screen and shell control of the host machine. Wayland is the…, Capture the full screen to ``path``. The agent reads the resulting image…, Run a shell command as the operator, with the operator's environment. This is…, What this machine can actually do, for ``sleipnir doctor``., run() (+2 more)

### Community 38 - "Privileged Action Audit"
Cohesion: 0.23
Nodes (11): Any, Path, Append-only record of every privileged action taken on the host. Same…, record(), redact(), key(), Type into whatever window currently has focus. ``key_delay_ms`` is not…, Press a chord, e.g. ``key("ctrl", "shift", "t")``. Modifiers are held for the… (+3 more)

### Community 39 - "Capability Package Surface"
Cohesion: 0.18
Nodes (9): available(), Real browser control, for the work that only exists behind a login.…, Operator-authorised capabilities: the desk the robot sits at. Everything in…, capture(), RuntimeError, Credentials that live for one keystroke burst and then stop existing. The rule…, A secret was used twice. Deliberately fatal rather than forgiving: re-use…, Prompt the operator for a credential with echo disabled. Reads straight into a… (+1 more)

### Community 40 - "Test Guardrails"
Cohesion: 0.22
Nodes (9): no_credential_reads(), no_real_utilization_reads(), fixture, Test-suite guardrails. The budget governor reads real window utilisation from…, Never call the usage endpoint from a test. Returns ``None``, which is the same…, Belt and braces: the token must not be read from disk either. A test that needs…, budget(), test_budget_headroom_is_none_when_limit_unknown() (+1 more)

### Community 41 - "Manifest Size Bound"
Cohesion: 0.18
Nodes (11): _manifest_for(), Manifest for a layered plan with every layer but the last two completed.…, This is the whole design in one assertion. A 600-task run must not cost the…, The orchestrator must never infer completeness from silence., Paths may cross into the manifest. Bytes may not., test_manifest_caps_are_enforced_not_merely_documented(), test_manifest_carries_no_artifact_contents(), test_manifest_reports_when_it_elided_content() (+3 more)

### Community 42 - "Keyboard & Mouse Injection"
Cohesion: 0.24
Nodes (10): CapabilityError, click(), ensure_daemon(), move_mouse(), RuntimeError, Start ``ydotoold`` if it is not already listening. Started detached and left…, Positive scrolls up, negative down., A host capability was asked for and is genuinely unavailable. Raised rather… (+2 more)

### Community 43 - "Plan Graph Traversal"
Cohesion: 0.20
Nodes (5): _propagate_dependencies(), Mark tasks blocked by unsatisfied deps, in topological order., Plan, The task DAG. Validated as acyclic and referentially closed on load., All tasks transitively downstream of ``task_id``.

### Community 44 - "DAG Test Fixtures"
Cohesion: 0.20
Nodes (10): make_chain(), make_layered(), _plan(), t0000 -> t0001 -> ... Simple shape for status-folding tests., A wide layered DAG: every task in layer k depends on three in layer k-1. This…, Replaying the log must not double-count cost — recovery depends on it., test_completed_task_is_superseded_when_spec_changes(), test_descendants_are_transitive() (+2 more)

### Community 45 - "Window Utilisation Maths"
Cohesion: 0.25
Nodes (7): What the meter itself reports. Percentages, never tokens., Token limit consistent with ``used_tokens`` being this percentage., WindowUtilization, The reading is a percentage; everything downstream works in tokens. Solving…, Near zero the division explodes and would imply a wildly wrong limit., test_implied_limit_refuses_when_utilisation_is_too_small_to_divide_by(), test_implied_limit_solves_for_the_limit_matching_local_accounting()

### Community 46 - "Dispatch Preview"
Cohesion: 0.29
Nodes (3): DispatchPreview, Describe the dispatch without performing it. No network, no spawn., What a dry run prints. Must be producible without spending anything.

### Community 47 - "Duty Officer Routing"
Cohesion: 0.29
Nodes (7): extract_queued_instruction(), Pull the ``QUEUE:`` line out of a duty-officer reply, if there is one. Parsed…, _ask_duty_officer(), Path, A constant-size picture of the run, for the duty officer. This is the whole…, Answer from bounded run state without spending a reason-tier spawn., run_digest()

### Community 48 - "HTTP Streaming Failures"
Cohesion: 0.33
Nodes (4): _HttpFailure, ClientFactory, Exception, An HTTP error status, carried out of the streaming path. Streaming used to…

### Community 49 - "Retry & Escalation Ladder"
Cohesion: 0.33
Nodes (5): Tier to use on ``attempt`` (1-indexed). Falls back to ``base_tier``., RetryPolicy, test_escalation_ladder_cannot_exceed_retries(), test_retry_policy_rejects_non_retryable_kinds(), test_tier_for_attempt_walks_the_ladder()

### Community 50 - "Codex Invocation"
Cohesion: 0.40
Nodes (3): CodexInvocation, Spawner, How to call the CLI. Data, not dispatch logic.

### Community 51 - "Console Rendering"
Cohesion: 0.40
Nodes (5): _clip(), Model and provider text is untrusted; strip anything non-printable. Same trust…, render(), _wrap(), logo_lines()

### Community 52 - "Parent-Death Guard"
Cohesion: 0.50
Nodes (4): _install_parent_death_signal(), main(), Run a provider CLI with a Linux parent-death signal installed. An executor can…, Install SIGTERM-on-parent-death, closing the setup race explicitly.

### Community 53 - "Workspace Security Tests"
Cohesion: 0.50
Nodes (4): parametrize, test_manifest_never_exceeds_the_ceiling(), test_outputs_cannot_overwrite_harness_owned_files(), test_repository_input_paths_cannot_escape_the_run_root()

### Community 54 - "Routing Refusal"
Cohesion: 0.67
Nodes (3): RuntimeError, No model satisfies the tier. Raised before dispatch, never mid-run., RoutingError

## Knowledge Gaps
- **1 isolated node(s):** `sleipnir`
  These have ≤1 connection - possible missing edges or undocumented components.
- **2 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Tier` connect `Tier Definitions & Router Tests` to `Attempt Outcome & Failure Kinds`, `Artifact Collection & Tier Choice`, `Executor Config & Result Log`, `Phase Gate & Escalation`, `Attempt Workspaces`, `Acceptance Checks`, `Budget Windows`, `Budget Test Suite`, `Tier Policy & Catalogue Snapshot`, `Budget Governor Core`, `Adapter Base Contract`, `Backend & Tier Config`, `CLI Parser & Capability Commands`, `Plan Revisions`, `Claude Adapter & Dispatch Request`, `CLI Command Handlers`, `Sparse Control Brain`, `Schema Test Suite`, `Console Chat Transport`, `Dispatch Preview`, `Retry & Escalation Ladder`?**
  _High betweenness centrality (0.075) - this node is a cross-community bridge._
- **Why does `Plan` connect `Plan Graph Traversal` to `Artifact Collection & Tier Choice`, `Executor Config & Result Log`, `Phase Gate & Escalation`, `Attempt Workspaces`, `Acceptance Checks`, `Budget Windows`, `Budget Test Suite`, `Budget Governor Core`, `Schema Validators`, `Bounded Manifest Projection`, `CLI Parser & Capability Commands`, `Plan Revisions`, `CLI Command Handlers`, `Sparse Control Brain`, `Console State & Input`, `Schema Test Suite`, `Artifact & Input Contracts`, `Status Folding`, `DAG Test Fixtures`, `Duty Officer Routing`?**
  _High betweenness centrality (0.067) - this node is a cross-community bridge._
- **Why does `Task` connect `Artifact Collection & Tier Choice` to `Executor Config & Result Log`, `Phase Gate & Escalation`, `Attempt Workspaces`, `Subprocess Runner`, `Acceptance Checks`, `Budget Windows`, `Tier Policy & Catalogue Snapshot`, `Budget Governor Core`, `Adapter Base Contract`, `Schema Validators`, `Bounded Manifest Projection`, `CLI Parser & Capability Commands`, `Claude Adapter & Dispatch Request`, `CLI Command Handlers`, `Sparse Control Brain`, `Schema Test Suite`, `Status Folding`, `Plan Graph Traversal`, `DAG Test Fixtures`?**
  _High betweenness centrality (0.061) - this node is a cross-community bridge._
- **Are the 5 inferred relationships involving `make_task()` (e.g. with `ExpectedOutput` and `InputContract`) actually correct?**
  _`make_task()` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 70 inferred relationships involving `Tier` (e.g. with `DispatchPreview` and `DispatchRequest`) actually correct?**
  _`Tier` has 70 INFERRED edges - model-reasoned connections that need verification._
- **Are the 25 inferred relationships involving `Task` (e.g. with `DispatchRequest` and `BudgetGovernor`) actually correct?**
  _`Task` has 25 INFERRED edges - model-reasoned connections that need verification._
- **Are the 48 inferred relationships involving `Adapter` (e.g. with `BaseAdapter` and `DispatchPreview`) actually correct?**
  _`Adapter` has 48 INFERRED edges - model-reasoned connections that need verification._