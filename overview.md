# Sleipnir — Overview

_Last updated: 2026-08-19 · Status: Phases 1–9 complete; 403 tests passing._

## What this is

Sleipnir is a manager for AI coding work. You give it one big job. It breaks the
job into many small tasks, works out which tasks depend on which, and then hands
each task to the cheapest AI model that is actually capable of doing it. Some
tasks go to a powerful expensive model, most go to a cheap one. It keeps track of
what has been done, what is running, and what it has spent, and it can be killed
half way through and pick up exactly where it left off.

The whole design exists to solve one specific money problem, and it is worth
understanding because every other decision follows from it.

**The problem.** The obvious way to build something like this is to have one
smart "manager" model that reads every finished task's output and decides what to
do next. That does not work, and not because it is slow — because of arithmetic.
The manager is called once per task. On call number 40 it re-reads the summaries
of all 39 finished tasks. On call 41 it re-reads 40. The total amount of text the
manager reads grows with the *square* of the number of tasks. At 60 tasks that is
merely wasteful. At 600 tasks it needs roughly 48 million tokens of input, which
no usage window on earth will give you.

**The fix.** The manager is never allowed to see finished work. The plan lives in
files on disk. Each time the manager is called, it is given a fresh, small,
**size-capped** summary of the situation — never the accumulated history. This
summary is called the *manifest*.

The measured result:

| tasks in the plan | size of the manifest |
|---:|---:|
| 60 | 2,689 tokens |
| 600 | 2,696 tokens |
| 10,000 | 2,706 tokens |

From 60 tasks to 10,000 tasks the manifest grows by 17 tokens. That is not an
optimisation; it is the reason the project can exist. A test named
`test_manifest_size_is_constant_in_task_count` fails if anyone ever reintroduces
growth.

## Languages & why

- **Python 3.12+** — the whole project. Chosen because the things being
  orchestrated are command-line tools and HTTP endpoints, and because `asyncio`
  handles "run three subprocesses at once and kill them cleanly on timeout"
  without a framework.
- **No agent framework.** Deliberately. The entire value here is precise control
  over what goes into a model's context, which is exactly the thing agent
  frameworks hide from you.

Runtime dependencies are only `pydantic` (data validation) and `httpx` (HTTP).
`pytest` is dev-only.

## Services & APIs used

| Service / API | What it does here | Keys needed? |
|---|---|---|
| `claude` CLI (`claude -p`) | Runs a task using your Claude subscription | No — inherits the CLI's existing login |
| `codex` CLI (`codex exec`) | Same, via your Codex/ChatGPT subscription | No — inherits the CLI's login |
| OpenRouter (chat completions) | The cheap tier, for mechanical tasks | **Yes** — `OPENROUTER_API_KEY` in your environment |
| OpenRouter (`/api/v1/models`) | Current model prices, so costs can be computed | **No** — public endpoint, verified |

**Sleipnir never implements a login flow.** The two CLI adapters shell out to the
official tools and inherit whatever credentials those already hold. OpenRouter
takes a key from the environment. Separately, the budget meter performs one
narrow read of Claude's existing credential file for `claudeAiOauth.accessToken`
so it can call the same read-only usage endpoint as the CLI. That token is never
logged, persisted, placed in state, or exposed by an exception.

An important billing distinction that the code models explicitly: a `claude -p`
call costs about **zero dollars** but consumes your **5-hour usage window**; an
OpenRouter call costs **dollars** but consumes **no window**. These are two
different scarce resources and they do not convert into each other, which is why
`CostEstimate` carries both `amount_usd` and `window_tokens` rather than one
"cost" number.

### Phase 8 modules (the console and the desk)

| File | What it does |
|---|---|
| `theme.py` | Green phosphor palette, flickering border, the logo, and GSAP's easing curves ported as pure functions of a frame number. |
| `console.py` | Full-screen renderer + raw-mode input loop. Owns the terminal, never composes a reply. |
| `chat.py` | Where a message goes: `claude` with session continuity when the brain is awake, a cheap duty officer reading the bounded manifest when it is asleep. |
| `capabilities/computer.py` | Keyboard, mouse, screen, and an operator shell. Wayland-correct via `ydotool`. |
| `capabilities/clipboard.py` | Reads Wayland text/image MIME; images become private model-readable attachments. |
| `capabilities/browser.py` | Playwright Chromium with a persistent, logged-in profile. |
| `capabilities/secrets.py` | One-shot credentials that cannot be printed and wipe on use. |
| `capabilities/audit.py` | Append-only, fsynced record of every privileged action, redacted at the boundary. |
| `capabilities/handoff.py` | Credential requests from TTY-less tool subprocesses, answered by the console. |
| `gate.py` | The phase gate: folds a run into a constant-size verdict, and escalates failed modules one tier without waking the brain. |

