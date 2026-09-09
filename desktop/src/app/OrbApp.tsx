import { listen } from "@tauri-apps/api/event";
import { useEffect, useState } from "react";

import { isTauriRuntime } from "../bridge";
import { createDemoBridge } from "../bridge/demo";
import { createTauriBridge } from "../bridge/tauri";
import { VoiceOrb } from "../components/VoiceOrb";
import type { VoicePhase } from "../domain/types";
import "../styles/app.css";

const bridge = isTauriRuntime() ? createTauriBridge() : createDemoBridge();

export function OrbApp() {
  const [phase, setPhase] = useState<VoicePhase>("armed");
  const [wakeName, setWakeName] = useState("Sleipnir");

  useEffect(() => {
    void bridge.loadDashboard().then((snapshot) => {
      setPhase(snapshot.voice.phase);
      setWakeName(snapshot.voice.settings.wakeName);
    });
    if (!isTauriRuntime()) return;
    let disposed = false;
    let unlisten: (() => void) | undefined;
    void listen<boolean>("voice-activity", (event) => {
      setPhase(event.payload ? "hearing" : "armed");
    }).then((stop) => {
      if (disposed) stop();
      else unlisten = stop;
    });
    return () => {
      disposed = true;
      unlisten?.();
    };
  }, []);

  return (
    <main className="orb-surface" data-scheme="orbit">
      <button type="button" className="orb-surface__button" aria-label="Open Sleipnir" onClick={() => bridge.showMain()}>
        <VoiceOrb phase={phase} level={phase === "hearing" ? 0.76 : 0} />
        <span className="orb-surface__wake">Hey, {wakeName}</span>
      </button>
    </main>
  );
}
