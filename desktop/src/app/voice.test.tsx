import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { createDemoBridge } from "../bridge/demo";
import { App } from "./App";

describe("voice workspace", () => {
  it("makes listening state and its privacy boundary explicit", async () => {
    const bridge = createDemoBridge();
    render(<App bridge={bridge} />);
    await screen.findByText("Local core connected");
    fireEvent.click(screen.getByRole("button", { name: "Voice" }));

    expect(screen.getByRole("heading", { name: "Sleipnir is listening." })).toBeVisible();
    expect(screen.getByText("Wake detection is local")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Stop listening" }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Voice is off." })).toBeVisible());
  });

  it("saves a valid wake name and provider voice selection", async () => {
    const bridge = createDemoBridge();
    render(<App bridge={bridge} />);
    await screen.findByText("Local core connected");
    fireEvent.click(screen.getByRole("button", { name: "Voice" }));

    fireEvent.change(screen.getByLabelText("Wake name"), { target: { value: "Friday" } });
    fireEvent.change(screen.getByLabelText("Voice preset"), { target: { value: "british-calm" } });
    fireEvent.change(screen.getByLabelText("Ambient provider"), { target: { value: "ollama" } });
    fireEvent.change(screen.getByLabelText("Ambient response model"), { target: { value: "qwen3.5:4b" } });
    fireEvent.click(screen.getByRole("button", { name: "Save voice settings" }));

    await waitFor(async () => {
      expect((await bridge.loadDashboard()).voice.settings).toMatchObject({
        wakeName: "Friday",
        ambientProvider: "ollama",
        responseModel: "qwen3.5:4b",
        voiceId: "british-calm",
      });
    });
  });
});
