import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { App } from "./App";

describe("Sleipnir desktop shell", () => {
  it("opens as a live Orbit workspace in simple mode", async () => {
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Good evening." })).toBeVisible();
    expect(screen.getByLabelText("Color scheme")).toHaveValue("orbit");
    expect(screen.getByRole("button", { name: "Advanced mode" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(screen.getByText("Local core connected")).toBeVisible();
  });
});
