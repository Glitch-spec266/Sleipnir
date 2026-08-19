# Graph Report - Sleipnir  (2026-08-19)

## Corpus Check
- 60 files · ~77,661 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1530 nodes · 4383 edges · 61 communities (56 shown, 5 thin omitted)
- Extraction: 84% EXTRACTED · 16% INFERRED · 0% AMBIGUOUS · INFERRED: 690 edges (avg confidence: 0.51)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `7500ce69`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- make_task
- cli.py
- Plan
- apply_revision
- test_pricing.py
- base.py
- test_adapters.py
- Adapter
- .run
- Tier
- OpenRouterAdapter
- AttemptWorkspace
- Sleipnir — Phase 1 design
- schema.py
- Path
- ValueError
- FakeProcess
- theme.py
- console.py
- budget.py
- test_the_run_digest_is_constant_size_and_carries_no_task_output
- Task
- test_capabilities.py
- chat.py
- test_console.py
- clipboard.py
- DispatchRequest
- AttemptStatus
- orchestrator.py
- WorkspaceCollisionError
- Browser
- test_handoff.py
- test_budget.py
- Secret
- current_window
- TerminalInputDecoder
- computer.py
- handoff.py
- test_file_blocks_cannot_escape_the_attempt_directory
- test_schema.py
- test_theme.py
- budget
- screenshot
- secrets.py
- browser.py
- Sleipnir — Overview
- WindowUtilization
- fold_results
- InputContract
- Sleipnir — project instructions
- PriceSnapshot
- RetryPolicy
- process_guard.py
- ProcessRunner
- parse_usage_line
- Sleipnir — Project State
- sleipnir
- run_is_active
- _widths
- run_digest
- test_decline_or_malformed_check_routes_to_strong_model

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

## Communities (61 total, 5 thin omitted)

### Community 0 - "make_task"
Cohesion: 0.09
Nodes (82): ExecutorConfig, Append-only reader/writer for ``results.jsonl``. Deliberately synchronous.…, Append-only attempt log. The single source of truth for run state., Append one record and fsync it. fsync per record is the cost of the recovery…, Read every record, tolerating exactly one torn trailing line. A crash mid-…, Attempts with a start and no finish — in flight when the process died., Raised when a non-final line fails to parse — that is real corruption, not the…, ResultLog (+74 more)

### Community 1 - "cli.py"
Cohesion: 0.06
Nodes (67): ArgumentParser, Namespace, BudgetGovernor, DownshiftDecision, Projection, Estimates consumption and downshifts eligible tasks to stay inside it., The meter's own reading, cached briefly. None if unavailable. Disabled by…, Cost of everything still to run, at the tiers currently assigned. (+59 more)

### Community 2 - "Plan"
Cohesion: 0.06
Nodes (84): escalation_changes(), evaluate_gate(), GateVerdict, GroupState, GroupVerdict, StrEnum, The phase gate: what the brain is allowed to know when it wakes up. The…, Every group passed. The phase may be merged and the next one begun. (+76 more)

### Community 3 - "apply_revision"
Cohesion: 0.21
Nodes (22): apply_revision(), persist_revision(), datetime, Path, RuntimeError, Validated, auditable plan revision application. The orchestrator may propose…, Append the audit first, then atomically replace the derived plan view., Latest revision that made each completed descendant stale. (+14 more)

### Community 4 - "test_pricing.py"
Cohesion: 0.07
Nodes (49): CatalogSnapshot, CatalogUnavailableError, _first_int(), _float(), ModelCatalog, parse_models(), _per_mtok(), Any (+41 more)

### Community 5 - "base.py"
Cohesion: 0.09
Nodes (23): ABC, AdapterError, BaseAdapter, DispatchPreview, RuntimeError, The adapter interface. An adapter's job is narrow on purpose: take a fully-…, One dispatch backend. Auth is never implemented here. The `claude` and `codex`…, Describe the dispatch without performing it. No network, no spawn. (+15 more)

