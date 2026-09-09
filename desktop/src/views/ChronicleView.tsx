import { History, RotateCcw } from "lucide-react";

import type { DashboardSnapshot } from "../domain/types";

export function ChronicleView({ snapshot }: { snapshot: DashboardSnapshot }) {
  return (
    <section className="view view--chronicle">
      <header className="view-head"><div><span className="kicker">Chronicle · append-only provenance</span><h1>Everything that happened.</h1><p>Understand, recover, and continue work without depending on a model's memory of the session.</p></div><button className="button" type="button"><RotateCcw size={15} />Recovery preview</button></header>
      <div className="chronicle-layout">
        <article className="surface timeline">
          {snapshot.timeline.map((event, index) => (
            <div className={`timeline-event timeline-event--${event.tone}`} key={event.id}>
              <div className="timeline-spine"><i />{index < snapshot.timeline.length - 1 && <span />}</div>
              <div><small>{new Date(event.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} · {event.kind.replaceAll("_", " ")}</small><h2>{event.title}</h2><p>{event.detail}</p></div>
              {event.taskId && <code>{event.taskId}</code>}
            </div>
          ))}
        </article>
        <aside className="surface recovery-card"><History size={22} /><span className="section-label">Recovery invariant</span><h2>No hidden checkpoint.</h2><p>Status is rebuilt by folding the plan and append-only records. A crash does not require a repair ritual.</p><dl><div><dt>Revision</dt><dd>{snapshot.run?.revision}</dd></div><div><dt>Events shown</dt><dd>{snapshot.timeline.length}</dd></div><div><dt>Run state</dt><dd>{snapshot.run?.state}</dd></div></dl></aside>
      </div>
    </section>
  );
}
