import { AlertTriangle, Check, Cpu, Download, Loader2, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import type { LocalModelReport, SetupRequirement, SetupStepResult } from "../domain/types";

interface SetupViewProps {
  probe(): Promise<SetupRequirement[]>;
  apply(): Promise<SetupStepResult[]>;
  models(): Promise<LocalModelReport>;
  pull(model: string): Promise<SetupStepResult>;
  onDone(): void;
}

type Stage = "checking" | "missing" | "installing" | "ready" | "offer" | "choosing" | "pulling" | "done";

const tierLabels: Record<string, string> = {
  low: "Low headroom",
  moderate: "Moderate headroom",
  high: "High headroom",
};

export function SetupView({ probe, apply, models, pull, onDone }: SetupViewProps) {
  const [stage, setStage] = useState<Stage>("checking");
  const [requirements, setRequirements] = useState<SetupRequirement[]>([]);
  const [report, setReport] = useState<LocalModelReport | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const check = useCallback(async () => {
    setStage("checking");
    setNote(null);
    try {
      const found = await probe();
      setRequirements(found);
      // An interactive gap is not a blocked install: the local model is a
      // choice about this machine's memory, so it belongs on the offer step
      // rather than in a list of things a command would fix.
      const blocking = found.filter((item) => !item.present && !item.interactive);
      const wantsModel = found.some((item) => !item.present && item.interactive);
      setStage(blocking.length > 0 ? "missing" : wantsModel ? "offer" : "ready");
    } catch (caught) {
      setNote(caught instanceof Error ? caught.message : "Could not check this machine");
      setStage("missing");
    }
  }, [probe]);

  useEffect(() => {
    void check();
  }, [check]);

  const install = async () => {
    setStage("installing");
    setNote(null);
    try {
      const results = await apply();
      const failed = results.filter((result) => !result.ok);
      if (failed.length > 0) {
        setNote(failed.map((result) => `${result.id}: ${result.detail}`).join(" · "));
      }
      await check();
    } catch (caught) {
      setNote(caught instanceof Error ? caught.message : "Setup could not finish");
      setStage("missing");
    }
  };

  const offerModel = async () => {
    setStage("choosing");
    setNote(null);
    try {
      setReport(await models());
    } catch (caught) {
      setNote(caught instanceof Error ? caught.message : "Could not read this machine's memory");
      setStage("offer");
    }
  };

  const choose = async (model: string) => {
    setStage("pulling");
    setNote(`Downloading ${model}. This runs in the background and can take a while.`);
    try {
      const result = await pull(model);
      setNote(result.detail);
      setStage(result.ok ? "done" : "choosing");
    } catch (caught) {
      setNote(caught instanceof Error ? caught.message : "The download failed");
      setStage("choosing");
    }
  };

  const missing = requirements.filter((item) => !item.present && !item.interactive);
  const privileged = missing.some((item) => item.needsRoot);

  return (
    <section className="view setup-view">
      <header className="setup-view__header">
        <h1>Set up Sleipnir</h1>
        <p>
          This checks what is already on your machine and installs the rest. You are asked
          for your password at most once.
        </p>
      </header>

      {stage === "checking" && (
        <p className="setup-view__status">
          <Loader2 className="spin" size={16} aria-hidden="true" /> Checking this machine…
        </p>
      )}

      {(stage === "missing" || stage === "installing") && (
        <>
          <ul className="setup-view__list">
            {requirements.map((item) => (
              <li key={item.id} className={item.present ? "is-present" : "is-missing"}>
                {item.present ? (
                  <Check size={15} aria-hidden="true" />
                ) : (
                  <AlertTriangle size={15} aria-hidden="true" />
                )}
                <span>{item.label}</span>
                {!item.present && item.fix && <code>{item.fix}</code>}
              </li>
            ))}
          </ul>
          {privileged && (
            <p className="setup-view__privileged">
              <ShieldCheck size={15} aria-hidden="true" />
              {missing.filter((item) => item.needsRoot).length} of these need administrator
              rights. They run together, so you are asked once.
            </p>
          )}
          <button type="button" onClick={install} disabled={stage === "installing"}>
            {stage === "installing" ? (
              <>
                <Loader2 className="spin" size={15} aria-hidden="true" /> Installing…
              </>
            ) : (
              <>Install the {missing.length} missing {missing.length === 1 ? "item" : "items"}</>
            )}
          </button>
        </>
      )}

      {stage === "ready" && (
        <>
          <p className="setup-view__status">
            <Check size={16} aria-hidden="true" /> Everything Sleipnir needs is installed.
          </p>
          <p>
            Next, connect the providers you want in Settings — you only need an API key for
            the ones you actually use.
          </p>
          <div className="setup-view__actions">
            <button type="button" onClick={() => setStage("offer")}>
              Continue
            </button>
          </div>
        </>
      )}

      {stage === "offer" && (
        <>
          <h2>Want a local model?</h2>
          <p>
            A model running on this machine makes the voice assistant smarter and keeps what
            you say off the network. It is optional — Sleipnir works without one.
          </p>
          <div className="setup-view__actions">
            <button type="button" onClick={offerModel}>
              <Cpu size={15} aria-hidden="true" /> Yes, check what fits
            </button>
            <button type="button" className="is-secondary" onClick={onDone}>
              Skip for now
            </button>
          </div>
        </>
      )}

      {(stage === "choosing" || stage === "pulling") && (
        <>
          <h2>Choose a model</h2>
          {report ? (
            <>
              <p className="setup-view__headroom">
                {report.headroom.freeGib.toFixed(1)} GB free of{" "}
                {report.headroom.totalGib.toFixed(1)} GB on {report.headroom.device}.
              </p>
              <ul className="setup-view__models">
                {report.options.map((option) => (
                  <li key={option.model} className={option.fits ? "" : "is-too-big"}>
                    <div>
                      <strong>{tierLabels[option.tier] ?? option.tier}</strong>
                      <code>{option.model}</code>
                      <small>
                        {option.download === "unknown"
                          ? "Download size unavailable right now"
                          : `${option.download} download`}
                        {" — "}
                        {option.note}
                      </small>
                    </div>
                    <button
                      type="button"
                      disabled={!option.fits || stage === "pulling"}
                      onClick={() => choose(option.model)}
                    >
                      <Download size={15} aria-hidden="true" /> Install
                    </button>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="setup-view__status">
              <Loader2 className="spin" size={16} aria-hidden="true" /> Reading this machine’s
              memory…
            </p>
          )}
          <button type="button" className="is-secondary" onClick={onDone}>
            Skip for now
          </button>
        </>
      )}

      {stage === "done" && (
        <>
          <p className="setup-view__status">
            <Check size={16} aria-hidden="true" /> Your local assistant is ready.
          </p>
          <div className="setup-view__actions">
            <button type="button" onClick={onDone}>
              Start using Sleipnir
            </button>
          </div>
        </>
      )}

      {note && <p className="setup-view__note">{note}</p>}
    </section>
  );
}