### Community 6 - "test_adapters.py"
Cohesion: 0.14
Nodes (49): claude_adapter(), openrouter(), Path, Adapter tests. Every adapter is driven end to end against a fake. The Claude…, The whole point: `usage.input_tokens` is 10, `modelUsage` is 907., Prompts carry file contents; argv has a length limit and is world-readable., Regression: seeding on (task, attempt) alone made every resume collide with…, Observed live: a subagent was denied one tool, worked around it, and produced… (+41 more)

### Community 7 - "Adapter"
Cohesion: 0.13
Nodes (44): extract_plan_json(), Pull a JSON object out of a model response. Tries the whole response first,…, Adapter, Dispatch backends. Auth is always delegated to the official tool., invoke(), PlanningAdapter, fixture, parametrize (+36 more)

### Community 8 - ".run"
Cohesion: 0.15
Nodes (12): Signals, _default_spawn(), ProcessResult, _pump(), Any, Path, Protocol, SIGTERM the group, allow a grace period, then SIGKILL. Shielded because this… (+4 more)

### Community 9 - "Tier"
Cohesion: 0.06
Nodes (67): Backend, ConfigError, ModelOption, _opt_float(), _opt_int(), _parse_backends(), _parse_models(), _parse_tiers() (+59 more)

### Community 10 - "OpenRouterAdapter"
Cohesion: 0.11
Nodes (16): AsyncClient, Response, _HttpFailure, materialize_file_blocks(), OpenRouterAdapter, Any, ClientFactory, Exception (+8 more)

### Community 11 - "AttemptWorkspace"
Cohesion: 0.08
Nodes (28): AttemptWorkspace, contained_regular_file(), Any, Path, The subagent's self-written summary, if it produced one., Match what is on disk against what the task promised. Returns (produced,…, Files the task wrote but never declared. Recorded with an empty ``name`` rather…, True only for a non-symlinked file physically beneath ``root``. Subagents… (+20 more)

### Community 12 - "Sleipnir — Phase 1 design"
Cohesion: 0.05
Nodes (38): Dollars and window quota are different resources, Files, Folding a percentage back into tokens, Module layout, Not built, on purpose, Other decisions worth overruling, Phase 2 — executor, Phase 3 — router (+30 more)

### Community 13 - "schema.py"
Cohesion: 0.12
Nodes (33): AcceptanceCheck, assert_checks_supported(), _check_command(), _check_files(), _check_json_schema(), _dispatch_check(), Any, RuntimeError (+25 more)

### Community 14 - "Path"
Cohesion: 0.17
Nodes (25): config(), governor(), plan_of(), Path, Records recur across resumed sessions; 59% of the real corpus was duplicated.…, A trivial task on a subscription backend is not cheap: the spawn alone costs…, The governor must never stop or reroute a run on a number it could not verify., Moving a task off longctx is a correctness failure, not a saving. (+17 more)

