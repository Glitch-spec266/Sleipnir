# Graph Report - Sleipnir  (2026-08-19)

## Corpus Check
- 13 files · ~74,327 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1387 nodes · 4205 edges · 61 communities (55 shown, 6 thin omitted)
- Extraction: 84% EXTRACTED · 16% INFERRED · 0% AMBIGUOUS · INFERRED: 689 edges (avg confidence: 0.51)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Executor Config & Status Folding
- CLI Parser & Budget Governor
- Phase Gate & Escalation
- Subprocess Runner
- Live Price Catalogue
- Adapter Base Contract
- Adapter Test Suite
- Plan Extraction & Adapters
- Budget Windows
- Tier Definitions & Router Tests
- HTTP Dispatch & Outcomes
- Attempt Workspaces
- Tier Policy & Catalogue Snapshot
- Acceptance Checks
- Budget Test Suite
- Schema Validators
- Backend & Tier Config
- Theme & Console Rendering
- Console State & Input
- Bounded Manifest Projection
- Summary Reading & Path Safety
- Executor Dispatch Loop
- Capability Test Suite
- Console Chat Transport
- Console Test Suite
- Subtask Prompt Assembly
- Claude Adapter
- Summary Capping & Executor Core
- Sparse Control Brain
- Schema Test Suite
- Browser Automation
- Credential Handoff Tests
- OAuth Window Meter
- One-Shot Secrets
- Attempt Outcome Resolution
- Governor & Router Protocols
- Keyboard & Mouse Injection
- Credential Handoff
- Plan Graph Traversal
- Status Folding Fixtures
- Theme Test Suite
- Test Guardrails
- Manifest Size Bound
- Screen Capture & Probe
- Privileged Action Audit
- Browser Daemon & CDP
- Capability Package Surface
- Window Utilisation Maths
- Check Support Refusal
- Artifact References
- File Block Materialisation
- Budget Snapshot
- Price Snapshot & Cost
- Retry & Escalation Ladder
- Parent-Death Guard
- Spec Hashing
- Artifact Directory Resolution
- Untrusted Text Clipping
- Package Root
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

## Communities (61 total, 6 thin omitted)

### Community 0 - "Executor Config & Status Folding"
Cohesion: 0.06
Nodes (109): ExecutorConfig, fold_results(), _fold_task(), Recompute every task's status from the append-only result log. Records are…, apply_revision(), persist_revision(), datetime, Path (+101 more)

### Community 1 - "CLI Parser & Budget Governor"
Cohesion: 0.06
Nodes (70): ArgumentParser, Namespace, BudgetGovernor, DownshiftDecision, Projection, Estimates consumption and downshifts eligible tasks to stay inside it., The meter's own reading, cached briefly. None if unavailable. Disabled by…, Cost of everything still to run, at the tiers currently assigned. (+62 more)

### Community 2 - "Phase Gate & Escalation"
Cohesion: 0.10
Nodes (57): escalation_changes(), evaluate_gate(), GateVerdict, GroupState, GroupVerdict, StrEnum, The phase gate: what the brain is allowed to know when it wakes up. The…, Every group passed. The phase may be merged and the next one begun. (+49 more)

### Community 3 - "Subprocess Runner"
Cohesion: 0.06
Nodes (41): Signals, skipif, _default_spawn(), ProcessResult, ProcessRunner, _pump(), Any, Path (+33 more)

### Community 4 - "Live Price Catalogue"
Cohesion: 0.08
Nodes (48): CatalogUnavailableError, _first_int(), _float(), ModelCatalog, parse_models(), _per_mtok(), Any, ClientFactory (+40 more)

### Community 5 - "Adapter Base Contract"
Cohesion: 0.07
Nodes (33): ABC, AdapterError, BaseAdapter, DispatchPreview, DispatchRequest, RuntimeError, The adapter interface. An adapter's job is narrow on purpose: take a fully-…, One dispatch backend. Auth is never implemented here. The `claude` and `codex`… (+25 more)

