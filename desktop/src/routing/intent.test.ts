import { describe, expect, it } from "vitest";

import { classifyInstruction } from "./intent";

describe("desktop instruction routing", () => {
  it("keeps small questions cheap and proposes escalation for project work", () => {
    expect(classifyInstruction("What is running right now?").kind).toBe("ambient");
    expect(classifyInstruction("Build and test the full-stack application")).toMatchObject({
      kind: "confirm",
      recommended: "claude",
    });
  });
});
