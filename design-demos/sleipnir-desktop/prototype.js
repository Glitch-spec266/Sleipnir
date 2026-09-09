const directions = [
  { id: "relay", file: "01-relay", n: "01", name: "Relay", note: "Agent command center with a quiet project rail and a focused glass work surface.", anchor: "Huashu roulette 13 · Codex-style command center" },
  { id: "atelier", file: "02-atelier", n: "02", name: "Atelier", note: "Conversation-first workspace with warm editorial material and a persistent working notebook.", anchor: "Claude Code Desktop · pane-based collaboration" },
  { id: "vector", file: "03-vector", n: "03", name: "Vector", note: "Editor-first layout that ties agent activity directly to files, diffs, and terminal state.", anchor: "Cursor Agents Window · IDE depth" },
  { id: "orbit", file: "04-orbit", n: "04", name: "Orbit", note: "Graph-first spatial control where eight parallel lanes converge around one protected context.", anchor: "Antigravity · multi-agent spatial supervision" },
  { id: "current", file: "05-current", n: "05", name: "Current", note: "Terminal-native industrial surface with command bands, hard edges, and legible execution state.", anchor: "Warp · terminal as agent environment" },
  { id: "index", file: "06-index", n: "06", name: "Index", note: "Fast, low-chrome thread and file index for operators who prefer precision over ceremony.", anchor: "Zed · thread sidebar and agent panel" },
  { id: "mission", file: "07-mission", n: "07", name: "Mission", note: "A repository work queue that carries tasks cleanly from request through review and merge.", anchor: "GitHub Agents · work-item lifecycle" },
  { id: "glasshouse", file: "08-glasshouse", n: "08", name: "Glasshouse", note: "Luminous light-mode desktop material with floating navigation and a soft live inspector.", anchor: "Native desktop · liquid glass, restrained" },
  { id: "chronicle", file: "09-chronicle", n: "09", name: "Chronicle", note: "Append-only history and recovery become the primary way to understand an autonomous run.", anchor: "Sleipnir-native · provenance first" },
  { id: "helm", file: "10-helm", n: "10", name: "Helm", note: "Dense safety-critical console joining graph, budget, providers, gates, and operator decisions.", anchor: "Custom studio · air traffic control × industrial tools" }
];

const pages = [
  { id: "command", label: "Command", glyph: "⌘" },
  { id: "graph", label: "Run graph", glyph: "08" },
  { id: "console", label: "Console", glyph: ">_" },
  { id: "review", label: "Review", glyph: "±" },
  { id: "routing", label: "Routing", glyph: "$" },
  { id: "trust", label: "Trust", glyph: "◎" }
];

const sampleTasks = [
  ["t014", "Audit capability boundary", "done", "reason"],
  ["t015", "Stage dependency inputs", "done", "code"],
  ["t016", "Verify browser control", "done", "code"],
  ["t017", "Harden outage failover", "run", "reason"],
  ["t018", "Build iOS capability", "done", "longctx"],
  ["t019", "Test party join path", "done", "code"],
  ["t020", "Sign on physical device", "wait", "reason"],
  ["gate", "Operator phase gate", "review", "control"]
];

function mark(assetRoot, compact = false) {
  return compact
    ? `<span class="mark-only"><img src="${assetRoot}/sleipnir-mark.svg" alt=""></span>`
    : `<span class="brand-lockup"><img src="${assetRoot}/sleipnir-mark.svg" alt=""><span><strong>SLEIPNIR</strong><small>eight-lane orchestration</small></span></span>`;
}

function nav(active) {
  return pages.map((page) => `<button class="nav-item ${active === page.id ? "active" : ""}" data-page="${page.id}" aria-current="${active === page.id ? "page" : "false"}"><span class="nav-glyph">${page.glyph}</span><span class="nav-text">${page.label}</span></button>`).join("");
}

