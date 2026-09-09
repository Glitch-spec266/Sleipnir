import { AudioLines, Mic, MicOff } from "lucide-react";

import type { VoicePhase } from "../domain/types";

const phaseLabels: Record<VoicePhase, string> = {
  off: "Voice off",
  armed: "Waiting for wake phrase",
  hearing: "Listening",
  thinking: "Thinking",
  acting: "Acting",
  approval: "Approval needed",
  speaking: "Speaking",
  error: "Voice error",
};

export function VoiceOrb({ phase, level = 0 }: { phase: VoicePhase; level?: number }) {
  const active = phase !== "off" && phase !== "error";

  return (
    <div className="voice-orb-wrap" data-phase={phase} aria-label={phaseLabels[phase]} role="img">
      <div className="voice-orb__halo" />
      <div className="voice-orb__ring voice-orb__ring--outer" />
      <div className="voice-orb__ring voice-orb__ring--inner" />
      <div className="voice-orb">
        {active ? <AudioLines size={34} aria-hidden="true" /> : <MicOff size={30} aria-hidden="true" />}
        {phase === "hearing" && (
          <span className="voice-level" style={{ "--voice-level": Math.max(0.2, level) } as React.CSSProperties}>
            <i /><i /><i /><i /><i />
          </span>
        )}
        {phase === "armed" && <Mic className="voice-orb__mic" size={13} aria-hidden="true" />}
      </div>
      <span className="voice-orb__phase">{phaseLabels[phase]}</span>
    </div>
  );
}
