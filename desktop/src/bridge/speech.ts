import type { SleipnirBridge } from ".";
import type { SpeechAudio } from "../domain/types";

/** Local speech plays in the core; cloud audio plays here with the same mute. */
export async function playSpeechAudio(audio: SpeechAudio | null | undefined, bridge: SleipnirBridge) {
  if (!audio) return;
  await bridge.setSpeechPlayback(true);
  try {
    const player = new Audio(`data:${audio.mimeType};base64,${audio.data}`);
    await new Promise<void>((resolve, reject) => {
      player.addEventListener("ended", () => resolve(), { once: true });
      player.addEventListener("error", () => reject(new Error("The selected voice could not be played")), { once: true });
      void player.play().catch(reject);
    });
  } finally {
    await bridge.setSpeechPlayback(false);
  }
}
