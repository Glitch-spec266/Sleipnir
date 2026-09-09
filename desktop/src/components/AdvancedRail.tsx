import { Activity, CircleDollarSign, ListChecks, ShieldCheck } from "lucide-react";

import type { DashboardSnapshot } from "../domain/types";

export function AdvancedRail({ snapshot }: { snapshot: DashboardSnapshot }) {
  const activeTasks = snapshot.tasks.filter((task) => !["done", "skipped"].includes(task.state));
  const window = snapshot.budgets.find((budget) => budget.kind === "window");
  const selectedRoute = snapshot.routes.find((route) => route.status === "selected");

  return (
    <aside className="advanced-rail" aria-label="Advanced run context">
      {snapshot.settings.advancedModules.mission && <section>
        <div className="rail-section-head"><span><ListChecks size={14} />Mission queue</span><code>{activeTasks.length}</code></div>
        <div className="mission-list">
          {activeTasks.map((task) => (
            <div className={`mission-item mission-item--${task.state}`} key={task.id}>
              <span>{task.title}</span>
              <small>{task.id} · {task.group}</small>
              <i><b style={{ width: `${task.progress}%` }} /></i>
            </div>
          ))}
        </div>
      </section>}
      {snapshot.settings.advancedModules.helm && <section className="rail-signals">
        <div className="rail-section-head"><span><Activity size={14} />Helm signals</span><code>nominal</code></div>
        <div className="signal-row"><span><CircleDollarSign size={13} />Window</span><code>{window?.used ?? 0}{window?.unit}</code></div>
        <div className="signal-row"><span><ShieldCheck size={13} />Audit</span><code>armed</code></div>
        <div className="signal-row"><span>Route</span><code>{selectedRoute?.provider ?? "idle"}</code></div>
      </section>}
    </aside>
  );
}
