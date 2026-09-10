import { listen } from "@tauri-apps/api/event";
import { useEffect, useRef, useState } from "react";

import { isTauriRuntime } from "../bridge";
import { createDemoBridge } from "../bridge/demo";
import { createTauriBridge } from "../bridge/tauri";
import { VoiceOrb } from "../components/VoiceOrb";
import type { VoicePhase } from "../domain/types";
import { classifyInstruction } from "../routing/intent";
import "../styles/app.css";

const bridge = isTauriRuntime() ? createTauriBridge() : createDemoBridge();

export function OrbApp() {
  const [phase, setPhase] = useState<VoicePhase>("armed");
  const [wakeName, setWakeName] = useState("Sleipnir");
  const [message, setMessage] = useState("Hold the shortcut to talk");
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const activeRef = useRef(false);

  const beginCapture = async () => {
    try {
      if (recorderRef.current?.state === "recording") return;
      const nextStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (!activeRef.current) {
        nextStream.getTracks().forEach((track) => track.stop());
        return;
      }
      const options = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg"]
        .find((candidate) => MediaRecorder.isTypeSupported(candidate));
      const nextRecorder = new MediaRecorder(nextStream, options ? { mimeType: options } : undefined);
      chunksRef.current = [];
      nextRecorder.ondataavailable = (event) => {
        if (event.data.size) chunksRef.current.push(event.data);
      };
      nextRecorder.start(250);
      streamRef.current = nextStream;
      recorderRef.current = nextRecorder;
      setMessage("Listening…");
    } catch (caught) {
      setPhase("error");
      setMessage(caught instanceof Error ? caught.message : "Microphone access failed");
    }
  };

  const finishCapture = async () => {
    const recorder = recorderRef.current;
    if (!recorder || recorder.state === "inactive") return;
    const finished = new Promise<void>((resolve) => recorder.addEventListener("stop", () => resolve(), { once: true }));
    recorder.stop();
    await finished;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    setPhase("thinking");
    setMessage("Transcribing locally…");
    try {
      const audio = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
      const bytes = Array.from(new Uint8Array(await audio.arrayBuffer()));
      const transcript = await bridge.transcribeAudio(bytes, audio.type);
      const decision = classifyInstruction(transcript);
      if (decision.kind === "confirm") {
        setPhase("approval");
        setMessage("Approval needed in Sleipnir");
        await bridge.handoffInstruction(transcript);
      } else {
        setMessage(transcript);
        const response = await bridge.sendMessage(transcript, "ambient");
        setPhase("speaking");
        setMessage(response.text);
        const speech = await bridge.speak(response.text);
        if (speech) {
          const player = new Audio(`data:${speech.mimeType};base64,${speech.data}`);
          await new Promise<void>((resolve, reject) => {
            player.addEventListener("ended", () => resolve(), { once: true });
            player.addEventListener("error", () => reject(new Error("The selected voice could not be played")), { once: true });
            void player.play().catch(reject);
          });
        }
        setPhase("armed");
      }
    } catch (caught) {
      setPhase("error");
      setMessage(caught instanceof Error ? caught.message : "Voice command failed");
    } finally {
      recorderRef.current = null;
      streamRef.current = null;
      chunksRef.current = [];
    }
  };

  useEffect(() => {
    void bridge.loadDashboard().then((snapshot) => {
      setPhase(snapshot.voice.phase);
      setWakeName(snapshot.voice.settings.wakeName);
    });
    if (!isTauriRuntime()) return;
    let disposed = false;
    const stops: Array<() => void> = [];
    void listen<boolean>("voice-activity", (event) => {
      activeRef.current = event.payload;
      setPhase(event.payload ? "hearing" : "armed");
      if (event.payload) void beginCapture();
      else void finishCapture();
    }).then((stop) => {
      if (disposed) stop();
      else stops.push(stop);
    });
    void listen<boolean>("listening-changed", (event) => {
      setPhase(event.payload ? "armed" : "off");
      setMessage(event.payload ? `Waiting for “Hey, ${wakeName}”` : "Microphone is off");
    }).then((stop) => {
      if (disposed) stop();
      else stops.push(stop);
    });
    void listen<VoicePhase>("voice-phase", (event) => {
      setPhase(event.payload);
      if (event.payload === "armed") setMessage(`Waiting for “Hey, ${wakeName}”`);
      if (event.payload === "thinking") setMessage("Thinking locally…");
      if (event.payload === "error") setMessage("Local wake listener needs attention");
    }).then((stop) => {
      if (disposed) stop();
      else stops.push(stop);
    });
    return () => {
      disposed = true;
      stops.forEach((stop) => stop());
    };
  }, []);

  return (
    <main className="orb-surface" data-scheme="orbit">
      <button type="button" className="orb-surface__button" aria-label="Open Sleipnir" onClick={() => bridge.showMain()}>
        <VoiceOrb phase={phase} level={phase === "hearing" ? 0.76 : 0} />
        <span className="orb-surface__wake">Hey, {wakeName}</span>
        <span className="orb-surface__message" role="status">{message}</span>
      </button>
    </main>
  );
}
