import { Settings2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { emit, listen } from "@tauri-apps/api/event";

import type { SleipnirBridge } from "../bridge";
import { isTauriRuntime } from "../bridge";
import { createDemoBridge } from "../bridge/demo";
import { createTauriBridge } from "../bridge/tauri";
import { Brand } from "../components/Brand";
import { AdvancedRail } from "../components/AdvancedRail";
import { OrbitDock, type ViewId } from "../components/OrbitDock";
import { StatusCluster } from "../components/StatusCluster";
import type { ColorScheme, ReviewDecision } from "../domain/types";
import { classifyInstruction, type InstructionRoute } from "../routing/intent";
import "../styles/app.css";
import { CommandView } from "../views/CommandView";
import { ChronicleView } from "../views/ChronicleView";
import { ConsoleView } from "../views/ConsoleView";
import { GraphView } from "../views/GraphView";
import { ReviewView } from "../views/ReviewView";
import { RoutingView } from "../views/RoutingView";
import { SettingsView } from "../views/SettingsView";
import { TrustView } from "../views/TrustView";
import { VoiceView } from "../views/VoiceView";
import { useSleipnir } from "./useSleipnir";

const runtimeBridge = isTauriRuntime() ? createTauriBridge() : createDemoBridge();

export function App({ bridge = runtimeBridge }: { bridge?: SleipnirBridge }) {
  const [advanced, setAdvanced] = useState(false);
  const [scheme, setScheme] = useState<ColorScheme>("orbit");
  const [activeView, setActiveView] = useState<ViewId>("home");
  const [pendingRoute, setPendingRoute] = useState<{ text: string; recommended: "claude" | "codex"; reason: string } | null>(null);
  const { snapshot, error, refresh, runAndRefresh } = useSleipnir(bridge);

  useEffect(() => {
    if (!advanced && !["home", "run", "review", "voice"].includes(activeView)) {
      setActiveView("home");
    }
  }, [activeView, advanced]);

  useEffect(() => {
    if (!snapshot) return;
    if (!snapshot.settings.adaptiveScheme || typeof window.matchMedia !== "function") {
      setScheme(snapshot.settings.colorScheme);
      return;
    }
    const preference = window.matchMedia("(prefers-color-scheme: light)");
    const followSystem = () => setScheme(preference.matches ? "glasshouse" : "orbit");
    followSystem();
    preference.addEventListener("change", followSystem);
    return () => preference.removeEventListener("change", followSystem);
  }, [snapshot]);

  useEffect(() => {
    if (!pendingRoute) return;
    const cancel = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPendingRoute(null);
    };
    window.addEventListener("keydown", cancel);
    return () => window.removeEventListener("keydown", cancel);
  }, [pendingRoute]);

  useEffect(() => {
    if (!isTauriRuntime()) return;
    let disposed = false;
    let unlisten: (() => void) | undefined;
    void listen<string>("voice-instruction", (event) => {
      const decision = classifyInstruction(event.payload);
      // A spoken instruction is answered by the local agent unless the operator
      // named a work provider. A confirmation modal is invisible when the window
      // is closed to the tray, which reads as Sleipnir having ignored them.
      {
        const route = decision.kind === "direct" ? decision.recommended : "ambient";
        void runAndRefresh(async () => {
          try {
            const response = await bridge.sendMessage(event.payload, route);
            await emit("voice-phase", "speaking");
            await bridge.speak(response.text);
          } finally {
            await emit("voice-phase", "armed");
          }
        });
      }
    }).then((stop) => {
      if (disposed) stop();
      else unlisten = stop;
    });
    return () => {
      disposed = true;
      unlisten?.();
    };
  }, [bridge, runAndRefresh]);

  useEffect(() => {
    if (!isTauriRuntime()) return;
    let disposed = false;
    let unlisten: (() => void) | undefined;
    void listen("dashboard-changed", () => void refresh()).then((stop) => {
      if (disposed) stop();
      else unlisten = stop;
    });
    return () => {
      disposed = true;
      unlisten?.();
    };
  }, [refresh]);

  const sendInstruction = async (text: string, forced?: InstructionRoute) => {
    if (!forced) {
      const decision = classifyInstruction(text);
      if (decision.kind === "confirm") {
        setPendingRoute({ text, recommended: decision.recommended, reason: decision.reason });
        return;
      }
      if (decision.kind === "direct") forced = decision.recommended;
    }
    await runAndRefresh(() => bridge.sendMessage(text, forced ?? "ambient"));
  };

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
    if (activeView === "console") return <ConsoleView snapshot={snapshot} onSend={sendInstruction} />;
    if (activeView === "chronicle") return <ChronicleView snapshot={snapshot} />;
    if (activeView === "routing") return <RoutingView snapshot={snapshot} />;
    if (activeView === "trust") return <TrustView snapshot={snapshot} />;
    if (activeView === "settings") return <SettingsView
      snapshot={snapshot}
      onSave={(settings) => runAndRefresh(() => bridge.setAppSettings(settings))}
      onSelectProject={(path) => runAndRefresh(() => bridge.selectRunRoot(path))}
      onClearHistory={() => runAndRefresh(() => bridge.clearHistory())}
    />;
    if (activeView === "voice") {
      return <VoiceView
        snapshot={snapshot}
        onSetListening={(enabled) => runAndRefresh(() => bridge.setListening(enabled))}
        onSave={(settings) => runAndRefresh(() => bridge.setVoiceSettings(settings))}
      />;
    }
    return <CommandView
      snapshot={snapshot}
      onSubmit={sendInstruction}
      onStartProject={(goal) => runAndRefresh(() => bridge.startProject(goal))}
    />;
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

      <main className={`workspace ${advanced ? "workspace--advanced" : ""} ${advanced && snapshot && !snapshot.settings.advancedModules.mission && !snapshot.settings.advancedModules.helm ? "workspace--no-rail" : ""}`}>
        {advanced && snapshot && (snapshot.settings.advancedModules.mission || snapshot.settings.advancedModules.helm) && <AdvancedRail snapshot={snapshot} />}
        <div className="workspace__stage">{main}</div>
      </main>

      {pendingRoute && (
        <div className="decision-backdrop" role="presentation">
          <section className="surface route-decision" role="dialog" aria-modal="true" aria-labelledby="route-decision-title">
            <span className="kicker">Escalation boundary</span>
            <h2 id="route-decision-title">Choose a work lane</h2>
            <p>{pendingRoute.reason} Nothing is sent until you choose.</p>
            <blockquote>{pendingRoute.text}</blockquote>
            <div className="route-decision__actions">
              <button type="button" className="button button--quiet" onClick={() => { const item = pendingRoute; setPendingRoute(null); void sendInstruction(item.text, "ambient"); }}>Keep it quick</button>
              <button autoFocus={pendingRoute.recommended === "codex"} type="button" className={`button ${pendingRoute.recommended === "codex" ? "button--primary" : ""}`} onClick={() => { const item = pendingRoute; setPendingRoute(null); void sendInstruction(item.text, "codex"); }}>Use Codex</button>
              <button autoFocus={pendingRoute.recommended === "claude"} type="button" className={`button ${pendingRoute.recommended === "claude" ? "button--primary" : ""}`} onClick={() => { const item = pendingRoute; setPendingRoute(null); void sendInstruction(item.text, "claude"); }}>Use Claude</button>
            </div>
            <button className="route-decision__cancel" type="button" onClick={() => setPendingRoute(null)}>Cancel</button>
          </section>
        </div>
      )}

      <footer className="app-footer">
        <div className="dock-cluster">
          <OrbitDock active={activeView} advanced={advanced} modules={snapshot?.settings.advancedModules} onNavigate={setActiveView} />
          <select
            className="scheme-select"
            aria-label="Color scheme"
            value={scheme}
            onChange={(event) => {
              const next = event.target.value as ColorScheme;
              setScheme(next);
              if (snapshot) void runAndRefresh(() => bridge.setAppSettings({ ...snapshot.settings, colorScheme: next, adaptiveScheme: false }));
            }}
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