function pageHead(eyebrow, title, copy, actions = true) {
  return `<header class="page-head">
    <div><div class="eyebrow">${eyebrow}</div><h1>${title}</h1><p>${copy}</p></div>
    ${actions ? `<div class="head-actions"><span class="pill live"><i class="presence-dot"></i> local · live</span><button class="button small" data-toast="Prototype action only">•••</button></div>` : ""}
  </header>`;
}

function commandPage() {
  const lanes = sampleTasks.map((task, i) => {
    const progress = task[2] === "done" ? 100 : task[2] === "run" ? 63 : task[2] === "review" ? 82 : 8;
    return `<div class="lane"><b>${task[0]} · ${task[1]}</b><span><i style="--p:${progress}%"></i></span><small>${task[3]} / ${task[2]}</small></div>`;
  }).join("");
  return `${pageHead("Command · Phase 20 shipped", "What should the system move next?", "Start from intent. Sleipnir turns it into a validated plan, routes each lane, and brings back only the bounded state needed for the next decision.")}
  <section class="command-grid">
    <article class="glass-card briefing">
      <span class="section-label">New instruction</span>
      <h2>Finish the remaining device gates, then prepare a release candidate.</h2>
      <p>One cross-network party test and one signed iPhone install are still blocked on hardware. Everything else can proceed without reopening completed work.</p>
      <div class="prompt-box" role="textbox" tabindex="0" aria-label="Task prompt">
        <span>Describe an outcome, attach a plan, or use <code>/project</code> to decompose a larger goal…</span>
        <div class="prompt-row"><div class="prompt-meta"><span class="pill">@ sleipnir</span><span class="pill">Auto route</span><span class="pill">Review gates</span></div><button class="button primary small" data-toast="Task creation is simulated">Plan task</button></div>
      </div>
    </article>
    <aside class="glass-card status-panel">
      <span class="section-label">Sample run · phase-20</span>
      <div class="status-ring"><strong>72%</strong><small>complete</small></div>
      <div class="status-list"><div class="status-row"><span>Ready</span><code>1</code></div><div class="status-row"><span>Running</span><code>1</code></div><div class="status-row"><span>Needs operator</span><code>1</code></div><div class="status-row"><span>Hardware blocked</span><code>2</code></div></div>
    </aside>
    <article class="glass-card lane-strip"><div class="lane-head"><span class="section-label">Eight active lanes</span><span class="pill">manifest 2.7k tokens</span></div><div class="lanes">${lanes}</div></article>
  </section>`;
}

function graphPage() {
  const nodes = sampleTasks.map((task, i) => `<button class="node ${task[2] === "wait" ? "wait" : task[2] === "review" ? "review" : ""} ${i === 3 ? "selected" : ""}" data-task="${task[0]}" type="button"><small>${task[0]} · ${task[3]}</small><b>${task[1]}</b><span class="node-meta"><i class="node-dot"></i>${task[2]}</span></button>`).join("");
  return `${pageHead("Run graph · derived state", "See the dependency shape, not a wall of logs.", "Status is folded from the append-only run log. Selecting a node reveals its contract and route without exposing worker output to the control context.")}
  <section class="graph-wrap">
    <article class="glass-card dag-canvas"><div class="dag-toolbar"><span class="section-label">phase-20 / revision 4</span><div><span class="pill">8 visible</span> <span class="pill live">1 running</span></div></div><div class="dag">${nodes}</div></article>
    <aside class="glass-card inspect"><span class="section-label">Selected task</span><h3 id="selected-task-title">t017 · Harden outage failover</h3><p id="selected-task-copy">Routing-preserving retry across a provider outage without reopening completed work.</p><dl><dt>Status</dt><dd id="selected-task-state">RUNNING</dd><dt>Tier</dt><dd>reason</dd><dt>Attempt</dt><dd>02 / 03</dd><dt>Input</dt><dd>summaries only</dd><dt>Workspace</dt><dd>attempt-02/</dd><dt>Gate</dt><dd>pytest + review</dd></dl><div class="inspect-note">Artifact contents stay in the worker workspace. This surface receives paths and bounded summaries only.</div></aside>
  </section>`;
}

