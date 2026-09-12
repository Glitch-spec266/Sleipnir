import { describe, expect, it, vi } from "vitest";
import { createDemoBridge } from "./demo";
import { playSpeechAudio } from "./speech";

describe("speech microphone guard", () => {
  it("leaves locally played audio to the native turn guard", async () => {
    const bridge = createDemoBridge();
    const mute = vi.spyOn(bridge, "setSpeechPlayback");
    await playSpeechAudio(null, bridge);
    expect(mute).not.toHaveBeenCalled();
  });

  it.each([false, true])("releases the microphone after playback (failure=%s)", async (failure) => {
    const calls: boolean[] = [];
    const bridge = createDemoBridge();
    bridge.setSpeechPlayback = async (active) => { calls.push(active); };
    class Player extends EventTarget {
      async play() {
        expect(calls).toEqual([true]);
        if (failure) throw new Error("audio device unavailable");
        this.dispatchEvent(new Event("ended"));
      }
    }
    vi.stubGlobal("Audio", Player);
    try {
      const playback = playSpeechAudio({ data: "YXVkaW8=", mimeType: "audio/wav" }, bridge);
      if (failure) await expect(playback).rejects.toThrow("audio device unavailable");
      else await playback;
      expect(calls).toEqual([true, false]);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
