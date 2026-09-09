import { ArrowRight, CircleDollarSign, Gauge, Route } from "lucide-react";

import type { BudgetPool, DashboardSnapshot } from "../domain/types";

function budgetValue(pool: BudgetPool) {
  const value = pool.unit === "USD" ? `$${pool.used.toFixed(2)}` : `${pool.used.toLocaleString()}${pool.unit === "%" ? "%" : ""}`;
  return pool.limit === null ? value : `${value} / ${pool.limit}${pool.unit === "%" ? "%" : ""}`;
}

export function RoutingView({ snapshot }: { snapshot: DashboardSnapshot }) {
  return (
    <section className="view view--routing">
      <header className="view-head"><div><span className="kicker">Helm · provider and budget control</span><h1>Every route, explained.</h1><p>Model choice, quota pressure, fixed dispatch cost, and fallback remain separate and inspectable.</p></div></header>
      <div className="budget-grid">
        {snapshot.budgets.map((pool) => {
          const percent = pool.limit ? Math.min(100, (pool.used / pool.limit) * 100) : 18;
          return <article className="surface budget-tile" key={pool.id}><span className="section-label">{pool.kind}</span><h2>{budgetValue(pool)}</h2><p>{pool.label}</p><div className="progress-track"><i style={{ width: `${percent}%` }} /></div></article>;
        })}
      </div>
      <article className="surface routes-table">
        <div className="route-head"><span>Task</span><span>Provider / model</span><span>Cost</span><span>State</span></div>
        {snapshot.routes.map((route) => (
          <div className="route-row" key={`${route.taskId}-${route.provider}`}>
            <span><Route size={15} /><code>{route.taskId}</code><small>{route.tier}</small></span>
            <span><strong>{route.provider}</strong><ArrowRight size={13} /><code>{route.model}</code></span>
            <span><CircleDollarSign size={14} />{route.costLabel}</span>
            <span data-route-state={route.status}>{route.status}</span>
            <p><Gauge size={14} />{route.rationale}</p>
          </div>
        ))}
      </article>
    </section>
  );
}
