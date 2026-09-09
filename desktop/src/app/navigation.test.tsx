import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

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

    expect(await screen.findByRole("dialog", { name: "Choose a work lane" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Use Codex" }));
    await waitFor(async () => {
      expect((await bridge.loadDashboard()).messages.at(-2)).toMatchObject({
        role: "operator",
        text: "Map this repository and continue the application",
      });
    });
  });

  it("creates the first project when the selected workspace has no plan", async () => {
    const bridge = createDemoBridge();
    const loadDashboard = bridge.loadDashboard;
    const startProject = vi.fn(async () => {});
    bridge.loadDashboard = async () => ({ ...(await loadDashboard()), run: null, tasks: [], routes: [] });
    bridge.startProject = startProject;
    render(<App bridge={bridge} />);
    await screen.findByRole("heading", { name: "Good evening." });

    fireEvent.change(screen.getByLabelText("New instruction"), {
      target: { value: "Build a private project dashboard" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create project" }));

    await waitFor(() => expect(startProject).toHaveBeenCalledWith("Build a private project dashboard"));
  });
});
