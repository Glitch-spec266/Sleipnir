# Sleipnir

<p align="center">
  <img src="assets/sleipnir-mark.svg" width="600" alt="Sleipnir — eight-spoke orchestration mark">
</p>

A budget-aware agentic orchestrator. Takes one complex project prompt,
decomposes it into a task DAG, and dispatches each task to the cheapest model
tier that can do it — while keeping the expensive orchestrator model's context
flat and staying inside a 5-hour usage window.

The design serves one insight: **delegation only saves money if subtask output
never re-enters the orchestrator's context.** The plan lives on disk. The
orchestrator is re-invoked fresh each cycle with only a compact, size-bounded
manifest.

## Status: Phases 1–20 implemented; desktop alpha active

| Phase | Scope | State |
|---|---|---|
| 1 | state schema + design | complete |
| 2 | executor + adapters (`claude`, `codex`, `openrouter`) | complete |
| 3 | tier router | complete |
| 4 | budget governor | complete |
| 5 | CLI | complete |
| 6 | end-to-end resume gate, review, pentest | complete |
| 7 | dependency-free live TUI + sparse-control console | complete |
| 8 | interactive console + audited host/browser/credential control | complete |
| 9 | phase gate + automatic escalation before scarce-brain wakeup | complete |
| 10 | multi-provider streaming console | complete |
| 11 | live gate and multi-provider verification | complete |
| 12 | server-tool and authoritative-cost accounting | complete |
| 13 | routing and budget adversarial hardening | complete |
| 14 | live capabilities and first complete run | complete |
| 15 | staged dependency delivery + live sparse-control route | complete |
| 16 | provider-outage failover allowance | complete |
| 17 | live console routing and provider controls | complete |
| 18 | Linux-native SwiftPM iOS capability through xtool | complete; live arm64 build verified |
| 19 | capability audit of every old and new ability | complete |
| 20 | protected askpass agent, encrypted party, iOS gate, Windows audit | complete on Linux; hardware gates recorded |
| 21 | production desktop GUI over the existing run-owning core | active on `gui`; native alpha packages on all three platforms |
| 22 | same-model intelligence amplification and Cowork demolition gate | required after GUI; benchmark specification written |

Read [`DESIGN.md`](DESIGN.md) for the tradeoffs, the manifest size math, and the
open decisions.