## File structure & modularity

```
Sleipnir/
├── src/sleipnir/
│   ├── schema.py         # every data structure, and the rules they must obey
│   ├── projection.py     # turns the event log into "what is the state right now"
│   ├── executor.py       # decides what can run, runs it, records what happened
│   ├── process.py        # the careful bit: subprocesses, timeouts, killing cleanly
│   ├── context.py        # builds the exact prompt text a subtask model receives
│   ├── artifacts.py      # per-attempt folders; collects the files a task produced
│   ├── checks.py         # acceptance checks — did the task actually do the job?
│   ├── runlog.py         # append-only writer for results.jsonl
│   ├── pricing.py        # what each model costs, fetched live, cached to disk
│   ├── config.py         # the operator's TOML policy: which models serve which tier
│   ├── router.py         # picks which model actually runs each task
│   ├── budget.py         # what has been spent, and the only part allowed to refuse
│   ├── planner.py        # turns your prompt into a task DAG
│   ├── revisions.py      # validates/applies/audits mid-run plan changes
│   ├── orchestrator.py   # sparse bounded-manifest Claude control cycles
│   ├── gate.py           # phase gate: constant-size verdict + module escalation
│   ├── tui.py            # bounded, dependency-free live terminal dashboard
│   ├── theme.py          # green chrome, flicker, logo, ported easing curves
│   ├── console.py        # the interactive console you type into
│   ├── chat.py           # routes a message: brain, or cheap duty officer
│   ├── process_guard.py  # forwards executor death to provider process groups
│   ├── cli.py            # the `sleipnir` command
│   ├── capabilities/     # host control — the operator lane, never the worker lane
│   │   ├── computer.py   # keyboard, mouse, screen, operator shell
│   │   ├── clipboard.py  # Wayland text paste + private image attachments
│   │   ├── browser.py    # Playwright Chromium, persistent logged-in profile
│   │   ├── secrets.py    # one-shot credentials that wipe on use
│   │   ├── audit.py      # append-only record of every privileged action
│   │   └── handoff.py    # credential asks from processes with no terminal
│   └── adapters/
│       ├── base.py       # the one interface every provider must implement
│       ├── claude.py     # `claude -p`      (verified against real output)
│       ├── codex.py      # `codex exec`     (verified against CLI 0.148.0)
│       └── openrouter.py # plain HTTP
├── tests/                # 403 tests, including the manifest and verdict size bounds
├── DESIGN.md             # the reasoning, tradeoffs and open decisions
├── project.md            # living state — current phase, decisions, next steps
└── overview.md           # this file
```

Each major module and its job, in plain language:

- **`schema.py`** — defines what a task, a result, a plan and a manifest *are*,
  and refuses to construct invalid ones. Most of the project's safety lives here
  rather than in runtime checks.
- **`projection.py`** — takes the plan plus the log of everything that happened,
  and computes the current status of every task. Pure calculation: no files, no
  network, no subprocesses.
- **`executor.py`** — the scheduler. Works out which tasks are ready (all their
  dependencies finished), runs at most three at a time, handles cancellation, and
  writes the record of what happened.
- **`process.py`** — launching an external command and reading its output while
  it runs, enforcing a timeout, and killing the whole process tree if it hangs.
  This is where deadlocks live in most projects, so it is tested at the spawn
  boundary rather than mocked away.
- **`adapters/`** — one small module per provider. Each knows how to send one
  task and report raw facts back. Adapters deliberately do **not** decide whether
  a task succeeded; the executor does.
- **`pricing.py`** — asks OpenRouter what every model currently costs and saves
  the answer to a file. Prices are never remembered or guessed; if the network is
  down it uses the saved file, and if there is no saved file it refuses to run.
- **`router.py`** — turns "this task needs `code`-level ability" into "run it on
  this exact model, through this exact adapter". See below for how it chooses.