function consolePage() {
  return `${pageHead("Console · sparse control", "Talk to the orchestrator without flooding its context.", "The console renders and routes. Tool traces stay grouped, decisions stay explicit, and the scarce brain wakes only when automatic execution reaches an impasse.")}
  <section class="console-layout">
    <article class="glass-card transcript"><div class="transcript-bar"><span class="section-label">phase-20 / control cycle 03</span><span class="pill live">streaming</span></div><div class="messages">
      <div class="message user"><div class="message-label">Operator</div><p>Finish every safe task. Stop before either hardware gate and show me the exact evidence needed.</p></div>
      <div class="message agent"><div class="message-label">Sleipnir control</div><p>Six lanes are complete. One routing task remains safe to run. Two gates require external hardware and will remain blocked without consuming another attempt.</p></div>
      <div class="tool-group"><div class="tool-line"><code>read_plan</code><span>group=phase-20 · 4 frontier tasks</span><small>18 ms</small></div><div class="tool-line"><code>projection</code><span>folded 42 terminal records</span><small>offline</small></div><div class="tool-line"><code>router</code><span>reason → subscription/cli-default</span><small>allowed</small></div></div>
      <div class="message agent"><div class="message-label">Decision</div><p>Continue with <code>t017</code>. Preserve <code>t020</code> as hardware-blocked. No semantic plan revision proposed.</p></div>
    </div><div class="composer"><p>Steer the run, ask for rationale, or queue a reviewed plan change…</p><div class="prompt-row"><span class="pill">Auto accept: off</span><button class="button primary small" data-toast="Message sending is simulated">Send</button></div></div></article>
    <aside class="context-panel"><article class="glass-card context-card"><span class="section-label">Bounded manifest</span><h3>2,696 tokens</h3><p>12 frontier · 16 evidence · 10 groups</p><div class="manifest-bar"><i></i></div><p>0.6% growth from 60 to 10,000 tasks</p></article><article class="glass-card context-card"><span class="section-label">Current route</span><h3>reason / cli-default</h3><p>Subscription lane · second viable candidate on retry</p></article><article class="glass-card decision"><span class="section-label">Operator decision</span><h3>2 gates paused</h3><p>Second physical host and signed iPhone install.</p><button class="button small" data-toast="Gate review is simulated">Review gates</button></article></aside>
  </section>`;
}

function reviewPage() {
  const lines = [
    ["", "", "def resolve(self, task, *, attempt=1):"],
    ["del", "−", "    return viable[0]"],
    ["add", "+", "    index = min(attempt - 1, len(viable) - 1)"],
    ["add", "+", "    selected = viable[index]"],
    ["", "", "    return RoutingDecision("],
    ["", "", "        model=selected.model,"],
    ["add", "+", "        rationale=explain_all(candidates, selected),"],
    ["", "", "    )"],
    ["", "", ""],
    ["", "", "def test_retry_uses_next_viable_candidate():"],
    ["add", "+", "    assert resolve(task, attempt=2).model == SECOND"],
    ["add", "+", "    assert 'first viable rate-limited' in rationale"]
  ];
  return `${pageHead("Review · attempt-02", "Inspect what landed on disk.", "Review the exact diff, acceptance checks, and provider evidence. Success is decided by output contracts—not by what the agent said it completed.")}
  <section class="glass-card review-layout"><aside class="file-list"><h3>6 changed files</h3><div class="file-row active"><span>router.py</span><span class="delta">+4 −1</span></div><div class="file-row"><span>budget.py</span><span class="delta">+8 −2</span></div><div class="file-row"><span>executor.py</span><span class="delta">+3</span></div><div class="file-row"><span>test_router.py</span><span class="delta">+12</span></div><div class="file-row"><span>test_budget.py</span><span class="delta">+6</span></div><div class="file-row"><span>DESIGN.md</span><span class="delta">+9</span></div></aside><div class="diff"><div class="diff-head"><strong>src/sleipnir/router.py</strong><div><span class="pill live">checks passed</span> <button class="button small" data-toast="Comment mode is simulated">Add comment</button></div></div><div class="code">${lines.map(l => `<div class="code-line ${l[0]}"><span class="sign">${l[1]}</span><span>${l[2] || "&nbsp;"}</span></div>`).join("")}</div><div class="review-actions"><button class="button small" data-toast="Rejection is simulated">Request changes</button><div><button class="button quiet small" data-toast="Editor handoff is simulated">Open in editor</button><button class="button primary small" data-toast="Approval is simulated">Approve attempt</button></div></div></div></section>`;
}

