# Sleipnir — Overview

_Last updated: 2026-08-18 · Status: phases 1-5 complete; final gate pending._

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
official tools and inherit whatever credentials those already hold. Only
OpenRouter takes a key, read from the environment and never stored in the repo.

An important billing distinction that the code models explicitly: a `claude -p`
call costs about **zero dollars** but consumes your **5-hour usage window**; an
OpenRouter call costs **dollars** but consumes **no window**. These are two
different scarce resources and they do not convert into each other, which is why
`CostEstimate` carries both `amount_usd` and `window_tokens` rather than one
"cost" number.

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
│   ├── cli.py            # the `sleipnir` command
│   └── adapters/
│       ├── base.py       # the one interface every provider must implement
│       ├── claude.py     # `claude -p`      (verified against real output)
│       ├── codex.py      # `codex exec`     (UNVERIFIED — flags not confirmed)
│       └── openrouter.py # plain HTTP
├── tests/                # 217 tests, including the manifest size bound
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

Two resources, and they do not convert. A `claude -p` call spends **5-hour
window quota** and almost no dollars; an OpenRouter call spends **dollars** and
no window. So a nearly-full window must never block an OpenRouter call, and a
blown dollar budget must never be "fixed" by choosing a cheaper model — a
cheaper model still costs money, and only refusing actually stops the spend.

The awkward part is that **Sleipnir cannot see your real window limit.** Claude
Code itself asks an authenticated endpoint (`GET /api/oauth/usage`) which
answers in percentages, not tokens. Reaching it needs the login token the
`claude` CLI holds, and Sleipnir's rule is that it never touches your
credentials — the adapters shell out to the official tools precisely so the
secret stays with the tool that owns it.

So the governor does the honest thing: **when it does not know the limit, it says
so and allows the work**, while reporting how fast you are burning. A guessed
limit is worse than none — it either throttles a run that had plenty of room, or
waves through one that did not, and you cannot tell which happened.

What it leans on instead is the one signal that is never a guess: an actual
rate-limit rejection from the API. When that arrives, the window really is spent,
and that fact outranks every estimate. Subscription work steps down a tier;
OpenRouter work carries on untouched.

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

Last verified run: **118 passed** on Python 3.14.6.

There is no command to run yet — the CLI is Phase 5, and the planner that would
give it something to do is Phase 4.

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

**Rules to respect:**

- Never add a field anywhere in `Manifest` that can carry file contents. Paths
  only. This is the invariant the whole project rests on.
- Never add a runtime dependency casually. There are two.
- Never put an API key in the repo. `OPENROUTER_API_KEY` comes from the
  environment.

## Known limitations / TODO


- **The `codex` adapter is unverified.** Its flags were written without the CLI
  present. `codex` is now installed here, so this can be cleared.
- **Window-token accounting is roughly 10× too pessimistic.** Cache reads are
  ~94% of measured window usage and are currently counted as equal to input
  tokens, though they are priced far lower. Kept deliberately pessimistic until
  Phase 3 measures what the window really counts.
- **`llm_judge` acceptance checks are unimplemented** and raise on purpose.
- **`server_tool_use` is captured but not yet priced.** Web search and fetch are
  billed per request; no run has used them yet.
- **The router assumes every task produces about 8,000 tokens of output.** Output
  is priced several times higher than input, so this flat guess moves the
  rankings. A real per-task estimate should come from the planner in Phase 4.
- **`code`-tier work starts on a free model.** Cheapest possible first attempt,
  but it leans hard on the acceptance checks to catch a weak result.
