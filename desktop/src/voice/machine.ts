import type { VoicePhase } from "../domain/types";

export interface VoiceMachineState {
  phase: VoicePhase;
  wakeName: string;
  heard: string;
  response: string;
  activity: string;
  networkActive: boolean;
  error: string | null;
}

export type VoiceEvent =
  | { type: "arm" }
  | { type: "disarm" }
  | { type: "push_to_talk" }
  | { type: "wake"; transcript: string }
  | { type: "utterance"; transcript: string; remote: boolean }
  | { type: "act" }
  | { type: "await_approval" }
  | { type: "speak"; text: string }
  | { type: "interrupt" }
  | { type: "complete" }
  | { type: "fail"; message: string };

export function validateWakeName(value: string): string {
  const name = value.trim().replace(/\s+/g, " ");
  if (name.length < 2 || name.length > 32) {
    throw new Error("Wake name must contain 2 to 32 characters");
  }
  if (!/^[\p{L}\p{N}][\p{L}\p{N} '-]*$/u.test(name)) {
    throw new Error("Wake name may contain letters, numbers, spaces, apostrophes, and hyphens");
  }
  return name;
}

function normalizedWords(value: string): string[] {
  return value
    .normalize("NFKC")
    .toLocaleLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
}

export function matchesWakePhrase(transcript: string, wakeName: string): boolean {
  const heard = normalizedWords(transcript);
  const phrase = ["hey", ...normalizedWords(validateWakeName(wakeName))];
  if (heard.length < phrase.length) return false;
  return heard.some((_, start) => phrase.every((word, offset) => heard[start + offset] === word));
}

function activityFor(phase: VoicePhase, wakeName: string): string {
  const labels: Record<VoicePhase, string> = {
    off: "Microphone is off",
    armed: `Waiting locally for “Hey, ${wakeName}”`,
    hearing: "Listening on this device",
    thinking: "Choosing the lightest capable route",
    acting: "Sleipnir is acting through an approved capability",
    approval: "Waiting for your approval",
    speaking: "Speaking · interrupt anytime",
    error: "Voice needs attention",
  };
  return labels[phase];
}

export function createVoiceState(phase: VoicePhase, wakeName = "Sleipnir"): VoiceMachineState {
  const validName = validateWakeName(wakeName);
  return {
    phase,
    wakeName: validName,
    heard: "",
    response: "",
    activity: activityFor(phase, validName),
    networkActive: false,
    error: null,
  };
}

export function reduceVoice(state: VoiceMachineState, event: VoiceEvent): VoiceMachineState {
  switch (event.type) {
    case "arm":
      return { ...state, phase: "armed", activity: activityFor("armed", state.wakeName), networkActive: false, error: null };
    case "disarm":
      return { ...state, phase: "off", activity: activityFor("off", state.wakeName), heard: "", response: "", networkActive: false, error: null };
    case "push_to_talk":
      return { ...state, phase: "hearing", activity: activityFor("hearing", state.wakeName), heard: "", networkActive: false, error: null };
    case "wake":
      if (state.phase !== "armed" || !matchesWakePhrase(event.transcript, state.wakeName)) return state;
      return { ...state, phase: "hearing", activity: activityFor("hearing", state.wakeName), heard: "", networkActive: false, error: null };
    case "utterance":
      if (state.phase !== "hearing") return state;
      return { ...state, phase: "thinking", activity: activityFor("thinking", state.wakeName), heard: event.transcript.trim(), networkActive: event.remote, error: null };
    case "act":
      return { ...state, phase: "acting", activity: activityFor("acting", state.wakeName), networkActive: false, error: null };
    case "await_approval":
      return { ...state, phase: "approval", activity: activityFor("approval", state.wakeName), networkActive: false, error: null };
    case "speak":
      return { ...state, phase: "speaking", activity: activityFor("speaking", state.wakeName), response: event.text, networkActive: false, error: null };
    case "interrupt":
      if (state.phase !== "speaking") return state;
      return { ...state, phase: "hearing", activity: activityFor("hearing", state.wakeName), heard: "", response: "", networkActive: false, error: null };
    case "complete":
      return { ...state, phase: "armed", activity: activityFor("armed", state.wakeName), heard: "", response: "", networkActive: false, error: null };
    case "fail":
      return { ...state, phase: "error", activity: activityFor("error", state.wakeName), networkActive: false, error: event.message };
  }
}