function routingPage() {
  const routes = [
    ["fast", "claude / cli-default", "subscription", "allowed", true],
    ["code", "codex / account-default", "subscription", "allowed", true],
    ["reason", "claude / cli-default", "subscription", "selected", true],
    ["longctx", "openrouter / configured", "metered", "standby", true],
    ["control", "claude / cli-default", "subscription", "scarce", true],
    ["vision", "nvidia / configured", "metered", "offline", false]
  ];
  return `${pageHead("Routing · live catalogue", "Cost, capability, and window pressure stay separate.", "Every candidate remains explainable. Prices arrive as data, capability claims come from operator config, and retries advance to the next viable route.")}
  <section class="routing-layout"><article class="glass-card route-table"><div class="route-head"><span>Tier</span><span>Route</span><span>Billing</span><span>State</span><span></span></div>${routes.map(r => `<div class="route-row"><b>${r[0]}</b><code>${r[1]}</code><span>${r[2]}</span><span class="pill ${r[3] === "selected" ? "live" : ""}">${r[3]}</span><i class="route-state ${r[4] ? "" : "off"}"></i></div>`).join("")}</article><aside class="glass-card budget-card"><span class="section-label">Sample five-hour window</span><h2>34%</h2><p>Observed utilization · cached 42s ago</p><div class="budget-scale"><i></i></div><div class="budget-ticks"><span>0</span><span>downshift 70</span><span>stop 95</span></div><div class="cost-lines"><div class="cost-line"><span>Window burn</span><code>18.4% / hr</code></div><div class="cost-line"><span>Metered spend</span><code>$0.00</code></div><div class="cost-line"><span>Notional</span><code>$12.84</code></div><div class="cost-line"><span>Cache weight</span><code>1.0×</code></div></div></aside><article class="glass-card explain"><span class="section-label">Why reason picked this route</span><div class="explain-line"><code>claude/default</code><span class="pill live">selected</span><span>Configured for reason tier; subscription window available; first viable candidate.</span></div><div class="explain-line"><code>codex/default</code><span class="pill">accepted</span><span>Capable, but ranked second by configured preference for this tier.</span></div><div class="explain-line"><code>openrouter/x</code><span class="pill bad">rejected</span><span>Missing current price in catalogue snapshot; unknown is never treated as free.</span></div></article></section>`;
}

function trustPage() {
  const caps = [["Browser", "Headed Chromium · audited"],["Keyboard", "Character count only"],["Credentials", "Session memory · wipe on consume"],["Sudo", "Protected askpass agent"],["iOS", "SwiftPM arm64 build lane"],["Party", "AES-GCM + Ed25519"]];
  return `${pageHead("Trust · operator lane", "Power is visible, scoped, and recorded.", "Capabilities never enter worker prompts. Every privileged action is audited at the boundary, while secrets remain non-renderable and outside durable run state.")}
  <section class="trust-grid"><article class="glass-card capability-card"><span class="section-label">Capabilities</span><div class="capability-list">${caps.map(c => `<div class="capability"><b>${c[0]}<i></i></b><p>${c[1]}</p></div>`).join("")}</div></article><article class="glass-card audit-card"><span class="section-label">Recent audit</span><div class="audit-list"><div class="audit-row"><span>12:17:32</span><b>askpass.served</b><span>source=agent</span></div><div class="audit-row"><span>12:17:28</span><b>credential.cached</b><span>label=sudo</span></div><div class="audit-row"><span>12:16:09</span><b>browser.click</b><span>button=left</span></div><div class="audit-row"><span>12:15:54</span><b>keyboard.type</b><span>chars=24</span></div><div class="audit-row"><span>12:14:41</span><b>party.verify</b><span>signature=valid</span></div></div></article><article class="glass-card party-card"><div><span class="section-label">Encrypted party · phase-20</span><h2>Collaborate across machines without sharing trust blindly.</h2><p>Join codes stay out of argv and transcripts. Creator signatures pin leader-only mode changes and assignments.</p></div><div class="party-peers"><div class="peer"><span><b>cachyos-workstation</b><br><small>LEADER · LOCAL</small></span><span class="pill live">online</span></div><div class="peer"><span><b>loopback-member</b><br><small>MEMBER · VERIFIED</small></span><span class="pill">idle</span></div><div class="peer"><span><b>physical-host-02</b><br><small>HARDWARE GATE</small></span><span class="pill warn">waiting</span></div></div></article></section>`;
}

