import { ArrowUp, AudioLines, FolderGit2, Sparkles } from "lucide-react";
import { useState, type FormEvent } from "react";

import type { DashboardSnapshot } from "../domain/types";

interface CommandViewProps {
  snapshot: DashboardSnapshot;
  onSubmit: (text: string) => Promise<void>;
}

export function CommandView({ snapshot, onSubmit }: CommandViewProps) {
  const [prompt, setPrompt] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!prompt.trim() || submitting) return;
    setSubmitting(true);
    try {
      await onSubmit(prompt);
      setPrompt("");
    } finally {
      setSubmitting(false);
    }
  };

  const running = snapshot.tasks.filter((task) => task.state === "running");
  const nextDecision = snapshot.reviews[0];

  return (
    <section className="view view--home">
      <header className="hero">
        <div className="kicker">Ready · local operator lane</div>
        <h1>Good evening.</h1>
        <p>
          Give Sleipnir the outcome. It will understand the workspace, choose the right
          lane, and bring back only the decisions that actually need you.
        </p>
      </header>

      <form className="command-card" onSubmit={submit}>
        <div>
          <textarea
            aria-label="New instruction"
            placeholder="What should we get done?"
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
          />
          <div className="command-card__meta">
            <span><FolderGit2 aria-hidden="true" size={14} />{snapshot.run?.workspace ?? "Choose a workspace"}</span>
            <span><Sparkles aria-hidden="true" size={14} />Auto route</span>
            <span><AudioLines aria-hidden="true" size={14} />Hey, {snapshot.voice.settings.wakeName}</span>
          </div>
        </div>
        <button className="command-card__go" type="submit" aria-label="Start task" disabled={submitting}>
          <ArrowUp aria-hidden="true" size={22} />
        </button>
      </form>

      <div className="home-grid">
        <article className="surface active-run">
          <div className="surface__head">
            <span className="section-label">In motion</span>
            <span className="data-label">{snapshot.run?.manifestTokens.toLocaleString()} tkn manifest</span>
          </div>
          <h2>{snapshot.run?.name ?? "No active project"}</h2>
          <p>{snapshot.run?.goal}</p>
          <div className="progress-track"><i style={{ width: `${snapshot.run?.progress ?? 0}%` }} /></div>
          <div className="task-mini-list">
            {running.map((task) => (
              <div key={task.id}>
                <span><i className="live-pip" />{task.title}</span>
                <code>{task.progress}%</code>
              </div>
            ))}
          </div>
        </article>
        <article className={`surface next-decision ${nextDecision ? "next-decision--waiting" : ""}`}>
          <div className="surface__head"><span className="section-label">Needs you</span><span className="data-label">{nextDecision ? "1 decision" : "clear"}</span></div>
          <h2>{nextDecision?.title ?? "Nothing is waiting"}</h2>
          <p>{nextDecision?.summary ?? "Safe work can continue in the background."}</p>
          {nextDecision && <button type="button" className="text-action">Open review <span>→</span></button>}
        </article>
      </div>
    </section>
  );
}