- **`config.py`** — reads your TOML file saying which models are allowed to serve
  which tier. No model name or price is written into the source anywhere.
- **`budget.py`** — works out what has already been spent, and is the only
  component allowed to refuse a task or send it to a cheaper tier. It reads
  Claude Code's own transcripts for *counters only*, never the conversation, and
  asks the meter directly for the true window percentage.
- **`planner.py`** — turns one prompt into a task DAG.
- **`cli.py`** — the `sleipnir` command: `run`, `resume`, `status`, `explain`.
- **`tui.py`** — a pure renderer over the plan and folded log. It never stores
  status or reads task output content. `sleipnir tui` is a zero-spend snapshot;
  `sleipnir tui --watch` follows another run; `sleipnir tui --run` owns and
  executes/resumes the run.
- **`revisions.py`** — applies typed task/edge changes to a copy, validates the
  whole resulting DAG, computes superseded and stale completed work, fsyncs the
  audit, and atomically replaces the plan view.
- **`orchestrator.py`** — wakes the expensive reason-tier brain only after
  automatic execution reaches an impasse. Its prompt is the capped manifest
  plus a constant-bounded drill-down of urgent task specs; no artifact content
  or worker transcript can enter.

### Files created while running (not in the repo)

| File | What it is | Can it be edited? |
|---|---|---|
| `plan.json` | the task DAG | only through a logged revision |
| `results.jsonl` | one line per thing that happened | append-only, never rewritten |
| `revisions.jsonl` | record of every mid-run plan change | append-only |
| `artifacts/task-<id>/attempt-NN/` | the actual output files and transcripts | written once per attempt |

All of these are in `.gitignore`. A `plan.json` **executes shell commands** via
`CommandCheck`, so it is executable content — never run one from a source you do
not trust.

## How the code works (the walkthrough)

1. A **plan** describes tasks, which tasks depend on which, what each task must
   produce, and how to check it worked. Each task declares a *tier* — how hard
   the work is — never a specific model name.
2. **`projection.fold_results`** reads the event log and replays it over the plan
   to work out each task's status. Nothing stores status as a field.
3. The **executor** asks: which tasks have all their dependencies satisfied? It
   takes up to three of those and dispatches each one.
4. **`context.py`** builds the prompt: the task description, plus the short
   summaries of the tasks it depends on, plus (only if explicitly justified) the
   full contents of specific files an earlier task produced.
5. An **adapter** sends that prompt to a provider and returns raw observations —
   what came back, how many tokens, did it time out.
6. The executor collects whatever files landed on disk, runs the **acceptance
   checks**, and writes a result record. If the task half-worked, that is
   recorded precisely — which outputs are missing, by name — rather than being
   flattened into "failed".
7. Finished work is folded back into a fresh, capped **manifest**, and the cycle
   repeats.

With `sleipnir orchestrate`, successful workers complete without another Claude
call. Only a terminal failure/partial/budget decision wakes the control model.
It returns `continue`, `stop`, or a typed revision. Invalid changes, cycles, and
semantic edits disguised as cheap retargets are rejected locally before the
plan changes.

If the executor is hard-killed after its fsynced start record but before its
finish record, the next run closes that orphan as `INTERRUPTED` and retries in a
new attempt directory. It first probes the recorded executor PID and refuses to
steal work from a process that is still alive.

Before any recovery or scheduling begins, the executor also takes a kernel-backed
exclusive `run.lock`. This closes the small but expensive race where two fresh
processes could both see a READY task before either wrote its start record. The
kernel releases the lock automatically after a crash.

Every file crossing into a prompt or summary is treated as untrusted. Paths
must stay under their declared root, symlinks are not followed, task outputs
cannot collide with harness-owned logs/state, and delegated CLI subprocesses do
not inherit unrelated API keys or CI tokens from the operator's shell.

### How the router chooses a model

The division of labour is the whole idea: **a person declares capability, the
machine decides cost.**

Putting a model into a tier's list is a human claim that it can do that kind of
work. Nothing in the price catalogue could ever establish that — there is no
"good at architecture" column — so the router does not try to guess it. Among the
models you have already declared capable, it then:

1. **Throws out anything that physically cannot hold the task's input.** If a
   task declares it will read 4MB, a model with an 8,000-token window is not a
   candidate. An *unknown* window is not treated as too small, because refusing
   on missing data rejects models that would have worked.
2. **Scores what is left**, including the fixed cost of merely starting a call.
   This matters more than it sounds: launching `claude -p` burns about 30,000
   tokens before any work happens — $0.04 on Haiku, $0.20 on Opus, measured at
   real prices. For a small task that startup fee *is* the entire bill, so a
   rename or a reformat should almost never go to a CLI.
3. **Picks the cheapest in whichever resource is scarce**, using the other only
   to break ties. On a subscription that means window quota, where a paid
   OpenRouter call scores zero because it consumes no window at all.

There is one nice accident in this. Because retries ask for the *n*-th cheapest
option rather than the cheapest again, a task that fails simply moves up the
list — `reason` work runs on Sonnet first and Opus on the retry. That is
escalation, and nobody wrote an escalation ladder to get it. It also solves a
real problem found in testing: free models rate-limit one at a time, so repeating
an identical call just fails identically, while asking for the next option
usually succeeds.

### How the budget governor decides

The quota pools do not convert. A `claude -p` call spends **Claude 5-hour
window quota**, a subscription-backed `codex exec` call spends **Codex quota**,
and an OpenRouter call spends **dollars**. Codex tokens are reported separately
and never charged to the Claude projection. A nearly-full Claude window must
not block Codex or OpenRouter work, and a blown dollar budget must not be
"fixed" by choosing a cheaper metered model—only refusing stops that spend.

Claude's authenticated `GET /api/oauth/usage` endpoint reports the five-hour
window as a percentage, not a token limit. The governor reads that percentage
through a narrowly scoped credential helper, then derives the token limit that
is consistent with locally observed usage. Every credential or network failure
falls back to local estimation rather than failing the run, and endpoint
failures are cached to prevent a 429 retry storm.

An observed rate-limit rejection remains ground truth and outranks every
estimate. It stops subscription dispatch while leaving metered OpenRouter work
alone, because those spend different resources.

One thing it will not do at any price: quietly downgrade a task that needs a huge
context window. That is not a saving, it is a task that now fails for a different
reason.

### What "how much have I spent" actually costs to answer

Reading those usage records correctly is harder than it looks, and every rule in
`budget.py` comes from measuring 2,760 real records rather than from reasoning:

- **The same turn is recorded more than once.** 52% of the records were repeats,
  because a resumed session re-writes earlier turns. Counting them all does not
  merely skew the total — it *doubles* it.
- **The obvious "input tokens" field is nearly always wrong.** Across the whole
  corpus it summed to 35,198 against 513 million tokens of real input. Almost all
  input arrives as cached tokens under different names.
- **There is a second copy of every number** in an `iterations` list. Adding both
  doubles every turn again.
- **Nine records were not real API calls at all** — the tool's own generated
  messages. Charging for those invents money that was never spent.

### The two ideas that make it robust

**Status is never stored.** It is always recalculated from the log. There is no
checkpoint file that can drift out of sync with reality, which is why crashing
half way through is an ordinary event rather than a repair job. Recovery at task
40 of 60 is: read the log, recalculate, find 39 done and 1 interrupted, re-run
that one. Nothing completed is lost and no money is re-spent.

**A task's identity ignores its routing.** `Task.spec_hash()` is a fingerprint
built from what a task *means* — its description, dependencies, inputs, outputs,
checks — and deliberately **excludes** which model tier it uses. If tier were
included, the budget governor moving a task to a cheaper model would throw away
that task's finished output, and the governor and the executor would fight each
other forever.

## How to run / test locally

The README says `uv`, which is **not installed on this machine**. Use stdlib
`venv`:

```sh
cd /home/venug/Sleipnir
python3 -m venv .venv
.venv/bin/python -m pip install "pydantic>=2.7" "httpx>=0.27" "pytest>=8"
.venv/bin/python -m pytest -q
```

Last verified run: **403 passed** on Python 3.14.6. `pip check`, `compileall`,
and `git diff --check` are also clean.

Host control needs a third runtime dependency and one privileged install:

```sh
.venv/bin/pip install playwright
.venv/bin/sleipnir setup     # prints every root command before running it
.venv/bin/sleipnir doctor    # reports what this machine can actually do
```

