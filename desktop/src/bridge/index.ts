import type { DashboardSnapshot, ReviewDecision, VoiceSettings } from "../domain/types";

export interface SleipnirBridge {
  loadDashboard(): Promise<DashboardSnapshot>;
  sendMessage(text: string): Promise<void>;
  startProject(goal: string): Promise<void>;
  review(itemId: string, decision: ReviewDecision): Promise<void>;
  setVoiceSettings(settings: VoiceSettings): Promise<void>;
  setListening(enabled: boolean): Promise<void>;
}

export function isTauriRuntime(): boolean {
  return "__TAURI_INTERNALS__" in window;
}
