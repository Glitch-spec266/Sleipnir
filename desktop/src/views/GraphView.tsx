import { Check, Clock3, GitBranch, LoaderCircle, ShieldAlert } from "lucide-react";
import { useMemo, useState } from "react";

import type { DashboardSnapshot, TaskState, TaskSummary } from "../domain/types";

const stateIcon: Record<TaskState, typeof Check> = {
  pending: Clock3,
  ready: GitBranch,
  running: LoaderCircle,
  review: ShieldAlert,
  done: Check,
  failed: ShieldAlert,
  blocked: ShieldAlert,
  skipped: Clock3,
  partial: ShieldAlert,
  stale: Clock3,
  superseded: Clock3,
  cancelled: ShieldAlert,
};

export function GraphView({ snapshot }: { snapshot: DashboardSnapshot }) {
  const initial = snapshot.tasks.find((task) => task.state === "running") ?? snapshot.tasks[0];
  const [selectedId, setSelectedId] = useState(initial?.id ?? "");
  const selected = useMemo(
    () => snapshot.tasks.find((task) => task.id === selectedId) ?? initial,
    [initial, selectedId, snapshot.tasks],
  );

  return (
    <section className="view view--run">
      <header className="view-head">
        <div><span className="kicker">Run graph · derived state</span><h1>The run, at a glance.</h1><p>Dependencies, work lanes, and the next decision—folded from the append-only record.</p></div>
        <div className="run-health"><strong>{snapshot.run?.progress ?? 0}%</strong><span>revision {snapshot.run?.revision ?? 0} · {snapshot.run?.state}</span></div>
      </header>
      <div className="graph-layout">
        <article className="surface graph-canvas">
          <div className="graph-orbits" aria-hidden="true"><i /><i /><i /></div>
          <div className="graph-nodes">
            {snapshot.tasks.map((task) => {
              const Icon = stateIcon[task.state];
              return (
                <button
                  key={task.id}
                  type="button"
                  className={`task-node task-node--${task.state}`}
                  aria-pressed={selected?.id === task.id}
                  aria-label={`${task.id} · ${task.title}`}
                  onClick={() => setSelectedId(task.id)}
                >
                  <span className="task-node__top"><code>{task.id}</code><Icon size={14} aria-hidden="true" /></span>
                  <strong>{task.title}</strong>
                  <span>{task.tier} · {task.state}</span>
                </button>
              );
            })}
          </div>
        </article>
        {selected && <TaskInspector task={selected} />}
      </div>
    </section>
  );
}

function TaskInspector({ task }: { task: TaskSummary }) {
  return (
    <aside className="surface inspector">
      <span className="section-label">Selected lane</span>
      <code className="inspector__id">{task.id} · {task.group}</code>
      <h2>{task.title}</h2>
      <p>{task.summary}</p>
      <dl>
        <div><dt>Status</dt><dd>{task.state}</dd></div>
        <div><dt>Tier</dt><dd>{task.tier}</dd></div>
        <div><dt>Attempt</dt><dd>{task.attempt} / {task.maxAttempts}</dd></div>
        <div><dt>Model</dt><dd>{task.model ?? "not routed"}</dd></div>
      </dl>
      <div className="inspector__checks">
        <span className="section-label">Acceptance</span>
        {task.checks.map((check) => <span key={check}><Check size={13} aria-hidden="true" />{check}</span>)}
      </div>
      <p className="boundary-note">Paths and bounded summaries only. Worker output stays outside the control context.</p>
    </aside>
  );
}