### Community 6 - "Adapter Test Suite"
Cohesion: 0.14
Nodes (49): claude_adapter(), openrouter(), Path, Adapter tests. Every adapter is driven end to end against a fake. The Claude…, The whole point: `usage.input_tokens` is 10, `modelUsage` is 907., Prompts carry file contents; argv has a length limit and is world-readable., Regression: seeding on (task, attempt) alone made every resume collide with…, Two executors started in the same second must not share a run_id. (+41 more)

### Community 7 - "Plan Extraction & Adapters"
Cohesion: 0.13
Nodes (44): extract_plan_json(), Pull a JSON object out of a model response. Tries the whole response first,…, Adapter, Dispatch backends. Auth is always delegated to the official tool., invoke(), PlanningAdapter, fixture, parametrize (+36 more)

### Community 8 - "Budget Windows"
Cohesion: 0.07
Nodes (39): current_window(), _int(), _parse_bucket(), parse_usage_line(), Any, datetime, Path, Budget governor: what the 5-hour window has cost, and what the plan will. Two… (+31 more)

### Community 9 - "Tier Definitions & Router Tests"
Cohesion: 0.16
Nodes (33): Capability classes. A plan declares a tier; the router resolves a model. Fixed…, Tier, config(), model(), parametrize, Router: tier -> model, filters, preference order, and explainability., The operator knows their own plan better than a price table does., Missing catalogue metadata is uncertainty, not evidence of insufficiency. (+25 more)

### Community 10 - "HTTP Dispatch & Outcomes"
Cohesion: 0.12
Nodes (15): AsyncClient, Response, DispatchOutcome, What the adapter observed. Raw facts only, no derived accounting., _HttpFailure, OpenRouterAdapter, Any, ClientFactory (+7 more)