function renderPage(page) {
  return ({ command: commandPage, graph: graphPage, console: consolePage, review: reviewPage, routing: routingPage, trust: trustPage }[page] || commandPage)();
}

function sideNote(direction) {
  return `<span class="section-label">${direction.n} · ${direction.name}</span><h2>phase-20</h2><p>${direction.note}</p><div class="thread-note"><b>Current thread</b><small>Harden outage failover · running</small></div><div class="thread-note"><b>Branch</b><small>main · clean</small></div><div class="thread-note"><b>Environment</b><small>local · CachyOS</small></div>`;
}

function renderShell(direction, active, assetRoot) {
  const stage = `<main class="page-stage" id="page-stage">${renderPage(active)}</main>`;
  if (direction.id === "relay") return `<div class="shell-relay"><aside class="relay-rail">${mark(assetRoot)}<nav class="nav-stack">${nav(active)}</nav><div class="rail-footer"><div class="presence"><i class="presence-dot"></i><span>1 lane running</span></div></div></aside><section class="relay-main">${stage}</section></div>`;
  if (direction.id === "atelier") return `<div class="shell-atelier"><header class="atelier-top">${mark(assetRoot)}<nav class="atelier-tabs">${nav(active)}</nav><span class="pill live" style="margin-left:auto">session isolated</span></header><div class="atelier-work"><aside class="atelier-notebook">${sideNote(direction)}</aside><section>${stage}</section></div></div>`;
  if (direction.id === "vector") return `<div class="shell-vector"><nav class="vector-activity">${mark(assetRoot,true)}${nav(active)}</nav><aside class="vector-explorer"><div class="explorer-title">Explorer · sleipnir</div><div class="tree"><b>⌄ src/sleipnir</b><span>adapters/</span><span>capabilities/</span><span class="deep">agent.py</span><span class="deep">browser.py</span><span>budget.py</span><span>executor.py</span><span>orchestrator.py</span><span>router.py</span><span>tui.py</span><b>⌄ run / phase-20</b><span>plan.json</span><span>results.jsonl</span><span>revisions.jsonl</span></div></aside><section class="vector-stage">${stage}</section><aside class="vector-agent"><div class="agent-head"><b>Agent</b><span class="pill live">running</span></div><div class="agent-feed"><span class="section-label">Control thread</span><b>Plan understood</b><span>Reading bounded manifest and frontier task specifications.</span><b>3 tools grouped</b><span>projection · router · pytest</span><b>Next</b><span>Verify retry chooses the next viable provider.</span></div><div class="agent-compose">Steer agent… <span style="float:right;color:var(--accent)">↵</span></div></aside></div>`;
  if (direction.id === "orbit") return `<div class="shell-orbit"><header class="orbit-top"><div class="orbit-brand">${mark(assetRoot)}</div><div class="orbit-state"><span class="pill live">phase-20 · 1 running</span> <span class="pill">window 34%</span></div></header><section class="orbit-stage">${stage}</section><nav class="orbit-nav">${nav(active)}</nav></div>`;
  if (direction.id === "current") return `<div class="shell-current"><header class="current-head">${mark(assetRoot)}<div class="current-prompt"><b>sleipnir</b><span>phase-20 / status --watch</span><span style="margin-left:auto;color:var(--accent)">LIVE</span></div><span class="pill">main · clean</span></header><nav class="current-nav">${nav(active)}</nav><section>${stage}</section></div>`;
  if (direction.id === "index") return `<div class="shell-index"><aside class="index-projects">${mark(assetRoot)}<div class="project-switcher"><b>sleipnir</b><small>/Projects/sleipnir</small></div><span class="section-label">Threads</span><div class="queue-item active"><b>Phase 20 verification</b><small>running · reason</small></div><div class="queue-item"><b>Desktop exploration</b><small>local · design</small></div><div class="queue-item"><b>Brand cleanup</b><small>paused</small></div><div class="rail-footer"><div class="presence"><i class="presence-dot"></i>local agent online</div></div></aside><nav class="index-pages"><div class="explorer-title">Views</div>${nav(active)}</nav><section class="index-stage">${stage}</section></div>`;
  if (direction.id === "mission") return `<div class="shell-mission"><header class="mission-top">${mark(assetRoot)}<nav class="mission-tabs">${nav(active)}</nav><button class="button primary small" data-toast="New task is simulated">New task</button></header><div class="mission-work"><aside class="mission-queue"><div class="queue-head"><span class="section-label">My work · 3</span><span class="pill">filter</span></div><div class="queue-item active"><b>Harden outage failover</b><small>phase-20 · t017</small><div class="queue-state"><i class="presence-dot"></i>running locally</div></div><div class="queue-item"><b>Sign iOS device build</b><small>phase-20 · t020</small><div class="queue-state"><span class="pill warn">hardware blocked</span></div></div><div class="queue-item"><b>Cross-network party</b><small>phase-20 · gate</small><div class="queue-state"><span class="pill warn">needs host</span></div></div></aside><section class="mission-stage">${stage}</section></div></div>`;
  if (direction.id === "glasshouse") return `<div class="shell-glasshouse"><nav class="glass-dock">${mark(assetRoot,true)}${nav(active)}</nav><section class="glass-stage">${stage}</section><aside class="glass-inspector"><span class="section-label">Live run</span><h3>Phase 20</h3><p>One safe lane continues. Two remain paused at explicit hardware gates.</p><div class="status-ring"><strong>72%</strong><small>complete</small></div><div class="status-list"><div class="status-row"><span>Window</span><code>34%</code></div><div class="status-row"><span>Notional</span><code>$12.84</code></div><div class="status-row"><span>Manifest</span><code>2.7k</code></div></div></aside></div>`;
  if (direction.id === "chronicle") return `<div class="shell-chronicle"><aside class="chronicle-rail">${mark(assetRoot)}<h2 class="chronicle-title">Run chronicle</h2><div class="history-line live"><b>Attempt 02 started</b><small>12:27:19 · t017</small></div><div class="history-line"><b>Party gate verified</b><small>12:20:23 · evidence</small></div><div class="history-line"><b>Sudo cache proven</b><small>12:17:51 · audit</small></div><div class="history-line"><b>Revision 4 applied</b><small>11:52:08 · routing only</small></div><nav class="chronicle-nav">${nav(active)}</nav></aside><section class="chronicle-stage">${stage}</section></div>`;
  return `<div class="shell-helm"><header class="helm-status"><div class="helm-brand">${mark(assetRoot,true)}<strong>SLEIPNIR</strong></div><div class="helm-readout"><small>run state</small><b><span>RUNNING</span> 01/08</b></div><div class="helm-readout"><small>window</small><b>34.0%</b></div><div class="helm-readout"><small>manifest</small><b>2,696 tkn</b></div><div class="helm-readout"><small>revision</small><b>04 · clean</b></div><div class="helm-clock">LOCAL / 12:29:45<br>MAIN · CLEAN</div></header><div class="helm-body"><nav class="helm-nav">${nav(active)}</nav><section class="helm-stage">${stage}</section><aside class="helm-inspector"><span class="section-label">System signals</span><h3>ALL NOMINAL</h3><p>One route active. No plan corruption, secret exposure, or budget refusal detected.</p><div class="signal"><div class="signal-head"><span>WINDOW</span><span>34%</span></div><div class="signal-bar"><i style="--p:34%"></i></div></div><div class="signal"><div class="signal-head"><span>FRONTIER</span><span>8/12</span></div><div class="signal-bar"><i style="--p:67%"></i></div></div><div class="signal"><div class="signal-head"><span>EVIDENCE</span><span>16/16</span></div><div class="signal-bar"><i style="--p:100%"></i></div></div><div class="inspect-note">CONTROL BOUNDARY<br>Paths + bounded summaries only. Artifact content remains outside this context.</div></aside></div></div>`;
}

