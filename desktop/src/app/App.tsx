import { AudioLines, Settings2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { SleipnirBridge } from "../bridge";
import { isTauriRuntime } from "../bridge";
import { createDemoBridge } from "../bridge/demo";
import { createTauriBridge } from "../bridge/tauri";
import { Brand } from "../components/Brand";
import { AdvancedRail } from "../components/AdvancedRail";
import { OrbitDock, type ViewId } from "../components/OrbitDock";
import { StatusCluster } from "../components/StatusCluster";
import type { ReviewDecision } from "../domain/types";
import "../styles/app.css";
import { CommandView } from "../views/CommandView";
import { ChronicleView } from "../views/ChronicleView";
import { ConsoleView } from "../views/ConsoleView";
import { GraphView } from "../views/GraphView";
import { ReviewView } from "../views/ReviewView";
import { RoutingView } from "../views/RoutingView";
import { SettingsView } from "../views/SettingsView";
import { TrustView } from "../views/TrustView";
import { useSleipnir } from "./useSleipnir";

export type ColorScheme = "orbit" | "index" | "glasshouse";

const runtimeBridge = isTauriRuntime() ? createTauriBridge() : createDemoBridge();

export function App({ bridge = runtimeBridge }: { bridge?: SleipnirBridge }) {
  const [advanced, setAdvanced] = useState(false);
  const [scheme, setScheme] = useState<ColorScheme>("orbit");
  const [activeView, setActiveView] = useState<ViewId>("home");
  const { snapshot, error, runAndRefresh } = useSleipnir(bridge);

  useEffect(() => {
    if (!advanced && !["home", "run", "review", "voice"].includes(activeView)) {
      setActiveView("home");
    }
  }, [activeView, advanced]);

  const main = useMemo(() => {
    if (error) {
      return <section className="load-state load-state--error"><h1>Core unavailable.</h1><p>{error}</p></section>;
    }
    if (!snapshot) {
      return <section className="load-state" aria-live="polite"><span className="loader" /><p>Connecting to the local core…</p></section>;
    }
    if (activeView === "run") return <GraphView snapshot={snapshot} />;
    if (activeView === "review") {
      const review = (itemId: string, decision: ReviewDecision) =>
        runAndRefresh(() => bridge.review(itemId, decision));
      return <ReviewView snapshot={snapshot} onReview={review} />;
    }
    if (activeView === "console") return <ConsoleView snapshot={snapshot} onSend={(text) => runAndRefresh(() => bridge.sendMessage(text))} />;
    if (activeView === "chronicle") return <ChronicleView snapshot={snapshot} />;
    if (activeView === "routing") return <RoutingView snapshot={snapshot} />;
    if (activeView === "trust") return <TrustView snapshot={snapshot} />;
    if (activeView === "settings") return <SettingsView />;
    if (activeView === "voice") {
      return (
        <section className="view empty-view">
          <AudioLines size={34} aria-hidden="true" />
          <span className="kicker">Ambient voice · {snapshot.voice.phase}</span>
          <h1>Hey, {snapshot.voice.settings.wakeName}.</h1>
          <p>{snapshot.voice.privacyLabel}. Voice setup continues in the next build stage.</p>
        </section>
      );
    }
    return <CommandView snapshot={snapshot} onSubmit={(text) => runAndRefresh(() => bridge.sendMessage(text))} />;
  }, [activeView, bridge, error, runAndRefresh, snapshot]);

  return (
    <div className="app" data-scheme={scheme} data-mode={advanced ? "advanced" : "simple"}>
      <header className="topbar">
        <Brand />
        {snapshot && <StatusCluster snapshot={snapshot} />}
        <div className="topbar__actions">
          <div className="topbar__status">
            <i className="status-dot" />
            <span>{snapshot?.runtime.label ?? "Connecting to core"}</span>
          </div>
          <button
            className="mode-switch"
            type="button"
            aria-label="Advanced mode"
            aria-pressed={advanced}
            onClick={() => setAdvanced((current) => !current)}
          >
            <Settings2 size={15} aria-hidden="true" />
            {advanced ? "Advanced" : "Simple"}
          </button>
        </div>
      </header>

      <main className={`workspace ${advanced ? "workspace--advanced" : ""}`}>
        {advanced && snapshot && <AdvancedRail snapshot={snapshot} />}
        <div className="workspace__stage">{main}</div>
      </main>

      <footer className="app-footer">
        <div className="dock-cluster">
          <OrbitDock active={activeView} advanced={advanced} onNavigate={setActiveView} />
          <select
            className="scheme-select"
            aria-label="Color scheme"
            value={scheme}
            onChange={(event) => setScheme(event.target.value as ColorScheme)}
          >
            <option value="orbit">Orbit</option>
            <option value="index">Index</option>
            <option value="glasshouse">Glasshouse</option>
          </select>
        </div>
      </footer>
    </div>
  );
}