### Community 11 - "Attempt Workspaces"
Cohesion: 0.11
Nodes (16): AttemptWorkspace, Any, Path, RuntimeError, Attempt workspace layout and output collection. One directory per attempt,…, Ensure an already-claimed workspace remains a real local directory., Atomically claim a new attempt directory; never reuse old contents., Match what is on disk against what the task promised. Returns (produced,… (+8 more)

### Community 12 - "Tier Policy & Catalogue Snapshot"
Cohesion: 0.13
Nodes (16): What a tier requires and which backends it prefers, in order., TierPolicy, CatalogSnapshot, ModelInfo, One comparable number for ranking. Tasks are input-heavy, so a plain average…, CandidateEval, _movement(), Tier -> concrete model resolution. Tasks declare a *tier*. This module turns… (+8 more)

### Community 13 - "Acceptance Checks"
Cohesion: 0.15
Nodes (27): AcceptanceCheck, _check_command(), _check_files(), _check_json_schema(), _dispatch_check(), Any, Acceptance checks. Checks run *after* the adapter returns and decide whether…, A deliberate *subset* of JSON Schema: type, required, properties, items, enum,… (+19 more)

### Community 14 - "Budget Test Suite"
Cohesion: 0.20
Nodes (27): config(), governor(), plan_of(), Path, Budget governor: usage parsing, window detection, projection, downshift. The…, Records recur across resumed sessions; 59% of the real corpus was duplicated.…, A trivial task on a subscription backend is not cheap: the spawn alone costs…, The governor must never stop or reroute a run on a number it could not verify. (+19 more)

### Community 15 - "Schema Validators"
Cohesion: 0.16
Nodes (7): field_validator, Self, model_validator, _find_cycle(), model_validator, Return one concrete cycle as a readable path, or None. Iterative (deep DAGs…, ValueError

### Community 16 - "Backend & Tier Config"
Cohesion: 0.19
Nodes (19): Backend, ConfigError, ModelOption, _opt_float(), _opt_int(), _parse_backends(), _parse_models(), _parse_tiers() (+11 more)

### Community 17 - "Theme & Console Rendering"
Cohesion: 0.12
Nodes (22): render(), _wrap(), ease_back_out(), ease_power2_out(), fg(), _fit(), flicker_level(), frame() (+14 more)

### Community 18 - "Console State & Input"
Cohesion: 0.14
Nodes (22): apply_key(), capability_brief(), ConsoleState, _handle(), Message, _paint(), play_splash(), poll_secret_request() (+14 more)

### Community 19 - "Bounded Manifest Projection"
Cohesion: 0.17
Nodes (23): _alerts(), build_manifest(), _clip(), _evidence(), _frontier(), _group_rollups(), datetime, Pure derivation of run state from plan + results. Deliberately I/O-free: no… (+15 more)

### Community 20 - "Summary Reading & Path Safety"
Cohesion: 0.13
Nodes (20): contained_regular_file(), The subagent's self-written summary, if it produced one., True only for a non-symlinked file physically beneath ``root``. Subagents…, assemble_plan(), build_planner_task(), generate_plan(), planning_instructions(), PlanningError (+12 more)

### Community 21 - "Executor Dispatch Loop"
Cohesion: 0.17
Nodes (10): ConcurrentExecutionError, Executor, RuntimeError, Everything the run would dispatch, spending nothing. Walks the DAG in…, Execute while holding exclusive ownership of the run directory., Close attempts whose executor died before writing a terminal record. The start…, Cancel in-flight attempts and wait for each to record its own end. Each attempt…, Which tier this attempt runs at, and why if it moved. Retry escalation outranks… (+2 more)

### Community 22 - "Capability Test Suite"
Cohesion: 0.09
Nodes (7): audit_log(), _entries(), fake_ydotool(), fixture, Capability tests are hermetic by construction. Nothing here may inject a real…, Capture ydotool argv instead of running it., test_capture_records_only_the_label_and_length()

### Community 23 - "Console Chat Transport"
Cohesion: 0.13
Nodes (21): ask_claude(), ask_router(), ChatError, claude_argv(), extract_queued_instruction(), Path, RuntimeError, Where a typed message goes. Sleipnir is a harness, not a model. This module is… (+13 more)

### Community 24 - "Console Test Suite"
Cohesion: 0.10
Nodes (6): The console owns the terminal, so its failure modes are visual. Two things are…, test_an_unbroken_token_longer_than_the_pane_is_hard_split(), test_every_rendered_line_is_exactly_the_terminal_width(), test_narrow_terminal_still_renders(), test_the_brain_is_asleep_exactly_when_a_run_owns_the_directory(), _widths()

### Community 25 - "Subtask Prompt Assembly"
Cohesion: 0.19
Nodes (17): ArtifactDirResolver, _artifact_section(), _describe_check(), _file_section(), IncludedInput, _output_section(), Path, Resolve a task's InputContract into the exact prompt a subagent receives. This… (+9 more)

### Community 26 - "Claude Adapter"
Cohesion: 0.16
Nodes (10): ClaudeAdapter, Any, Path, Spawner, Map the CLI's own status vocabulary onto FailureKind., Sum `modelUsage` across every model the dispatch actually used. A dispatch can…, The model that produced the most output — the one that did the work if a…, Flags verified against `claude --help` (CLI 2.1.234). The prompt goes over… (+2 more)

### Community 27 - "Summary Capping & Executor Core"
Cohesion: 0.15
Nodes (15): clip_summary(), Enforce the schema's hard summary cap at the write site. The schema *rejects*…, cost_from_outcome(), _pid_is_alive(), datetime, Concurrency-capped DAG execution. The executor owns everything the adapters…, Compose the shared dollar/quota axes for worker and control calls., Probe process existence without sending a signal that changes state. (+7 more)

### Community 28 - "Sparse Control Brain"
Cohesion: 0.18
Nodes (16): build_control_task(), control_instructions(), control_plan_context(), ControlDecision, ControlError, _extract_decision(), BaseModel, Path (+8 more)

### Community 29 - "Schema Test Suite"
Cohesion: 0.12
Nodes (17): parametrize, Phase 1 schema tests. The load-bearing test is…, Re-tiering a task must NOT invalidate its completed work., test_attempt_directories_never_collide(), test_downshift_must_be_explained(), test_manifest_never_exceeds_the_ceiling(), test_metered_calls_do_not_consume_the_window(), test_outputs_cannot_overwrite_harness_owned_files() (+9 more)

### Community 30 - "Browser Automation"
Cohesion: 0.16
Nodes (6): Browser, Any, An open browser the agent can drive. Deliberately a thin wrapper: it exposes…, Attach to the shared browser, starting it only if nobody has. Attaching rather…, Detach. Deliberately does **not** close the browser. Closing it here is what…, Really end the shared browser, discarding its live tabs. The profile on disk…

### Community 31 - "Credential Handoff Tests"
Cohesion: 0.12
Nodes (7): fixture, The credential handoff, and the three live bugs that produced it. Every test…, A full-screen redraw loop that does not switch buffers appends every frame to…, Drawing the top row of a five-row wordmark renders as debris., requests_dir(), test_the_banner_is_all_or_nothing(), test_the_console_uses_the_alternate_screen()

### Community 32 - "OAuth Window Meter"
Cohesion: 0.19
Nodes (16): allow_utilization_reads, fetch_window_utilization(), Read the CLI's OAuth access token, or None. Returns None for every failure…, Ask the meter. Returns None on any failure, never raises, never logs., read_oauth_token(), _creds(), Skip the round trip rather than send a token that will 401., The usage endpoint is itself rate-limited — observed returning 429. A governor… (+8 more)

### Community 33 - "One-Shot Secrets"
Cohesion: 0.15
Nodes (6): Put a captured credential into a form field and wipe it. Separate from ``fill``…, BaseException, TracebackType, A one-shot credential. Every representation hook is overridden. Without that,…, Yield the plaintext exactly once, then wipe the buffer., Secret

### Community 34 - "Attempt Outcome Resolution"
Cohesion: 0.21
Nodes (11): Combine what the provider said with what actually landed on disk. The…, AttemptStatus, FailureKind, StrEnum, Outcome of a single attempt. Deliberately small — *why* lives in FailureKind., Why an attempt did not fully succeed. Separated from AttemptStatus so retry…, Exception, test_failed_dependency_skips_dependents() (+3 more)

### Community 35 - "Governor & Router Protocols"
Cohesion: 0.19
Nodes (8): The tier to dispatch ``task`` at, plus why if it moved., Governor, Protocol, Budget control. Implemented by BudgetGovernor (Phase 4)., Tier -> concrete model. Implemented by TierRouter. ``downshift_reason`` is how…, Router, Attempts never share a directory, so a re-run can never clobber evidence from a…, Task

### Community 36 - "Keyboard & Mouse Injection"
Cohesion: 0.24
Nodes (13): CapabilityError, click(), ensure_daemon(), key(), move_mouse(), RuntimeError, Keyboard, mouse, screen and shell control of the host machine. Wayland is the…, Start ``ydotoold`` if it is not already listening. Started detached and left… (+5 more)

### Community 37 - "Credential Handoff"
Cohesion: 0.21
Nodes (12): answer(), await_answer(), pending(), Path, Asking the operator for a credential from a process that has no terminal. The…, Tell the waiting process what happened. Status only — never the value., A pending ask. Carries a label; never a value., File a request for the console to fulfil. (+4 more)

### Community 38 - "Plan Graph Traversal"
Cohesion: 0.17
Nodes (8): Plan, The task DAG. Validated as acyclic and referentially closed on load., All tasks transitively downstream of ``task_id``., What the duty officer sees. If this ever grew with the plan, the cheap stand-in…, test_the_run_digest_is_constant_size_and_carries_no_task_output(), make_layered(), _plan(), A wide layered DAG: every task in layer k depends on three in layer k-1. This…

### Community 39 - "Status Folding Fixtures"
Cohesion: 0.18
Nodes (12): finished(), make_chain(), t0000 -> t0001 -> ... Simple shape for status-folding tests., Replaying the log must not double-count cost — recovery depends on it., routing(), test_completed_task_is_superseded_when_spec_changes(), test_descendants_are_transitive(), test_failed_attempt_requires_a_failure_kind() (+4 more)

### Community 40 - "Theme Test Suite"
Cohesion: 0.21
Nodes (5): The chrome must stay a pure function of the frame number, and must never be…, test_frame_lines_never_exceed_requested_width(), test_splash_ends_fully_revealed(), test_splash_renders_every_frame_at_a_narrow_terminal(), _visible()

### Community 41 - "Test Guardrails"
Cohesion: 0.22
Nodes (9): no_credential_reads(), no_real_utilization_reads(), fixture, Test-suite guardrails. The budget governor reads real window utilisation from…, Never call the usage endpoint from a test. Returns ``None``, which is the same…, Belt and braces: the token must not be read from disk either. A test that needs…, budget(), test_budget_headroom_is_none_when_limit_unknown() (+1 more)

### Community 42 - "Manifest Size Bound"
Cohesion: 0.18
Nodes (11): _manifest_for(), Manifest for a layered plan with every layer but the last two completed.…, This is the whole design in one assertion. A 600-task run must not cost the…, The orchestrator must never infer completeness from silence., Paths may cross into the manifest. Bytes may not., test_manifest_caps_are_enforced_not_merely_documented(), test_manifest_carries_no_artifact_contents(), test_manifest_reports_when_it_elided_content() (+3 more)

### Community 43 - "Screen Capture & Probe"
Cohesion: 0.22
Nodes (9): CompletedProcess, Probe, Path, Capture the full screen to ``path``. The agent reads the resulting image…, Run a shell command as the operator, with the operator's environment. This is…, What this machine can actually do, for ``sleipnir doctor``., run(), screenshot() (+1 more)

### Community 44 - "Privileged Action Audit"
Cohesion: 0.27
Nodes (9): Any, Path, Append-only record of every privileged action taken on the host. Same…, record(), redact(), Type into whatever window currently has focus. ``key_delay_ms`` is not…, type_text(), Type a captured credential into whatever window has focus, then wipe. This is… (+1 more)

### Community 45 - "Browser Daemon & CDP"
Cohesion: 0.24
Nodes (8): available(), _cdp_alive(), ensure_browser(), Path, Real browser control, for the work that only exists behind a login.…, Terminate the detached browser, if one is running. True if it stopped., Start the shared browser if it is not already running, and return its endpoint.…, stop_browser()

### Community 46 - "Capability Package Surface"
Cohesion: 0.22
Nodes (7): Operator-authorised capabilities: the desk the robot sits at. Everything in…, capture(), RuntimeError, Credentials that live for one keystroke burst and then stop existing. The rule…, A secret was used twice. Deliberately fatal rather than forgiving: re-use…, Prompt the operator for a credential with echo disabled. Reads straight into a…, SecretConsumed

### Community 47 - "Window Utilisation Maths"
Cohesion: 0.25
Nodes (7): What the meter itself reports. Percentages, never tokens., Token limit consistent with ``used_tokens`` being this percentage., WindowUtilization, The reading is a percentage; everything downstream works in tokens. Solving…, Near zero the division explodes and would imply a wildly wrong limit., test_implied_limit_refuses_when_utilisation_is_too_small_to_divide_by(), test_implied_limit_solves_for_the_limit_matching_local_accounting()

### Community 48 - "Check Support Refusal"
Cohesion: 0.29
Nodes (5): assert_checks_supported(), RuntimeError, Raised at startup, not per task. A plan that cannot be fully checked must fail…, UnsupportedCheckError, RunReport

### Community 49 - "Artifact References"
Cohesion: 0.29
Nodes (6): ArtifactRef, A request for another task's *full* output rather than its summary. Three…, test_artifact_budget_must_fit_max_input_bytes(), test_artifact_ref_must_name_a_real_output(), test_artifact_ref_rejects_path_escape(), test_artifact_ref_rejects_wildcard_everything()

### Community 50 - "File Block Materialisation"
Cohesion: 0.33
Nodes (6): materialize_file_blocks(), Path, Write ```file:<path> blocks into ``target_dir``. Paths are confined to the…, parametrize, test_file_blocks_cannot_escape_the_attempt_directory(), test_file_blocks_write_nested_paths()

### Community 52 - "Price Snapshot & Cost"
Cohesion: 0.33
Nodes (5): PriceSnapshot, Per-million-token prices as fetched at dispatch time. Never populated from…, Cost of ``usage`` under this snapshot. Missing cache prices fall back to the…, test_cache_write_ttls_are_priced_separately(), test_missing_cache_prices_fall_back_without_undercounting()

### Community 53 - "Retry & Escalation Ladder"
Cohesion: 0.33
Nodes (5): Tier to use on ``attempt`` (1-indexed). Falls back to ``base_tier``., RetryPolicy, test_escalation_ladder_cannot_exceed_retries(), test_retry_policy_rejects_non_retryable_kinds(), test_tier_for_attempt_walks_the_ladder()

### Community 54 - "Parent-Death Guard"
Cohesion: 0.50
Nodes (4): _install_parent_death_signal(), main(), Run a provider CLI with a Linux parent-death signal installed. An executor can…, Install SIGTERM-on-parent-death, closing the setup race explicitly.

### Community 55 - "Spec Hashing"
Cohesion: 0.40
Nodes (4): _canonical_json(), Any, Stable digest of the task's *meaning*. Completed results are keyed by (task_id,…, Stable JSON encoding for hashing: sorted keys, no incidental whitespace.

## Knowledge Gaps
- **1 isolated node(s):** `sleipnir`
  These have ≤1 connection - possible missing edges or undocumented components.
- **6 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Task` connect `Governor & Router Protocols` to `Executor Config & Status Folding`, `CLI Parser & Budget Governor`, `Phase Gate & Escalation`, `Subprocess Runner`, `Adapter Base Contract`, `Budget Windows`, `Tier Policy & Catalogue Snapshot`, `Acceptance Checks`, `Schema Validators`, `Bounded Manifest Projection`, `Summary Reading & Path Safety`, `Executor Dispatch Loop`, `Subtask Prompt Assembly`, `Summary Capping & Executor Core`, `Sparse Control Brain`, `Schema Test Suite`, `Plan Graph Traversal`, `Check Support Refusal`, `Spec Hashing`?**
  _High betweenness centrality (0.093) - this node is a cross-community bridge._
- **Why does `Tier` connect `Tier Definitions & Router Tests` to `Executor Config & Status Folding`, `CLI Parser & Budget Governor`, `Phase Gate & Escalation`, `Adapter Base Contract`, `Adapter Test Suite`, `Budget Windows`, `Tier Policy & Catalogue Snapshot`, `Acceptance Checks`, `Budget Test Suite`, `Backend & Tier Config`, `Summary Reading & Path Safety`, `Executor Dispatch Loop`, `Console Chat Transport`, `Summary Capping & Executor Core`, `Sparse Control Brain`, `Schema Test Suite`, `Attempt Outcome Resolution`, `Governor & Router Protocols`, `Plan Graph Traversal`, `Status Folding Fixtures`, `Retry & Escalation Ladder`?**
  _High betweenness centrality (0.066) - this node is a cross-community bridge._
- **Why does `make_task()` connect `Executor Config & Status Folding` to `Governor & Router Protocols`, `Adapter Test Suite`, `Status Folding Fixtures`, `Plan Graph Traversal`, `Tier Definitions & Router Tests`, `Attempt Workspaces`, `Acceptance Checks`, `Budget Test Suite`, `Artifact References`, `Summary Reading & Path Safety`, `Subtask Prompt Assembly`, `Schema Test Suite`?**
  _High betweenness centrality (0.061) - this node is a cross-community bridge._
- **Are the 5 inferred relationships involving `make_task()` (e.g. with `ExpectedOutput` and `InputContract`) actually correct?**
  _`make_task()` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 70 inferred relationships involving `Tier` (e.g. with `DispatchPreview` and `DispatchRequest`) actually correct?**
  _`Tier` has 70 INFERRED edges - model-reasoned connections that need verification._
- **Are the 25 inferred relationships involving `Task` (e.g. with `DispatchRequest` and `BudgetGovernor`) actually correct?**
  _`Task` has 25 INFERRED edges - model-reasoned connections that need verification._
- **Are the 48 inferred relationships involving `Adapter` (e.g. with `BaseAdapter` and `DispatchPreview`) actually correct?**
  _`Adapter` has 48 INFERRED edges - model-reasoned connections that need verification._