import { ArrowUp, Braces, SquareTerminal } from "lucide-react";
import { useState, type FormEvent } from "react";

import type { DashboardSnapshot } from "../domain/types";

export function ConsoleView({ snapshot, onSend }: { snapshot: DashboardSnapshot; onSend: (text: string) => Promise<void> }) {
  const [text, setText] = useState("");

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!text.trim()) return;
    await onSend(text);
    setText("");
  };

  return (
    <section className="view view--console">
      <header className="view-head"><div><span className="kicker">Sparse control · bounded conversation</span><h1>Talk without flooding context.</h1><p>Steer the run, inspect the route, or explicitly widen a request into a project.</p></div></header>
      <article className="surface console-surface">
        <div className="console-bar"><span><SquareTerminal size={14} />control / {snapshot.run?.id}</span><code>{snapshot.run?.manifestTokens.toLocaleString()} tkn</code></div>
        <div className="console-messages">
          {snapshot.messages.map((message) => (
            <div className={`console-message console-message--${message.role}`} key={message.id}>
              <span>{message.role}{message.route ? ` · ${message.route}` : ""}</span>
              <p>{message.text}</p>
            </div>
          ))}
          <div className="tool-trace"><Braces size={15} /><code>projection.fold_results</code><span>42 events · offline</span><small>18 ms</small></div>
        </div>
        <form className="console-compose" onSubmit={submit}>
          <textarea aria-label="Console message" value={text} onChange={(event) => setText(event.target.value)} placeholder="Steer this run, ask why, or type /project…" />
          <button type="submit" aria-label="Send message"><ArrowUp size={19} /></button>
        </form>
      </article>
    </section>
  );
}