`setup` installs `ydotool` and `wl-clipboard`, writes a udev rule granting the
user `/dev/uinput`, adds the user to the `input` group, and fetches the Chromium
build Playwright drives. It exists so nobody hand-runs sudo out of a README. A
new login session is needed afterwards for the group change to apply.

### The console

Bare `sleipnir` — no subcommand — opens the interactive console: a boot
animation, then a green frame that flickers while you type. What you type is
**not** answered by Sleipnir. Ordinary messages enter a guarded fast lane. A
tool-free Haiku turn first returns a strict capability verdict; because its CLI
invocation has `--tools ""`, it cannot click, type, browse, or edit while making
that decision. An exact affirmative lets Haiku handle the request. Anything
else goes to Sonnet. A failed action is not replayed automatically because it
may already have changed the host. Both turns retain conversation continuity
through `--session-id` and `--resume`.

`/project <goal>` bypasses chat and launches Sleipnir's existing planner and
orchestrator. That means large work uses the same task DAG, model-tier routing,
budget governor, acceptance checks, phase gate, and human review boundary as
the batch CLI rather than a console-specific imitation. `--fast-model` and
`--model` select the two aliases; an empty fast alias disables the check.

The console explicitly enables bracketed paste, so Ctrl+Shift+V text—including
multiple lines—arrives as one edit rather than escape-sequence debris or partial
submissions. A terminal PTY cannot carry pixels. For an image paste event,
Sleipnir asks the Wayland clipboard for its offered MIME, writes the selected
image to a private `0600` file under `~/.sleipnir/clipboard`, and adds that
directory to Claude's allowed roots. Agent-driven copy/paste uses
`sleipnir computer copy|paste`, which injects Ctrl+Shift+C/V into the focused
application and therefore leaves text-versus-image ownership to the desktop.

The batch subcommands are all still there: `plan`, `run`, `resume`, `status`,
`explain`, `tui`, `orchestrate`, `apply-revision`, plus the new `setup`,
`doctor`, `computer`, `browser` and `secret`. The TUI's `--orchestrate` mode
owns the same sparse-control loop while rendering live plan revisions and
bounded control events.

The console runs Claude in `bypassPermissions` by default, because a tool that
stops to confirm every click is not a tool that can drive a desktop. That is the
most consequential fact about a session, so it is stated in the footer for as
long as it is true — `FULL HOST CONTROL` — rather than behind a launch prompt
that gets dismissed once. `sleipnir console --ask-first` narrows it back to
`acceptEdits`, which confirms each action and confines the model to the repo.

### The phase gate

When `orchestrate` finishes an executor pass and the run is not complete, the
gate runs before anything expensive. `evaluate_gate` folds the plan and the
result log into one verdict per group: how many tasks are done, how many failed,
and which ids. It is the same size for a 5-task run and a 500-task run, which is
the point — this is what the brain is allowed to know.

If a group failed, the harness tries to fix it without help: each genuinely
failed task is re-run one tier stronger, with exactly one extra attempt. That is
a `retarget_task` revision touching only `tier` and `retry`, both outside
`spec_hash`, so completed work in the group survives and the change auto-applies
without operator review. Only then, if the gate cannot fix it, is the brain
woken. `--no-auto-escalate` skips straight to the brain.

The console reads the same machinery from the other side. An owned run lock
means an executor is mid-build, so the brain is asleep; a message then goes to a
cheap OpenRouter duty officer along with the gate digest and nothing else. If
the message asks for a *change* rather than information, the duty officer
refuses to act and returns a `QUEUE:` line, which is shown to you and handed to
the brain as text on its next turn.

### Host control, in one paragraph

`sleipnir computer` types, clicks, moves the pointer, captures the screen, and
sends Ctrl+Shift+C/V without flattening the clipboard payload.
Under Wayland none of that can be done the X11 way, so input is injected into
`/dev/uinput` through `ydotool` — the events are indistinguishable from a
physical keyboard, which is why every call is written to
`~/.sleipnir/capability-audit.jsonl`. `sleipnir browser` drives a real Chromium
with a persistent profile, so logins survive between runs. `sleipnir secret
prompt "<label>"` asks *you* for a credential inside the console — a tool
subprocess has no terminal of its own, so it files a labelled request and waits
while the console prompts you in its own frame — and injects it straight into
the focused window; the model that called it learns only that a
credential was supplied. Nothing is stored, logged, or returned.

