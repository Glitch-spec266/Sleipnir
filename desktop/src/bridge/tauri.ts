import { invoke } from "@tauri-apps/api/core";

import type { SleipnirBridge } from ".";
import type { DashboardSnapshot, ReviewDecision, VoiceSettings } from "../domain/types";

export function createTauriBridge(): SleipnirBridge {
  return {
    loadDashboard: () => invoke<DashboardSnapshot>("load_dashboard"),
    sendMessage: (text: string) => invoke<void>("send_message", { text }),
    startProject: (goal: string) => invoke<void>("start_project", { goal }),
    review: (itemId: string, decision: ReviewDecision) =>
      invoke<void>("review_item", { itemId, decision }),
    setVoiceSettings: (settings: VoiceSettings) =>
      invoke<void>("set_voice_settings", { settings }),
    setListening: (enabled: boolean) => invoke<void>("set_listening", { enabled }),
  };
}
