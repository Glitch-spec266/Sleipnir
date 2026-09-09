import { BarChart3, Blocks, History, ListChecks, MonitorCog, ShieldCheck } from "lucide-react";
import { useState } from "react";

const modules = [
  { id: "mission", label: "Mission work queue", detail: "Repository lifecycle and resumable work lanes.", icon: ListChecks },
  { id: "chronicle", label: "Chronicle history", detail: "Append-only event and recovery navigation.", icon: History },
  { id: "helm", label: "Helm system signals", detail: "Budgets, routing, gates, and runtime telemetry.", icon: MonitorCog },
  { id: "tools", label: "Raw tool traces", detail: "Grouped calls, durations, and bounded output metadata.", icon: Blocks },
  { id: "audit", label: "Detailed audit", detail: "Capability use and policy decisions.", icon: ShieldCheck },
] as const;

export function SettingsView() {
  const [enabled, setEnabled] = useState<Record<string, boolean>>(() => Object.fromEntries(modules.map((module) => [module.id, true])));
  const [telemetry, setTelemetry] = useState(true);

  return (
    <section className="view view--settings">
      <header className="view-head"><div><span className="kicker">Settings · advanced surface</span><h1>Advanced is yours to tune.</h1><p>Choose the operational detail you want without changing how Sleipnir executes the run.</p></div></header>
      <div className="settings-layout">
        <article className="surface settings-card"><div className="surface__head"><span className="section-label">Visible modules</span><code>per device</code></div><div className="settings-list">{modules.map(({ id, label, detail, icon: Icon }) => <label key={id}><Icon size={17} /><span><strong>{label}</strong><small>{detail}</small></span><input aria-label={label} type="checkbox" checked={enabled[id]} onChange={(event) => setEnabled((current) => ({ ...current, [id]: event.target.checked }))} /></label>)}</div></article>
        <aside className="surface settings-card telemetry-card"><BarChart3 size={21} /><span className="section-label">Product improvement</span><h2>Minimal telemetry</h2><p>Coarse feature use, reliability, performance, and anonymized acceptance outcomes only. Never prompts, code, content, paths, recordings, or secrets.</p><label className="telemetry-toggle"><span><strong>Share improvement data</strong><small>You can inspect queued events before they leave.</small></span><input aria-label="Share improvement data" type="checkbox" checked={telemetry} onChange={(event) => setTelemetry(event.target.checked)} /></label></aside>
      </div>
    </section>
  );
}
