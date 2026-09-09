import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { createDemoBridge } from "../bridge/demo";
import { App } from "./App";

describe("simple-mode navigation", () => {
  it("moves from command to the live run and selects a task", async () => {
    render(<App bridge={createDemoBridge()} />);

    await screen.findByRole("heading", { name: "Good evening." });
    fireEvent.click(screen.getByRole("button", { name: "Run" }));

    expect(await screen.findByRole("heading", { name: "The run, at a glance." })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /Connect live run projections/ }));
    expect(screen.getByRole("heading", { name: "Connect live run projections" })).toBeVisible();
    expect(screen.getByText("Reading plans and append-only events through one typed bridge.")).toBeVisible();
  });

  it("keeps operator machinery out of simple navigation", async () => {
    render(<App bridge={createDemoBridge()} />);
    await screen.findByText("Local core connected");

    expect(screen.queryByRole("button", { name: "Routing" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Audit" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Review" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Voice" })).toBeVisible();
  });

  it("submits a typed instruction through the shared bridge", async () => {
    const bridge = createDemoBridge();
    render(<App bridge={bridge} />);
    await screen.findByRole("heading", { name: "Good evening." });

    fireEvent.change(screen.getByLabelText("New instruction"), {
      target: { value: "Map this repository and continue the application" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Start task" }));

    expect((await bridge.loadDashboard()).messages.at(-1)?.text).toBe(
      "Map this repository and continue the application",
    );
  });
});