### Community 15 - "ValueError"
Cohesion: 0.16
Nodes (7): field_validator, Self, model_validator, _find_cycle(), model_validator, Return one concrete cycle as a readable path, or None. Iterative (deep DAGs…, ValueError

### Community 16 - "FakeProcess"
Cohesion: 0.15
Nodes (6): StreamReader, FakeProcess, FakeStdin, Test doubles. The fake lives at the *spawn* boundary rather than replacing…, Implements the SpawnedProcess protocol., _reader()

### Community 17 - "theme.py"
Cohesion: 0.11
Nodes (24): _clip(), Model and provider text is untrusted; strip anything non-printable. Same trust…, render(), _wrap(), ease_back_out(), ease_power2_out(), fg(), _fit() (+16 more)

### Community 18 - "console.py"
Cohesion: 0.13
Nodes (26): apply_key(), _clean_paste(), ConsoleState, Message, _paint(), paste_system_clipboard(), play_splash(), poll_secret_request() (+18 more)

### Community 19 - "budget.py"
Cohesion: 0.26
Nodes (10): _parse_bucket(), datetime, Path, Budget governor: what the 5-hour window has cost, and what the plan will. Two…, # NOTE: `iterations` is deliberately ignored. It repeats the same counts, Read every project transcript and return deduplicated usage records., scan_usage(), UsageScan (+2 more)

### Community 21 - "Task"
Cohesion: 0.05
Nodes (47): ArtifactDirResolver, The tier to dispatch ``task`` at, plus why if it moved., _artifact_section(), _describe_check(), _file_section(), IncludedInput, _output_section(), Path (+39 more)

### Community 22 - "test_capabilities.py"
Cohesion: 0.08
Nodes (7): audit_log(), _entries(), fake_ydotool(), fixture, Capability tests are hermetic by construction. Nothing here may inject a real…, Capture ydotool argv instead of running it., test_capture_records_only_the_label_and_length()

### Community 23 - "chat.py"
Cohesion: 0.11
Nodes (26): ask_claude(), ask_router(), ChatError, claude_argv(), extract_queued_instruction(), fast_lane_capable(), Path, RuntimeError (+18 more)

### Community 25 - "clipboard.py"
Cohesion: 0.26
Nodes (11): available(), ClipboardError, ClipboardPayload, offered_types(), Path, RuntimeError, Read text or images from the operator's Wayland clipboard. Keyboard-driven…, The desktop clipboard is unavailable or has no supported payload. (+3 more)

### Community 26 - "DispatchRequest"
Cohesion: 0.11
Nodes (15): DispatchRequest, Run the request to completion, a timeout, or a cancellation. Implementations…, Everything an adapter needs. Fully resolved — adapters never route., ClaudeAdapter, Any, Path, Spawner, Map the CLI's own status vocabulary onto FailureKind. (+7 more)

### Community 27 - "AttemptStatus"
Cohesion: 0.11
Nodes (25): DispatchOutcome, What the adapter observed. Raw facts only, no derived accounting., CodexAdapter, _first_int(), Any, Path, Spawner, Walk every event for the last recognisable usage block. Deliberately structure-… (+17 more)

### Community 28 - "orchestrator.py"
Cohesion: 0.18
Nodes (16): build_control_task(), control_instructions(), control_plan_context(), ControlDecision, ControlError, _extract_decision(), BaseModel, Path (+8 more)

### Community 29 - "WorkspaceCollisionError"
Cohesion: 0.33
Nodes (5): RuntimeError, Ensure an already-claimed workspace remains a real local directory., Atomically claim a new attempt directory; never reuse old contents., An attempt path existed before the harness claimed this attempt., WorkspaceCollisionError

### Community 30 - "Browser"
Cohesion: 0.15
Nodes (9): Browser, Any, An open browser the agent can drive. Deliberately a thin wrapper: it exposes…, Attach to the shared browser, starting it only if nobody has. Attaching rather…, Detach. Deliberately does **not** close the browser. Closing it here is what…, Really end the shared browser, discarding its live tabs. The profile on disk…, CapabilityError, RuntimeError (+1 more)

### Community 31 - "test_handoff.py"
Cohesion: 0.12
Nodes (7): fixture, The credential handoff, and the three live bugs that produced it. Every test…, A full-screen redraw loop that does not switch buffers appends every frame to…, Drawing only one row of the horse emblem renders as debris., requests_dir(), test_the_banner_is_all_or_nothing(), test_the_console_uses_the_alternate_screen()

### Community 32 - "test_budget.py"
Cohesion: 0.22
Nodes (17): allow_utilization_reads, fetch_window_utilization(), Read the CLI's OAuth access token, or None. Returns None for every failure…, Ask the meter. Returns None on any failure, never raises, never logs., read_oauth_token(), _creds(), Budget governor: usage parsing, window detection, projection, downshift. The…, Skip the round trip rather than send a token that will 401. (+9 more)

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

### Community 37 - "handoff.py"
Cohesion: 0.21
Nodes (12): answer(), await_answer(), pending(), Path, Asking the operator for a credential from a process that has no terminal. The…, Tell the waiting process what happened. Status only — never the value., A pending ask. Carries a label; never a value., File a request for the console to fulfil. (+4 more)

### Community 39 - "test_schema.py"
Cohesion: 0.08
Nodes (34): make_layered(), _manifest_for(), _plan(), parametrize, Phase 1 schema tests. The load-bearing test is…, A wide layered DAG: every task in layer k depends on three in layer k-1. This…, Re-tiering a task must NOT invalidate its completed work., The trap found in the real ~/.claude/projects record: input_tokens=2 while… (+26 more)

### Community 40 - "test_theme.py"
Cohesion: 0.16
Nodes (6): Sleipnir — a budget-aware agentic orchestrator. Phases 1–5 provide the schema,…, The chrome must stay a pure function of the frame number, and must never be…, test_frame_lines_never_exceed_requested_width(), test_splash_ends_fully_revealed(), test_splash_renders_every_frame_at_a_narrow_terminal(), _visible()

### Community 41 - "budget"
Cohesion: 0.22
Nodes (9): no_credential_reads(), no_real_utilization_reads(), fixture, Test-suite guardrails. The budget governor reads real window utilisation from…, Never call the usage endpoint from a test. Returns ``None``, which is the same…, Belt and braces: the token must not be read from disk either. A test that needs…, budget(), test_budget_headroom_is_none_when_limit_unknown() (+1 more)

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
Cohesion: 0.19
Nodes (16): fold_results(), Recompute every task's status from the append-only result log. Records are…, finished(), make_chain(), t0000 -> t0001 -> ... Simple shape for status-folding tests., Replaying the log must not double-count cost — recovery depends on it., test_completed_task_is_superseded_when_spec_changes(), test_descendants_are_transitive() (+8 more)

### Community 49 - "InputContract"
Cohesion: 0.15
Nodes (13): ArtifactRef, InputContract, A request for another task's *full* output rather than its summary. Three…, Everything a task is permitted to read. Nothing else is provided to it., Planner-declared upper bound on input size. Feeds tier selection., Input contracts are enforced as filesystem security boundaries., test_dependency_artifact_symlink_cannot_escape_its_attempt(), test_repository_file_symlink_cannot_escape_the_run_root() (+5 more)

### Community 50 - "Sleipnir — project instructions"
Cohesion: 0.14
Nodes (13): Checkpoint discipline, Environment on this machine, Lessons from the first real console session, Money and resources, Rules that will bite you if ignored, Security, Sleipnir — project instructions, The budget governor (Phase 4) (+5 more)

### Community 52 - "PriceSnapshot"
Cohesion: 0.33
Nodes (5): PriceSnapshot, Per-million-token prices as fetched at dispatch time. Never populated from…, Cost of ``usage`` under this snapshot. Missing cache prices fall back to the…, test_cache_write_ttls_are_priced_separately(), test_missing_cache_prices_fall_back_without_undercounting()

### Community 53 - "RetryPolicy"
Cohesion: 0.33
Nodes (5): Tier to use on ``attempt`` (1-indexed). Falls back to ``base_tier``., RetryPolicy, test_escalation_ladder_cannot_exceed_retries(), test_retry_policy_rejects_non_retryable_kinds(), test_tier_for_attempt_walks_the_ladder()

### Community 54 - "process_guard.py"
Cohesion: 0.50
Nodes (4): _install_parent_death_signal(), main(), Run a provider CLI with a Linux parent-death signal installed. An executor can…, Install SIGTERM-on-parent-death, closing the setup race explicitly.

### Community 55 - "ProcessRunner"
Cohesion: 0.21
Nodes (22): skipif, ProcessRunner, Spawner, Runs one child process to completion, a timeout, or a cancellation., fake_spawner(), Any, Build a Spawner that yields FakeProcess objects. ``calls`` captures argv and…, Path (+14 more)

### Community 56 - "parse_usage_line"
Cohesion: 0.10
Nodes (23): _int(), parse_usage_line(), Any, One deduplicated, priced-elsewhere assistant turn., Tokens charged against the 5-hour window. ``cache_read_weight`` exists because…, Extract one usage record, or None if this line does not carry usage. Tolerant…, UsageRecord, window_tokens() (+15 more)

### Community 57 - "Sleipnir — Project State"
Cohesion: 0.15
Nodes (12): Current phase/stage, Decisions log, Environment on this machine, Goal, Guarded fast lane and `/project` (2026-08-19), Next steps, Open questions, Phase 6 progress (2026-08-18) (+4 more)

### Community 62 - "run_is_active"
Cohesion: 0.29
Nodes (5): The brain is asleep exactly when a run owns the directory. Derived, never…, refresh_brain_state(), Path, Whether another file description currently owns the run lock., run_is_active()

### Community 65 - "_widths"
Cohesion: 0.50
Nodes (4): test_an_unbroken_token_longer_than_the_pane_is_hard_split(), test_every_rendered_line_is_exactly_the_terminal_width(), test_narrow_terminal_still_renders(), _widths()

### Community 66 - "run_digest"
Cohesion: 0.50
Nodes (4): _claude_dirs(), Path, A constant-size picture of the run, for the duty officer. This is the whole…, run_digest()

## Knowledge Gaps
- **67 isolated node(s):** `sleipnir`, `The one invariant`, `Rules that will bite you if ignored`, `The router (Phase 3)`, `Money and resources` (+62 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **5 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Tier` connect `Tier` to `make_task`, `cli.py`, `Plan`, `apply_revision`, `base.py`, `test_adapters.py`, `test_schema.py`, `AttemptWorkspace`, `schema.py`, `Path`, `budget.py`, `test_the_run_digest_is_constant_size_and_carries_no_task_output`, `Task`, `RetryPolicy`, `chat.py`, `DispatchRequest`, `AttemptStatus`, `orchestrator.py`?**
  _High betweenness centrality (0.068) - this node is a cross-community bridge._
- **Why does `Plan` connect `Plan` to `make_task`, `cli.py`, `run_digest`, `apply_revision`, `test_schema.py`, `AttemptWorkspace`, `schema.py`, `Path`, `ValueError`, `fold_results`, `InputContract`, `console.py`, `budget.py`, `test_the_run_digest_is_constant_size_and_carries_no_task_output`, `Task`, `orchestrator.py`?**
  _High betweenness centrality (0.067) - this node is a cross-community bridge._
- **Why does `Task` connect `Task` to `make_task`, `cli.py`, `Plan`, `base.py`, `test_schema.py`, `.run`, `Tier`, `AttemptWorkspace`, `schema.py`, `ValueError`, `budget.py`, `test_the_run_digest_is_constant_size_and_carries_no_task_output`, `DispatchRequest`, `AttemptStatus`, `orchestrator.py`?**
  _High betweenness centrality (0.054) - this node is a cross-community bridge._
- **Are the 5 inferred relationships involving `make_task()` (e.g. with `ExpectedOutput` and `InputContract`) actually correct?**
  _`make_task()` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 70 inferred relationships involving `Tier` (e.g. with `DispatchPreview` and `DispatchRequest`) actually correct?**
  _`Tier` has 70 INFERRED edges - model-reasoned connections that need verification._
- **Are the 25 inferred relationships involving `Task` (e.g. with `DispatchRequest` and `BudgetGovernor`) actually correct?**
  _`Task` has 25 INFERRED edges - model-reasoned connections that need verification._
- **Are the 48 inferred relationships involving `Adapter` (e.g. with `BaseAdapter` and `DispatchPreview`) actually correct?**
  _`Adapter` has 48 INFERRED edges - model-reasoned connections that need verification._
