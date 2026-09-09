import { BarChart3, Blocks, FolderGit2, History, KeyRound, ListChecks, MonitorCog, Save, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";

import type { AppSettings, DashboardSnapshot } from "../domain/types";

const modules = [
  { id: "mission", label: "Mission work queue", detail: "Repository lifecycle and resumable work lanes.", icon: ListChecks },
  { id: "chronicle", label: "Chronicle history", detail: "Append-only event and recovery navigation.", icon: History },
  { id: "helm", label: "Helm system signals", detail: "Budgets, routing, gates, and runtime telemetry.", icon: MonitorCog },
  { id: "tools", label: "Raw tool traces", detail: "Grouped calls, durations, and bounded output metadata.", icon: Blocks },
  { id: "audit", label: "Detailed audit", detail: "Capability use and policy decisions.", icon: ShieldCheck },
] as const;

interface SettingsViewProps {
  snapshot: DashboardSnapshot;
  onSave(settings: AppSettings): Promise<void>;
  onSelectProject(path: string): Promise<void>;
}

export function SettingsView({ snapshot, onSave, onSelectProject }: SettingsViewProps) {
  const [draft, setDraft] = useState(snapshot.settings);
  const [projectPath, setProjectPath] = useState(snapshot.run?.workspace ?? "");
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => setDraft(snapshot.settings), [snapshot.settings]);
  useEffect(() => setProjectPath(snapshot.run?.workspace ?? ""), [snapshot.run?.workspace]);

  const save = async () => {
    try {
      await onSave(draft);
      setMessage("Desktop settings saved on this device.");
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : "Could not save settings");
    }
  };

  const openProject = async () => {
    try {
      await onSelectProject(projectPath);
      setMessage("Project connected.");
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : "Could not open project");
    }
  };

  return (
    <section className="view view--settings">
      <header className="view-head"><div><span className="kicker">Settings · advanced surface</span><h1>Advanced is yours to tune.</h1><p>Choose operational detail, providers, and trust posture without changing Sleipnir’s run truth.</p></div></header>
      <div className="settings-layout">
        <article className="surface settings-card">
          <div className="surface__head"><span className="section-label">Visible modules</span><code>per device</code></div>
          <div className="settings-list">{modules.map(({ id, label, detail, icon: Icon }) => (
            <label key={id}><Icon size={17} /><span><strong>{label}</strong><small>{detail}</small></span><input aria-label={label} type="checkbox" checked={draft.advancedModules[id]} onChange={(event) => setDraft((current) => ({ ...current, advancedModules: { ...current.advancedModules, [id]: event.target.checked } }))} /></label>
          ))}</div>
        </article>

        <div className="settings-stack">
          <section className="surface settings-card compact-settings">
            <div className="surface__head"><span className="section-label">Active project</span><FolderGit2 size={16} /></div>
            <label className="field-label"><span>Project run directory</span><input aria-label="Project run directory" value={projectPath} onChange={(event) => setProjectPath(event.target.value)} /></label>
            <button className="save-action" type="button" onClick={openProject}>Open project</button>
          </section>

          <section className="surface settings-card compact-settings">
            <div className="surface__head"><span className="section-label">Trust posture</span><ShieldCheck size={16} /></div>
            <label className="field-label"><span>Capability approval</span><select aria-label="Capability approval" value={draft.permissionMode} onChange={(event) => setDraft((current) => ({ ...current, permissionMode: event.target.value as AppSettings["permissionMode"] }))}><option value="ask">Ask before every host action</option><option value="always">Always allow in this workspace</option></select></label>
            <label className="inline-toggle"><span><strong>Adaptive color scheme</strong><small>Follow ambient light and system preference.</small></span><input type="checkbox" checked={draft.adaptiveScheme} onChange={(event) => setDraft((current) => ({ ...current, adaptiveScheme: event.target.checked }))} /></label>
          </section>

          <section className="surface settings-card compact-settings">
            <div className="surface__head"><span className="section-label">Provider activation</span><KeyRound size={16} /></div>
            <div className="provider-env-grid">
              <label><span>OpenRouter key variable</span><input aria-label="OpenRouter key variable" value={draft.providerEnv.openrouter} onChange={(event) => setDraft((current) => ({ ...current, providerEnv: { ...current.providerEnv, openrouter: event.target.value } }))} /></label>
              <label><span>Gemini key variable</span><input aria-label="Gemini key variable" value={draft.providerEnv.gemini} onChange={(event) => setDraft((current) => ({ ...current, providerEnv: { ...current.providerEnv, gemini: event.target.value } }))} /></label>
              <label><span>NVIDIA NIM key variable</span><input aria-label="NVIDIA NIM key variable" value={draft.providerEnv.nvidia} onChange={(event) => setDraft((current) => ({ ...current, providerEnv: { ...current.providerEnv, nvidia: event.target.value } }))} /></label>
            </div>
            <p className="settings-note">Names only. Secret values stay in your environment or official provider CLI.</p>
          </section>

          <section className="surface settings-card telemetry-card compact-settings">
            <BarChart3 size={18} /><span className="section-label">Product improvement</span><p>Reliability, coarse feature use, and anonymized acceptance outcomes only—never prompts, code, paths, recordings, or secrets.</p>
            <label className="telemetry-toggle"><span><strong>Share improvement data</strong><small>On by default; inspect or disable anytime.</small></span><input aria-label="Share improvement data" type="checkbox" checked={draft.telemetryEnabled} onChange={(event) => setDraft((current) => ({ ...current, telemetryEnabled: event.target.checked }))} /></label>
          </section>
          <button className="primary-action settings-save" type="button" onClick={save}><Save size={14} /> Save desktop settings</button>
          {message && <p className="form-message" role="status">{message}</p>}
        </div>
      </div>
    </section>
  );
}
