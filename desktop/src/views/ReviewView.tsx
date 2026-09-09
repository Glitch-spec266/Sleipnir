import { Check, FileCode2, ShieldAlert, X } from "lucide-react";

import type { DashboardSnapshot, ReviewDecision } from "../domain/types";

interface ReviewViewProps {
  snapshot: DashboardSnapshot;
  onReview: (itemId: string, decision: ReviewDecision) => Promise<void>;
}

export function ReviewView({ snapshot, onReview }: ReviewViewProps) {
  const item = snapshot.reviews[0];
  if (!item) return <section className="view empty-view"><Check size={30} /><h1>Nothing needs review.</h1><p>Safe work continues in the background.</p></section>;

  return (
    <section className="view view--review">
      <header className="view-head"><div><span className="kicker">Review gate · {item.risk} risk</span><h1>One decision. Full context.</h1><p>Inspect the proposed boundary, its evidence, and the exact effect of approval.</p></div></header>
      <div className="review-layout">
        <article className="surface review-main">
          <div className="review-main__title"><div><code>{item.taskId}</code><h2>{item.title}</h2></div><ShieldAlert size={24} aria-hidden="true" /></div>
          <p>{item.summary}</p>
          <div className="file-changes">
            {item.files.map((file) => <div key={file.path}><span><FileCode2 size={15} />{file.path}</span><code>+{file.additions} −{file.deletions}</code></div>)}
          </div>
          <div className="review-actions">
            <button type="button" className="button button--quiet" onClick={() => void onReview(item.id, "reject")}><X size={15} />Reject</button>
            <button type="button" className="button" onClick={() => void onReview(item.id, "request_changes")}>Request changes</button>
            <button type="button" className="button button--primary" onClick={() => void onReview(item.id, "approve")}><Check size={15} />Approve once</button>
          </div>
        </article>
        <aside className="surface evidence-panel">
          <span className="section-label">Evidence</span>
          {item.checks.map((check) => <div className="evidence-row" key={check.label}><i data-state={check.status} /><span>{check.label}</span><code>{check.status}</code></div>)}
          <div className="policy-note"><ShieldAlert size={16} /><p><strong>This does not change your standing policy.</strong> “Always allow” remains a separate setting scoped by action and workspace.</p></div>
        </aside>
      </div>
    </section>
  );
}
