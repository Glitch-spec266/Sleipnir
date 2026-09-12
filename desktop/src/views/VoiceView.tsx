import { Cloud, Headphones, Keyboard, Mic, Save, ShieldCheck, Volume2 } from "lucide-react";
import { useEffect, useState } from "react";

import { VoiceOrb } from "../components/VoiceOrb";
import type { DashboardSnapshot, VoiceSettings } from "../domain/types";
import { validateWakeName } from "../voice/machine";

interface VoiceViewProps {
  snapshot: DashboardSnapshot;
  onSetListening(enabled: boolean): Promise<void>;
  onSave(settings: VoiceSettings): Promise<void>;
}

const headings = {
  off: "Voice is off.",
  armed: "Sleipnir is listening.",
  hearing: "I’m listening.",
  thinking: "Finding the best route.",
  acting: "Sleipnir is acting.",
  approval: "Your approval is needed.",
  speaking: "Sleipnir is speaking.",
  error: "Voice needs attention.",
} as const;

export function VoiceView({ snapshot, onSetListening, onSave }: VoiceViewProps) {
  const voice = snapshot.voice;
  const [draft, setDraft] = useState(voice.settings);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => setDraft(voice.settings), [voice.settings]);

  const patch = <K extends keyof VoiceSettings>(key: K, value: VoiceSettings[K]) => {
    setDraft((current) => ({ ...current, [key]: value }));
    setMessage(null);
  };

  const save = async () => {
    try {
      const settings = { ...draft, wakeName: validateWakeName(draft.wakeName) };
      await onSave(settings);
      setMessage("Voice settings saved on this device.");
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : "Could not save voice settings");
    }
  };

  return (
    <section className="view voice-view">
      <div className="voice-stage">
        <div className="voice-stage__copy">
          <span className="kicker">Ambient command layer</span>
          <h1>{headings[voice.phase]}</h1>
          <p>
            Say <strong>“Hey, {voice.settings.wakeName}”</strong>, or hold your push-to-talk shortcut.
            Speech leaves this device only after activation.
          </p>
          <div className="voice-actions">
            <button className="primary-action" type="button" onClick={() => onSetListening(voice.phase === "off")}>
              <Mic size={15} aria-hidden="true" />
              {voice.phase === "off" ? "Start listening" : "Stop listening"}
            </button>
            <button className="secondary-action" type="button" disabled={voice.phase === "off"}>
              <Keyboard size={15} aria-hidden="true" /> Talk now
              <kbd>{voice.settings.pushToTalkShortcut}</kbd>
            </button>
          </div>
          <div className="privacy-chip">
            <ShieldCheck size={14} aria-hidden="true" />
            <span><strong>Wake detection is local</strong> · {voice.privacyLabel}</span>
          </div>
        </div>
        <VoiceOrb phase={voice.phase} level={voice.level} />
      </div>

      <div className="voice-settings-grid">
        <section className="surface voice-settings-card">
          <div className="surface__head">
            <span className="section-label">Wake & response</span>
            <Headphones size={15} aria-hidden="true" />
          </div>
          <div className="form-grid">
            <label>
              <span>Wake name</span>
              <input aria-label="Wake name" value={draft.wakeName} onChange={(event) => patch("wakeName", event.target.value)} />
              <small>Activated by “Hey, {draft.wakeName || "…"}”</small>
            </label>
            <label>
              <span>Your name</span>
              <input aria-label="Your name" value={draft.operatorName} onChange={(event) => patch("operatorName", event.target.value)} />
              <small>{draft.operatorName ? `Addressed as ${draft.operatorName}` : "Leave blank and it will not know who you are"}</small>
            </label>
            <label>
              <span>Push-to-talk shortcut</span>
              <input aria-label="Push-to-talk shortcut" value={draft.pushToTalkShortcut} onChange={(event) => patch("pushToTalkShortcut", event.target.value)} />
            </label>
            <label>
              <span>Transcription</span>
              <select aria-label="Transcription" value={draft.transcription} onChange={(event) => patch("transcription", event.target.value as VoiceSettings["transcription"])}>
                <option value="local">On-device (private)</option>
                <option value="gemini">Gemini live</option>
              </select>
            </label>
            <label>
              <span>Ambient provider</span>
              <select aria-label="Ambient provider" value={draft.ambientProvider} onChange={(event) => patch("ambientProvider", event.target.value as VoiceSettings["ambientProvider"])}>
                <option value="auto">Automatic · activated cloud</option>
                <option value="ollama">Ollama · local</option>
                <option value="gemini">Gemini</option>
                <option value="openrouter">OpenRouter</option>
                <option value="nvidia-nim">NVIDIA NIM</option>
              </select>
            </label>
            <label>
              <span>Ambient response model</span>
              <input aria-label="Ambient response model" value={draft.responseModel} onChange={(event) => patch("responseModel", event.target.value)} />
              <small>For local JARVIS, choose Ollama and name an installed model.</small>
            </label>
            <label>
              <span>Escalation</span>
              <select aria-label="Escalation" value={draft.escalation} onChange={(event) => patch("escalation", event.target.value as VoiceSettings["escalation"])}>
                <option value="automatic">Suggest, then ask</option>
                <option value="confirm">Always ask</option>
              </select>
            </label>
          </div>
          <div className="voice-switches">
            <Toggle label="Local wake detection" checked={draft.localWake} onChange={(checked) => patch("localWake", checked)} />
            <Toggle label="Start at login" checked={draft.startAtLogin} onChange={(checked) => patch("startAtLogin", checked)} />
            <Toggle label="Allow voice interruption" checked={draft.interruptible} onChange={(checked) => patch("interruptible", checked)} />
          </div>
        </section>

        <section className="surface voice-settings-card">
          <div className="surface__head">
            <span className="section-label">Voice character</span>
            <Volume2 size={15} aria-hidden="true" />
          </div>
          <div className="form-grid">
            <label>
              <span>Voice provider</span>
              <select aria-label="Voice provider" value={draft.voiceProvider} onChange={(event) => patch("voiceProvider", event.target.value as VoiceSettings["voiceProvider"])}>
                <option value="system">System voice · free</option>
                <option value="gemini">Gemini speech</option>
                <option value="openrouter">OpenRouter speech</option>
              </select>
            </label>
            <label>
              <span>Voice preset</span>
              <select aria-label="Voice preset" value={draft.voiceId} onChange={(event) => patch("voiceId", event.target.value)}>
                <optgroup label="Natural">
                  <option value="system-natural">Natural · device</option>
                  <option value="american-warm">American · warm</option>
                  <option value="british-calm">British · calm</option>
                  <option value="australian-bright">Australian · bright</option>
                  <option value="indian-clear">Indian · clear</option>
                </optgroup>
                <optgroup label="Character">
                  <option value="meme-dramatic">Dramatic announcer</option>
                  <option value="meme-deadpan">Deadpan operator</option>
                </optgroup>
              </select>
            </label>
            <label>
              <span>Accent profile</span>
              <select aria-label="Accent profile" value={draft.accent} onChange={(event) => patch("accent", event.target.value as VoiceSettings["accent"])}>
                <option value="neutral">Adaptive neutral</option>
                <option value="american">American</option>
                <option value="british">British</option>
                <option value="australian">Australian</option>
                <option value="indian">Indian</option>
              </select>
            </label>
          </div>
          <div className="provider-activation">
            <Cloud size={15} aria-hidden="true" />
            <div>
              <strong>Bring your own providers</strong>
              <p>Activate OpenRouter, Gemini, or NVIDIA NIM by naming an environment variable. Secret values never enter project files or run history.</p>
              <code>OPENROUTER_API_KEY · GEMINI_API_KEY · NVIDIA_API_KEY</code>
            </div>
          </div>
          <button className="save-action" type="button" onClick={save}>
            <Save size={14} aria-hidden="true" /> Save voice settings
          </button>
          {message && <p className="form-message" role="status">{message}</p>}
        </section>
      </div>
    </section>
  );
}

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange(checked: boolean): void }) {
  return (
    <label>
      <span>{label}</span>
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
    </label>
  );
}
