import type { AppSettings, DashboardSnapshot, ReviewDecision, VoiceSettings } from "../domain/types";
import type { InstructionRoute } from "../routing/intent";

export interface SleipnirBridge {
  loadDashboard(): Promise<DashboardSnapshot>;
  sendMessage(text: string, route?: InstructionRoute): Promise<void>;
  startProject(goal: string): Promise<void>;
  review(itemId: string, decision: ReviewDecision): Promise<void>;
  setVoiceSettings(settings: VoiceSettings): Promise<void>;
  setListening(enabled: boolean): Promise<void>;
  setAppSettings(settings: AppSettings): Promise<void>;
  selectRunRoot(path: string): Promise<void>;
  showMain(): Promise<void>;
}

export function isTauriRuntime(): boolean {
  return "__TAURI_INTERNALS__" in window;
}
