import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { createDemoBridge } from "../bridge/demo";
import { App } from "./App";

describe("advanced mode", () => {
  it("reveals Mission, Chronicle, and Helm operator surfaces on demand", async () => {
    render(<App bridge={createDemoBridge()} />);
    await screen.findByText("Local core connected");

    expect(screen.queryByRole("button", { name: "Chronicle" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Advanced mode" }));

    expect(screen.getByRole("button", { name: "Console" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Chronicle" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Routing" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Trust" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Settings" })).toBeVisible();
  });

  it("navigates to provenance and route rationale", async () => {
    render(<App bridge={createDemoBridge()} />);
    await screen.findByText("Local core connected");
    fireEvent.click(screen.getByRole("button", { name: "Advanced mode" }));

    fireEvent.click(screen.getByRole("button", { name: "Chronicle" }));
    expect(screen.getByRole("heading", { name: "Everything that happened." })).toBeVisible();
    expect(screen.getByText("Bridge implementation started")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Routing" }));
    expect(screen.getByRole("heading", { name: "Every route, explained." })).toBeVisible();
    expect(screen.getByText(/fixed dispatch cost is already amortized/i)).toBeVisible();
  });

  it("shows granular advanced controls in settings", async () => {
    render(<App bridge={createDemoBridge()} />);
    await screen.findByText("Local core connected");
    fireEvent.click(screen.getByRole("button", { name: "Advanced mode" }));
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));

    expect(screen.getByRole("heading", { name: "Advanced is yours to tune." })).toBeVisible();
    expect(screen.getByRole("checkbox", { name: "Mission work queue" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Chronicle history" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Helm system signals" })).toBeChecked();
  });
});
