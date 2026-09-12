import type { AgentResponse, AppSettings, DashboardSnapshot, HubPairing, LocalModelReport, ReviewDecision, SetupRequirement, SetupStepResult, SpeechAudio, VoiceSettings } from "../domain/types";
import type { InstructionRoute } from "../routing/intent";

export interface SleipnirBridge {
  loadDashboard(): Promise<DashboardSnapshot>;
  sendMessage(text: string, route?: InstructionRoute): Promise<AgentResponse>;
  startProject(goal: string): Promise<void>;
  review(itemId: string, decision: ReviewDecision): Promise<void>;
  setVoiceSettings(settings: VoiceSettings): Promise<void>;
  setListening(enabled: boolean): Promise<void>;
  setAppSettings(settings: AppSettings): Promise<void>;
  selectRunRoot(path: string): Promise<void>;
  showMain(): Promise<void>;
  transcribeAudio(audio: number[], mimeType: string): Promise<string>;
  handoffInstruction(text: string): Promise<void>;
  speak(text: string): Promise<SpeechAudio | null>;
  clearHistory(): Promise<void>;
  probeSetup(): Promise<SetupRequirement[]>;
  applySetup(): Promise<SetupStepResult[]>;
  localModels(): Promise<LocalModelReport>;
  pullModel(model: string): Promise<SetupStepResult>;
  hubPairing(): Promise<HubPairing>;
}

export function isTauriRuntime(): boolean {
  return "__TAURI_INTERNALS__" in window;
}