function renderApp() {
  const root = document.getElementById("app");
  if (!root) return;
  const id = document.body.dataset.direction;
  const direction = directions.find((item) => item.id === id) || directions[0];
  const assetRoot = document.body.dataset.assetRoot || "../../../assets";
  let active = location.hash.replace("#", "") || "command";
  if (!pages.some((page) => page.id === active)) active = "command";
  root.innerHTML = `<div class="app-window"><div class="window-bar"><span class="traffic"><i></i><i></i><i></i></span><span class="window-title">Sleipnir · ${direction.name} · ${pages.find(p => p.id === active).label}</span><span class="sample-label">selection prototype</span></div><div class="app-body">${renderShell(direction, active, assetRoot)}</div><div id="toast" role="status" aria-live="polite"></div></div>`;
  bindApp(direction, active, assetRoot);
}

function bindApp(direction, active, assetRoot) {
  document.querySelectorAll("[data-page]").forEach((button) => button.addEventListener("click", () => {
    const page = button.dataset.page;
    history.replaceState(null, "", `#${page}`);
    const body = document.querySelector(".app-body");
    body.innerHTML = renderShell(direction, page, assetRoot);
    document.querySelector(".window-title").textContent = `Sleipnir · ${direction.name} · ${pages.find(p => p.id === page).label}`;
    bindApp(direction, page, assetRoot);
  }));
  document.querySelectorAll("[data-toast]").forEach((button) => button.addEventListener("click", () => showToast(button.dataset.toast)));
  document.querySelectorAll("[data-task]").forEach((node) => node.addEventListener("click", () => {
    document.querySelectorAll("[data-task]").forEach(n => n.classList.remove("selected"));
    node.classList.add("selected");
    const task = sampleTasks.find(t => t[0] === node.dataset.task);
    const title = document.getElementById("selected-task-title");
    const state = document.getElementById("selected-task-state");
    if (title) title.textContent = `${task[0]} · ${task[1]}`;
    if (state) state.textContent = task[2].toUpperCase();
  }));
}

