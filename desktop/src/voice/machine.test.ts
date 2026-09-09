import { describe, expect, it } from "vitest";

import { createVoiceState, matchesWakePhrase, reduceVoice, validateWakeName } from "./machine";

describe("ambient voice state machine", () => {
  it("keeps the network dark while armed and begins hearing only after a local wake", () => {
    const armed = createVoiceState("armed");
    const hearing = reduceVoice(armed, { type: "wake", transcript: "hey sleipnir" });

    expect(armed.networkActive).toBe(false);
    expect(armed.activity).toBe("Waiting locally for “Hey, Sleipnir”");
    expect(hearing).toMatchObject({ phase: "hearing", networkActive: false });
  });

  it("marks a remote route only after a finalized utterance needs one", () => {
    const hearing = reduceVoice(createVoiceState("armed"), { type: "wake", transcript: "hey sleipnir" });
    const thinking = reduceVoice(hearing, {
      type: "utterance",
      transcript: "continue the application",
      remote: true,
    });

    expect(thinking).toMatchObject({
      phase: "thinking",
      heard: "continue the application",
      networkActive: true,
    });
  });

  it("supports barge-in while speaking", () => {
    const speaking = reduceVoice(createVoiceState("armed"), {
      type: "speak",
      text: "I found one change that needs approval.",
    });
    const interrupted = reduceVoice(speaking, { type: "interrupt" });

    expect(speaking.phase).toBe("speaking");
    expect(interrupted).toMatchObject({ phase: "hearing", response: "", networkActive: false });
  });

  it("keeps action and approval phases visible", () => {
    const acting = reduceVoice(createVoiceState("thinking"), { type: "act" });
    const approval = reduceVoice(acting, { type: "await_approval" });

    expect(acting).toMatchObject({ phase: "acting", activity: expect.stringContaining("acting") });
    expect(approval).toMatchObject({ phase: "approval", activity: "Waiting for your approval" });
  });

  it("matches a configurable phrase without accepting embedded lookalikes", () => {
    expect(matchesWakePhrase("Hey, Sleipnir — are you there?", "Sleipnir")).toBe(true);
    expect(matchesWakePhrase("they sleipnirized the project", "Sleipnir")).toBe(false);
    expect(validateWakeName("  Friday  ")).toBe("Friday");
    expect(() => validateWakeName("h")).toThrow(/2 to 32/);
  });
});
