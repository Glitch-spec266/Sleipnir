import { describe, expect, it } from "vitest";

import { createDemoBridge } from "./demo";

describe("demo bridge", () => {
  it("projects every operator surface from one snapshot", async () => {
    const bridge = createDemoBridge();
    const snapshot = await bridge.loadDashboard();

    expect(snapshot.source).toBe("demo");
    expect(snapshot.run?.state).toBe("running");
    expect(snapshot.tasks.some((task) => task.state === "running")).toBe(true);
    expect(snapshot.routes[0]?.rationale).toContain("subscription");
    expect(snapshot.budgets.map((budget) => budget.kind)).toEqual(
      expect.arrayContaining(["window", "notional"]),
    );
    expect(snapshot.timeline[0]?.kind).toBe("dispatch_started");
    expect(snapshot.capabilities.some((capability) => capability.id === "computer")).toBe(true);
    expect(snapshot.voice.phase).toBe("armed");
  });

  it("updates voice state and appends operator messages", async () => {
    const bridge = createDemoBridge();

    await bridge.setListening(false);
    await bridge.sendMessage("Prepare the release notes");
    const snapshot = await bridge.loadDashboard();

    expect(snapshot.voice.phase).toBe("off");
    expect(snapshot.messages.at(-1)).toMatchObject({
      role: "operator",
      text: "Prepare the release notes",
    });
  });
});