## How to add code / extend it

- **To add a new AI provider:** create a module in `src/sleipnir/adapters/`
  implementing the interface in `adapters/base.py`. Return a `DispatchOutcome`
  containing only what you observed. Do not decide success or failure there — the
  executor owns that judgement, because only it knows whether the acceptance
  checks passed.
- **To add a new kind of acceptance check:** extend `checks.py`. Any check that
  cannot actually be performed must fail loudly *when the executor is
  constructed*, not when the task runs. Discovering at task 40 that a check was
  silently a no-op is worse than refusing the plan up front.
- **To change what the orchestrator can see:** edit the manifest caps in
  `schema.py`. A manifest validates itself against its own caps at construction,
  so an over-budget manifest cannot be built. If you widen a cap, expect
  `test_manifest_size_is_constant_in_task_count` to have an opinion.
- **To add a host capability:** put it in `capabilities/`, route it through
  `audit.record`, and expose it as a `sleipnir <noun> <verb>` subcommand in
  `cli.py` — then add the line to `console.CAPABILITY_BRIEF`. The brief is how
  the model learns the capability exists; a command nobody told it about will
  never be called. Never hand a capability to a dispatched worker task.
- **To change the console's look:** everything visual lives in `theme.py` and is
  a pure function of an explicit frame number. Add easing curves there rather
  than reaching for an animation library — a terminal cannot run one, and the
  determinism is what makes the splash testable with no terminal attached.
- **To pad or truncate a coloured line:** use `theme._fit`, never `len()` and
  `ljust`. Colour escapes are ~20 invisible bytes per line; measuring them as
  columns silently collapses the border.

**Rules to respect:**

- Never add a field anywhere in `Manifest` that can carry file contents. Paths
  only. This is the invariant the whole project rests on.
- Never add a runtime dependency casually. There are two required (`pydantic`,
  `httpx`) and one optional (`playwright`, under the `host` extra).
- Never put an API key in the repo. `OPENROUTER_API_KEY` comes from the
  environment.
- Never log the content of a keystroke, a form fill, or a credential. The audit
  redactor runs at the boundary and records lengths; keep it that way.
- Never add a `Secret` accessor that returns plaintext without wiping the
  buffer, and never remove one of its rendering overrides. A single stray
  f-string is all it takes to put a password in a transcript permanently.

## Known limitations / TODO


- **Sparse control is provider-verified.** A bounded Claude control call
  retargeted a seeded terminal failure without changing task meaning; the
  persisted revision then delegated the accepted retry to Codex. Completed
  valid and invalid brain calls now land on the append-only accounting stream.
- **Local window-token accounting remains deliberately pessimistic.** Cache
  reads are counted 1:1 by default, but the authenticated utilization percentage
  self-calibrates the implied limit whenever the provider meter is available.
- **`llm_judge` acceptance checks are unimplemented** and raise on purpose.
- **Server-tool accounting is provider-aware.** Search/fetch request counts are
  durable usage fields. Frozen catalogue search rates feed fallback estimates;
  provider totals win when present, avoiding double charges. Anthropic web
  fetch currently has no separate request fee, though fetched tokens still bill.
- **The router assumes every task produces about 2,000 tokens of output.** Output
  is priced several times higher than input, so this flat guess moves the
  rankings. A real per-task estimate should come from the planner in Phase 4.
- **`code`-tier work starts on a free model.** Cheapest possible first attempt,
  but it leans hard on the acceptance checks to catch a weak result.
- **Two host-capability joins remain unverified.** Console→Claude→screenshot is
  live-proven. Browser and credential handoff work standalone but have not yet
  been invoked by Claude from inside the real console.
- **The phase gate still needs its final live run.** Constant-size group verdicts,
  failed-module-only escalation, finite retry grants and derived brain sleep are
  implemented and hermetically covered; provider quota blocked the live pass.
- **Playwright is optional and unpinned to a browser build.** `sleipnir setup`
  fetches Chromium; a machine that skips setup gets a clear
  `CapabilityError`, not a crash.
- **Desktop control is Linux-only.** `ydotool` and `/dev/uinput` are kernel
  facilities with no macOS or Windows equivalent; `probe()` reports what is
  missing rather than pretending.
