import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { createDemoBridge } from "../bridge/demo";
import { App } from "./App";

describe("instruction escalation", () => {
  it("asks before handing project work to a higher tier and lets the operator force a route", async () => {
    const bridge = createDemoBridge();
    render(<App bridge={bridge} />);
    await screen.findByText("Local core connected");

    fireEvent.change(screen.getByLabelText("New instruction"), { target: { value: "Build and test the settings application" } });
    fireEvent.click(screen.getByRole("button", { name: "Start task" }));
    expect(await screen.findByRole("dialog", { name: "Choose a work lane" })).toBeVisible();
    expect(screen.getByText(/change the project/i)).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Use Codex" }));
    await waitFor(async () => {
      expect((await bridge.loadDashboard()).messages.at(-1)).toMatchObject({
        role: "sleipnir",
        route: "codex · approved",
      });
    });
  });
});