The post-GUI product objective is not feature parity with a single-agent
desktop assistant. Sleipnir must use skills, evidence, diverse candidates,
verification, repair, synthesis, and empirical routing to make the same
underlying model decisively outperform Claude Cowork across quality, accepted
cost, credits, speed, efficiency, adaptability, background non-interference,
and output quality. This is a measured release gate rather than a current
performance claim. See the
[`Quality and Efficiency Roadmap`](docs/ROADMAP.md) for the
comparison controls, initial targets, restrictions, and required architecture
in [the tracked design](DESIGN.md#phase-22--intelligence-amplification-and-design-competency).

## What exists

```
src/sleipnir/schema.py       pydantic models for plan.json, results.jsonl,
                             revisions.jsonl, and the derived Manifest
src/sleipnir/projection.py   pure fold of results over plan -> task status,
                             and the bounded manifest projection
src/sleipnir/executor.py     readiness, concurrency cap, cancellation, dry run
src/sleipnir/adapters/       claude/codex CLIs plus OpenRouter-compatible,
                             generic OpenAI-compatible, and Anthropic HTTP
src/sleipnir/process.py      async subprocess: streaming, timeout, tree kill
src/sleipnir/context.py      InputContract -> the exact subagent prompt
src/sleipnir/artifacts.py    attempt workspaces and output collection
src/sleipnir/checks.py       acceptance checks
src/sleipnir/runlog.py       append-only results.jsonl, fsync per record
src/sleipnir/pricing.py      live OpenRouter catalogue, TTL cache
src/sleipnir/config.py       TOML backend + per-tier policy
src/sleipnir/router.py       tier -> model, with full routing rationale
src/sleipnir/budget.py       5-hour window accounting and downshift
src/sleipnir/planner.py      prompt -> validated task DAG
src/sleipnir/revisions.py    typed, audited mid-run plan changes
src/sleipnir/orchestrator.py sparse bounded-context brain decisions
src/sleipnir/gate.py         constant-size phase verdict + finite escalation
src/sleipnir/tui.py          bounded DAG / routing / budget terminal dashboard
src/sleipnir/console.py      guarded chat + `/project` multi-model front door
src/sleipnir/chat.py         Claude session transport + tool-free fast-lane gate
src/sleipnir/party.py        encrypted, signed cross-machine agent collaboration
src/sleipnir/capabilities/agent.py
                             session-only credential cache outside worker context
src/sleipnir/capabilities/askpass.py
                             pinentry/GUI prompt and bounded askpass protocol
src/sleipnir/capabilities/ios.py  xtool/SwiftPM iOS bridge for Linux and Windows
src/sleipnir/cli.py          plan / run / console / ios / agent / askpass / sudo
src/sleipnir/platform/       the one seam between Sleipnir and the OS:
                             POSIX, macOS and Windows backends behind one API
src/sleipnir/capabilities/computer/
                             desktop control: ydotool on Linux, Quartz on
                             macOS, SendInput and GDI on Windows, audited
                             in one place
src/sleipnir/gui.py          artifact-safe desktop dashboard projection
src/sleipnir/gui_agent.py    desktop ambient/Codex/Claude routing boundary
src/sleipnir/voice/          wake/VAD, speech, Ollama vision/tools, and relays
desktop/                     React/Vite renderer and Tauri 2 native host
tests/                       720 passing tests, including the executable form of the
                             manifest size bound
```

Provider auth is never persisted by Sleipnir. The `claude` and `codex` adapters
inherit official-CLI credentials. HTTP backends keep only an environment
variable name in configuration; OpenRouter-compatible, generic
OpenAI-compatible, and direct Anthropic endpoints read the value at dispatch.
Raw API keys are not valid TOML fields or slash-command arguments.

## The property everything else rests on

The orchestrator's per-cycle context does not grow with the size of the plan:

| tasks | manifest tokens |
|---:|---:|
| 60 | 2,689 |
| 600 | 2,696 |
| 10,000 | 2,706 |

`test_manifest_size_is_constant_in_task_count` fails if a change reintroduces
growth.

## Development

Python 3.12+. Runtime dependencies: `pydantic`, `httpx`, and `cryptography`.
No agent frameworks.

The desktop client lives in `desktop/`. Its renderer can be exercised without
native prerequisites:

```sh
cd desktop
npm ci
npm test -- --run
npm run test:e2e
```

`npm run tauri dev` additionally needs the platform Tauri prerequisites. On
Linux that includes WebKitGTK 4.1. Release CI builds unsigned AppImage, DEB,
RPM, MSI/NSIS, DMG and app-bundle artifacts; production signing and updater
keys are intentionally not claimed until release credentials exist.

### Local JARVIS lane

The desktop can use an operator-installed Ollama model as a local multimodal
assistant. The tested Linux configuration is `qwen3.5:4b` under the alias
`jarvis`, with a 16K context. Conversation uses a short text-only turn; screen
observation uses one current frame without action tools. Commands receive the
relevant browser, desktop, or document tools. Browser actions return bounded
DOM state and replace the old image; native actions receive a fresh frame.
Temporary screen captures are removed immediately. Hard work can be delegated
to the installed Claude Code or Codex CLI.

Continuous wake listening applies local energy-based voice segmentation before
Whisper, so a quiet room does not spawn repeated transcription jobs. Set
`SLEIPNIR_WHISPER_MODEL` for a custom location. Desktop autostart also discovers
`ggml-small.en.bin` or `ggml-base.en.bin` under
`$XDG_DATA_HOME/whisper-models/` (normally
`~/.local/share/whisper-models/`). Pre-wake transcripts stay inside the
listener. “Hey, <wake name>” opens a conversation: follow-ups need no repeated
wake phrase until 15 seconds of quiet. That window restarts after the app
finishes its reply, so processing time does not consume it. The local model
stays warm while listening is enabled. Recent conversation is recovered from
encrypted history across turns and wake cycles, limited to eight messages
from the last six hours.

The desktop permission posture still applies. `ask` allows observation and
safe navigation. Asking to answer or fill a form also authorizes entering its
answers; submitting still requires an explicit request or approval. Other
clicks, fills, and typing return `approval_required` under `ask`; one approval
covers that turn's task. A blocked tool stops the loop immediately. `always`
enables those audited actions. Credentials remain outside the local model and
use Sleipnir's protected credential prompt.

The workbench scrolls within its content area while the navigation dock remains
visible. A second desktop launch opens the existing instance, keeping one wake
listener active.

### Phone hub

Enable **Settings → Phone hub** and copy its address and pairing token into the
iOS client in `ios/SleipnirHub`. Both devices must be on the same reachable
local network; use the desktop's current address if it changes. The hub requires
the token for every request and provides run status, pending reviews, an
on-demand screen view, and a voice-listener toggle. Disable the hub in Settings
to stop it immediately.

The iOS client targets iOS 16 or later, declares local-network access, and keeps
the token in the device keychain. Allow Local Network access when prompted;
if previously denied, enable it in iOS Settings for SleipnirHub. Build an
unsigned IPA on Linux with
`sleipnir ios ipa-unsigned --project ios/SleipnirHub -- -c release`.

On current Arch/CachyOS, Tauri's cached `linuxdeploy` contains an older `strip`
that cannot parse modern `.relr.dyn` ELF sections. Build AppImage with:

```sh
cd desktop
NO_STRIP=true npm run tauri build -- --bundles appimage
```

## Install

Sleipnir is a Python command-line tool, not an npm package. The `sleipnir`
name on npm is already used by an unrelated project. Once a release has been
published to PyPI, install it globally with either command below:

```sh
uv tool install sleipnir
# or, if you use pipx
pipx install sleipnir
```

Then open the console or inspect the available commands:

```sh
sleipnir
sleipnir --help
sleipnir --version
```

To install the current GitHub version before a PyPI release, use:

```sh
uv tool install git+https://github.com/Glitch-spec266/Sleipnir.git
```

For an npm-style global install, use the npm launcher:

```sh
npm install -g sleipnir-cli
sleipnir --help
```

Python 3.12 or later is required. The host/browser integration is deliberately
optional; add it only on a machine that needs it:

```sh
pipx install 'sleipnir[host]'
sleipnir setup
```

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python "pydantic>=2.7" "httpx>=0.27" "cryptography>=46" "pytest>=8"
.venv/bin/python -m pytest -q
```

On Windows the same three commands, with the interpreter where Windows puts it:

```powershell
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe "pydantic>=2.7" "httpx>=0.27" "cryptography>=46" "pytest>=8"
.venv\Scripts\python.exe -m pytest -q
```

## Windows

Linux and Windows are both first-class. Every OS call — process trees, file
locking, console raw mode, shell selection, input injection, screen capture —
goes through `src/sleipnir/platform/`, which picks a backend once at import;
no other module branches on the platform. Nothing extra is installed and
nothing needs administrator rights: input is `user32.SendInput`, capture is
GDI plus a stdlib PNG encoder, and process containment is a job object.

Four differences are real and worth knowing before you rely on them:

- **Input injection is user-mode, not kernel-level.** ydotool writes to
  `/dev/uinput`, below the input stack. `SendInput` sits above it, so UIPI
  blocks it from reaching windows owned by an elevated process, the UAC secure
  desktop is unreachable by design, and software that checks `LLMHF_INJECTED`
  (anti-cheat, DRM, some banking apps) can tell the input is synthetic.
  `sleipnir doctor` reports whether this process is elevated for that reason.
- **A POSIX shell is a soft prerequisite.** `CommandCheck` commands in a
  `plan.json` are written POSIX-style, so Sleipnir prefers `sh` — from
  `$SLEIPNIR_SHELL`, then `PATH`, then a Git for Windows install — and falls
  back to `cmd.exe` with a loud `doctor` warning. `sleipnir setup` offers
  `winget install --id Git.Git` when none is found.
- **Codex's worker sandbox is weaker.** Its `workspace-write` mode is kernel-
  enforced on Linux and macOS; on Windows it is closer to an intention than a
  guarantee. Sleipnir cannot fix that, and says so rather than implying a
  containment it is not getting.
- **Parent-death containment is *stronger*.** `PR_SET_PDEATHSIG` sends a
  signal a provider CLI can trap; a job object with `KILL_ON_JOB_CLOSE` is
  unconditional and covers the whole descendant tree, so a hard-killed
  Sleipnir cannot leave a spending orphan behind.

State lives in `~/.sleipnir/` and `~/.cache/sleipnir/` on both platforms —
one location is easier to explain, and moving it would orphan existing runs.

## Terminal dashboard

`sleipnir tui` prints a read-only snapshot and cannot dispatch anything.
`sleipnir tui --watch` follows a run, and `sleipnir tui --run` executes or
resumes it under the run-directory lock while displaying live DAG, route and
budget state. The dashboard adds no runtime dependency and never displays
subagent summaries or artifact content.
`sleipnir tui --orchestrate` adds the bounded sparse-brain loop to that same
console; plan revisions reload live and review-required proposals are surfaced.
Read-only/watch modes are catalogue-free and offline; their usage line derives
metered dollars, Claude-window tokens, and Codex tokens directly from the log.
All untrusted display values are stripped of terminal control characters.

## Interactive console

Bare `sleipnir` opens the full-screen console. Ordinary messages first receive
a tool-free Haiku capability check in a disposable session. Built-in tools are
disabled and MCP discovery is replaced by an explicit empty configuration, so
the classifier cannot touch the host; the binary protocol replaces its default
agent system prompt. Only an exact one-turn affirmative lets Haiku act in the
separate durable session. Declines and malformed verdicts go to Sonnet with the
untouched request. A failed action is never automatically replayed because it
may already have had a side effect. `--fast-model` and `--model` override the
two aliases, and an empty `--fast-model` disables the gate.

`/project <goal>` is the explicit boundary for larger work. It bypasses ordinary
chat and runs the existing `plan` then `orchestrate` commands, so decomposition,
tier routing, budgets, acceptance checks, phase-gate escalation, and review gates
remain the same pipeline as batch operation. In a bare console every invocation
gets a fresh named workspace beneath `./runs`; `--run-root` opts into one exact
workspace instead.

The console enables terminal bracketed-paste mode, so Ctrl+Shift+V inserts
multiline text atomically instead of leaking CSI markers or submitting halfway
through. Clipboard images cannot travel through a text PTY; when the terminal
forwards the paste event, Sleipnir reads the image MIME with `wl-paste`, saves it
as a private `0600` attachment, and gives Claude the path. The agent-facing
`sleipnir computer copy` and `sleipnir computer paste` commands emit real
Ctrl+Shift+C/V chords, preserving either text or image MIME in the focused app.
For browser credentials, `secret prompt "<label>" --browser-selector "<css>"`
fills the persistent page over CDP; focusing the console to type the masked
value therefore cannot steal the target field. The first matching request
opens a native `pinentry` dialog; later requests reuse the value from an
idle-expiring agent. Retained values exist only in locked, non-dumpable session
memory and are wiped on expiry or `sleipnir agent stop`. Dispatched workers are
stripped of the socket address and askpass hook; on Linux the agent also rejects
a peer whose process ancestry carries Sleipnir's worker marker. The provider's
kernel sandbox remains the outer boundary. For privileged commands use
`sleipnir sudo -- <command>` or the console's explicit `/sudo <command>`.

`/party create [name]` starts an encrypted cross-machine party and places its
join code on the clipboard without printing it. A peer uses `/party join
[name]` and pastes the code into a GUI, keeping the relay credential out of the
console and model transcript. `/party say`, `/party ask`, `/party mode
collaborate|delegate`, and leader-only `/party assign` provide coordination and
hierarchy. `/party sync` lets the local Claude agent answer waiting peers in a
fresh, bounded turn with built-in and MCP tools disabled. Peer text is never
executed or applied to a plan; local work and plan revisions keep their normal
operator gates. The default ntfy relay sees only a random topic and signed
AES-GCM ciphertext.

The splash uses a letter-free eight-spoke radial emblem; the frame title carries
the product name, so the mark itself stays legible even in a narrow terminal.

The local command registry also exposes `/router`, `/provider`, `/config`,
`/run-root`, and `/cache-read-weight`. Provider additions are session-scoped and
written to a private temporary config used by project child processes. For
example, an OpenAI-compatible service is registered as:

```text
/provider add <name> openai <model> <base-url> <API_KEY_ENV> [context] [price-per-Mtok]
/router code <name> <model>
```

The secret itself must already be in that environment variable. Multiple
backends using the same HTTP protocol remain separate routing and accounting
identities.

## iOS without a Mac

`sleipnir ios` wraps xtool's cross-platform SwiftPM workflow without invoking a
shell:

```sh
sleipnir ios doctor --project ./MyApp
sleipnir ios setup
sleipnir ios auth login
sleipnir ios build --project ./MyApp
sleipnir ios ipa --project ./MyApp
sleipnir ios run --project ./MyApp -- --usb
```

The build/run actions require `Package.swift` and `xtool.yml`. This is not a
general `.xcodeproj` or `.xcworkspace` runner: native SwiftPM iOS apps are the
supported project shape, while Xcode-only build systems and other mobile
language ecosystems need their own bridge. On Linux, `ios xcodeproj` fails
explicitly because xtool 1.19.0 documents project generation there as a no-op.
A stock SwiftUI fixture has been built through this command to a Mach-O arm64
app on Linux. Signing, install, and launch need Apple authentication and a real
attached iOS device; App Store credential wiring and submission remain
intentionally unconfigured.

## Sparse brain control

`sleipnir orchestrate` runs the DAG normally and spends no extra Claude call
when workers succeed. At a terminal impasse it invokes the configured
reason-tier brain with only the bounded manifest and up to four urgent task
specs (24k characters total). The brain may stop, defer, or propose a typed
revision; Sleipnir validates the full DAG and computes the revision blast radius
locally before persisting anything.

Semantic task/edge proposals require explicit operator review through
`sleipnir apply-revision`; only routing-only retargets auto-apply by default.
Applied proposal files remain as audit artifacts but no longer inflate the
TUI's pending-review badge.
When a semantic revision is approved, superseded tasks and stale descendants
are rerun in dependency order rather than being mistaken for completed work.

The shipped example policy keeps Claude first for `reason`, puts the Codex
subscription first for bulk `code`, and uses OpenRouter first for cheap
`mechanical`/`extract` work. This reserves Claude's tighter window for planning
and control while distributing worker usage across the other two backends.
Codex subscription usage is tracked in its own quota pool. The example's
`@cli-default` sentinel lets the authenticated CLI choose its currently
supported account default; operators can still pin a concrete model id.
Sparse brain calls append their own durable usage/cost record, so the TUI and
budget history include Claude control spend as well as worker spend.

## Security note

`CommandCheck` acceptance checks execute shell commands from `plan.json`. A plan
file is executable content: do not run one from a source you do not trust.
