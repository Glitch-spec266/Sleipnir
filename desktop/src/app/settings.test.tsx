import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { createDemoBridge } from "../bridge/demo";
import { App } from "./App";

describe("persistent desktop settings", () => {
  it("saves telemetry, approval, and provider activation policy", async () => {
    const bridge = createDemoBridge();
    render(<App bridge={bridge} />);
    await screen.findByText("Local core connected");
    fireEvent.click(screen.getByRole("button", { name: "Advanced mode" }));
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));

    fireEvent.click(screen.getByLabelText("Share improvement data"));
    fireEvent.change(screen.getByLabelText("Capability approval"), { target: { value: "always" } });
    fireEvent.change(screen.getByLabelText("OpenRouter key variable"), { target: { value: "MY_OPENROUTER_KEY" } });
    fireEvent.click(screen.getByRole("button", { name: "Save desktop settings" }));

    await waitFor(async () => {
      expect((await bridge.loadDashboard()).settings).toMatchObject({
        telemetryEnabled: false,
        permissionMode: "always",
        providerEnv: { openrouter: "MY_OPENROUTER_KEY" },
      });
    });
  });

  it("switches to a validated Sleipnir run directory", async () => {
    const bridge = createDemoBridge();
    render(<App bridge={bridge} />);
    await screen.findByText("Local core connected");
    fireEvent.click(screen.getByRole("button", { name: "Advanced mode" }));
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    fireEvent.change(screen.getByLabelText("Project run directory"), { target: { value: "/runs/other" } });
    fireEvent.click(screen.getByRole("button", { name: "Open project" }));

    await waitFor(async () => expect((await bridge.loadDashboard()).run?.workspace).toBe("/runs/other"));
  });
});
