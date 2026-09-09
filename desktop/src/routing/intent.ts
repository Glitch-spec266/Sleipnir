export type InstructionRoute = "ambient" | "claude" | "codex";

export type InstructionDecision =
  | { kind: "ambient"; recommended: "ambient"; reason: string }
  | { kind: "confirm"; recommended: "claude" | "codex"; reason: string };

const work = /\b(build|implement|fix|refactor|debug|deploy|release|install|configure|test|commit|push|edit|write|create|redesign|research|presentation|slides|full[ -]?stack|repository|codebase|project)\b/i;
const deep = /\b(architecture|security|migration|production|multi[ -]?stage|thorough|investigate|root cause|autonomous|entire|everything|full[ -]?stack)\b/i;

export function classifyInstruction(text: string): InstructionDecision {
  const clean = text.trim();
  if (work.test(clean)) {
    return {
      kind: "confirm",
      recommended: deep.test(clean) || clean.length > 240 ? "claude" : "codex",
      reason: "This can change the project or host, so Sleipnir recommends a capable work lane.",
    };
  }
  return {
    kind: "ambient",
    recommended: "ambient",
    reason: "This can stay on the fast conversational lane.",
  };
}
