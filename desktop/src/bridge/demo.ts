import type { SleipnirBridge } from ".";
import type { AppSettings, DashboardSnapshot, ReviewDecision, VoiceSettings } from "../domain/types";
import { createDemoSnapshot } from "../fixtures/run";

export function createDemoBridge(): SleipnirBridge {
  let snapshot = createDemoSnapshot();

  const refresh = (): DashboardSnapshot => structuredClone(snapshot);

  return {
    async loadDashboard() {
      return refresh();
    },
    async sendMessage(text: string, route = "ambient") {
      const clean = text.trim();
      if (!clean) throw new Error("Instruction cannot be empty");
      snapshot.messages.push({
        id: `m-${snapshot.messages.length + 1}`,
        at: new Date().toISOString(),
        role: "operator",
        text: clean,
        route: "conversation",
      });
      const response = {
        status: "complete" as const,
        text: route === "ambient" ? "I kept that on the fast lane." : `The instruction is with the ${route} work lane.`,
        route: `${route} · approved`,
        rationale: route === "ambient" ? "Fast conversational lane." : "Operator approved the capable work lane.",
        sessionId: route === "ambient" ? null : `demo-${route}`,
      };
      snapshot.messages.push({
        id: `m-${snapshot.messages.length + 1}`,
        at: new Date().toISOString(),
        role: "sleipnir",
        text: response.text,
        route: response.route,
      });
      return response;
    },
    async startProject(goal: string) {
      const clean = goal.trim();
      if (!clean) return;
      if (snapshot.run) {
        snapshot.run = { ...snapshot.run, goal: clean, state: "planning", progress: 0 };
      }
      snapshot.timeline.unshift({
        id: `ev-${snapshot.timeline.length + 1}`,
        at: new Date().toISOString(),
        kind: "recovery",
        title: "Planning requested",
        detail: clean,
        taskId: null,
        tone: "live",
      });
    },
    async review(itemId: string, decision: ReviewDecision) {
      const item = snapshot.reviews.find((review) => review.id === itemId);
      if (!item) throw new Error(`Unknown review item: ${itemId}`);
      snapshot.timeline.unshift({
        id: `ev-${snapshot.timeline.length + 1}`,
        at: new Date().toISOString(),
        kind: "gate_requested",
        title: decision === "approve" ? "Review approved" : "Review returned",
        detail: `${item.taskId} · ${decision}`,
        taskId: item.taskId,
        tone: decision === "approve" ? "success" : "warning",
      });
    },
    async setVoiceSettings(settings: VoiceSettings) {
      snapshot.voice = { ...snapshot.voice, settings: structuredClone(settings) };
    },
    async setListening(enabled: boolean) {
      snapshot.voice = {
        ...snapshot.voice,
        phase: enabled ? "armed" : "off",
        heard: "",
        privacyLabel: enabled ? "Wake phrase stays on this device" : "Microphone is off",
      };
    },
    async setAppSettings(settings: AppSettings) {
      snapshot.settings = structuredClone(settings);
    },
    async selectRunRoot(path: string) {
      if (!path.trim()) throw new Error("Project run directory is required");
      if (snapshot.run) snapshot.run = { ...snapshot.run, workspace: path.trim() };
    },
    async showMain() {},
    async transcribeAudio() {
      return "What is running right now?";
    },
    async handoffInstruction() {},
    async speak() {
      return null;
    },
    async clearHistory() {
      snapshot.messages = [];
    },
  };
}
