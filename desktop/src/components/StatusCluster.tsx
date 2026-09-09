import { Radio, ShieldCheck } from "lucide-react";

import type { DashboardSnapshot } from "../domain/types";

export function StatusCluster({ snapshot }: { snapshot: DashboardSnapshot }) {
  const running = snapshot.tasks.filter((task) => task.state === "running").length;
  const reviews = snapshot.reviews.length;

  return (
    <div className="status-cluster" aria-label="System status">
      <span className="status-cluster__item">
        <Radio size={14} aria-hidden="true" />
        {running} running
      </span>
      <span className="status-cluster__divider" />
      <span className="status-cluster__item">
        <ShieldCheck size={14} aria-hidden="true" />
        {reviews} decision
      </span>
      <span className="status-cluster__divider" />
      <span className="status-cluster__item">window {snapshot.budgets[0]?.used ?? 0}%</span>
    </div>
  );
}
