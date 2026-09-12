import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { SetupRequirement } from "../domain/types";
import { SetupView } from "../views/SetupView";

function requirement(overrides: Partial<SetupRequirement>): SetupRequirement {
  return {
    id: "x",
    label: "x",
    present: true,
    detail: "",
    fix: "",
    needsRoot: false,
    interactive: false,
    ...overrides,
  };
}

function harness(items: SetupRequirement[]) {
  return {
    probe: vi.fn().mockResolvedValue(items),
    apply: vi.fn().mockResolvedValue([]),
    models: vi.fn().mockResolvedValue({
      headroom: { freeGib: 7.5, totalGib: 8, device: "GPU", accelerated: true },
      options: [],
    }),
    pull: vi.fn().mockResolvedValue({ id: "model", ok: true, detail: "ready" }),
    onDone: vi.fn(),
  };
}

describe("SetupView", () => {
  it("offers the model instead of demanding an install when only the model is missing", async () => {
    // A local model is a choice about this machine's memory, not something a
    // command could fix in advance. Listing it as a missing item would leave
    // the wizard stuck: install runs nothing, the probe still reports a gap.
    const props = harness([
      requirement({ id: "ollama", label: "Ollama", present: true }),
      requirement({ id: "local-model", label: "Local assistant model", present: false, interactive: true }),
    ]);

    render(<SetupView {...props} />);

    await waitFor(() => expect(screen.getByText("Want a local model?")).toBeInTheDocument());
    expect(screen.queryByText(/Install the/)).not.toBeInTheDocument();
  });

  it("counts only the items a command can install", async () => {
    const props = harness([
      requirement({ id: "grim", label: "Screenshot tool", present: false, fix: "pacman -Syu grim", needsRoot: true }),
      requirement({ id: "local-model", label: "Local assistant model", present: false, interactive: true }),
    ]);

    render(<SetupView {...props} />);

    await waitFor(() => expect(screen.getByText(/Install the 1 missing item/)).toBeInTheDocument());
    expect(screen.getByText(/need administrator rights/)).toBeInTheDocument();
  });
});
