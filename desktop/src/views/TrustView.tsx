import { Eye, LockKeyhole, ShieldCheck, ShieldOff } from "lucide-react";

import type { DashboardSnapshot } from "../domain/types";

export function TrustView({ snapshot }: { snapshot: DashboardSnapshot }) {
  return (
    <section className="view view--trust">
      <header className="view-head"><div><span className="kicker">Trust · permissions and audit</span><h1>Power with a visible boundary.</h1><p>Basic actions begin narrow. Consequential actions ask; explicit scoped policies can change that.</p></div></header>
      <div className="trust-layout">
        <article className="surface capability-panel"><div className="surface__head"><span className="section-label">Operator capabilities</span><code>audit on</code></div><div className="capability-grid">{snapshot.capabilities.map((capability) => <div key={capability.id}><span className="capability-icon">{capability.state === "off" ? <ShieldOff size={17} /> : <ShieldCheck size={17} />}</span><section><strong>{capability.label}</strong><p>{capability.detail}</p></section><code>{capability.state}</code></div>)}</div></article>
        <article className="surface audit-panel"><div className="surface__head"><span className="section-label">Recent audit</span><Eye size={15} /></div>{snapshot.audit.map((event) => <div className="audit-row" key={event.id}><small>{new Date(event.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</small><span><strong>{event.action}</strong><em>{event.actor} · {event.scope}</em></span><code data-result={event.result}>{event.result}</code></div>)}<div className="secret-note"><LockKeyhole size={16} /><p>Secrets live in protected session memory. Workers never inherit the credential route.</p></div></article>
      </div>
    </section>
  );
}