function showToast(copy) {
  let toast = document.getElementById("toast");
  if (!toast) return;
  toast.textContent = copy;
  Object.assign(toast.style, { position: "fixed", right: "22px", bottom: "22px", zIndex: 100, padding: "10px 13px", borderRadius: "9px", background: "var(--panel-strong)", border: "1px solid var(--line-hi)", color: "var(--text)", boxShadow: "var(--shadow)", opacity: 1, transition: "opacity .2s ease" });
  clearTimeout(window.__sleipnirToastTimer);
  window.__sleipnirToastTimer = setTimeout(() => { toast.style.opacity = 0; }, 1300);
}

function renderGallery() {
  const gallery = document.getElementById("gallery");
  if (!gallery) return;
  gallery.innerHTML = directions.map((d) => `<a class="concept-card" href="directions/${d.file}.html"><div class="concept-shot"><img src="screenshots/${d.file}.png" alt="${d.name} direction preview"></div><div class="concept-meta"><span class="concept-number">${d.n}</span><div><h2>${d.name}</h2><p>${d.note}</p><p class="section-label" style="margin-top:9px">${d.anchor}</p></div><span class="concept-pages">6 pages<br>interactive</span></div></a>`).join("");
}

window.addEventListener("hashchange", renderApp);
renderGallery();
renderApp();
