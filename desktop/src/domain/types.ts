export type TaskState =
  | "pending"
  | "ready"
  | "running"
  | "review"
  | "done"
  | "failed"
  | "blocked"
  | "skipped"
  | "partial"
  | "stale"
  | "superseded"
  | "cancelled";

export type Tier = "mechanical" | "code" | "extract" | "longctx" | "reason" | "control";
export type ColorScheme = "orbit" | "index" | "glasshouse";
export type VoicePhase =
  | "off"
  | "armed"
  | "hearing"
  | "thinking"
  | "acting"
  | "approval"
  | "speaking"
  | "error";

export interface RuntimeStatus {
  connected: boolean;
  label: string;
  version: string;
  platform: string;
}

export interface RunSummary {
  id: string;
  name: string;
  goal: string;
  state: "idle" | "planning" | "running" | "review" | "complete" | "blocked";
  revision: number;
  progress: number;
  manifestTokens: number;
  startedAt: string;
  workspace: string;
}

export interface TaskSummary {
  id: string;
  title: string;
  state: TaskState;
  tier: Tier;
  model: string | null;
  group: string;
  progress: number;
  dependsOn: string[];
  attempt: number;
  maxAttempts: number;
  summary: string;
  checks: string[];
}

export interface RouteDecision {
  taskId: string;
  tier: Tier;
  provider: "claude" | "codex" | "openrouter" | "anthropic" | "compatible";
  model: string;
  costLabel: string;
  latencyLabel: string;
  rationale: string;
  status: "selected" | "available" | "unavailable";
}

export interface BudgetPool {
  id: string;
  label: string;
  kind: "window" | "metered" | "notional" | "tokens";
  used: number;
  limit: number | null;
  unit: string;
  resetsAt: string | null;
}

export interface TimelineEvent {
  id: string;
  at: string;
  kind:
    | "dispatch_started"
    | "task_completed"
    | "gate_requested"
    | "revision_applied"
    | "route_changed"
    | "capability_used"
    | "recovery";
  title: string;
  detail: string;
  taskId: string | null;
  tone: "live" | "success" | "warning" | "neutral";
}

export interface ReviewItem {
  id: string;
  taskId: string;
  title: string;
  summary: string;
  files: Array<{ path: string; additions: number; deletions: number }>;
  checks: Array<{ label: string; status: "passed" | "failed" | "pending" }>;
  risk: "low" | "medium" | "high";
}

export interface CapabilitySummary {
  id: "computer" | "browser" | "clipboard" | "credentials" | "ios" | "party";
  label: string;
  detail: string;
  state: "ready" | "limited" | "off";
  audited: boolean;
}

export interface AuditEvent {
  id: string;
  at: string;
  actor: "operator" | "sleipnir" | "worker";
  action: string;
  scope: string;
  result: "allowed" | "refused" | "complete";
}

export interface ConversationMessage {
  id: string;
  at: string;
  role: "operator" | "sleipnir" | "tool";
  text: string;
  route?: string;
}

export interface VoiceSettings {
  wakeName: string;
  localWake: boolean;
  startAtLogin: boolean;
  pushToTalkShortcut: string;
  transcription: "local" | "gemini";
  responseModel: string;
  escalation: "automatic" | "confirm";
  voiceProvider: "system" | "gemini" | "openrouter" | "elevenlabs";
  voiceId: string;
  accent: "neutral" | "american" | "british" | "australian" | "indian";
  interruptible: boolean;
}

export interface VoiceStatus {
  phase: VoicePhase;
  heard: string;
  level: number;
  privacyLabel: string;
  settings: VoiceSettings;
}

export interface AppSettings {
  colorScheme: ColorScheme;
  adaptiveScheme: boolean;
  advancedModules: Record<"mission" | "chronicle" | "helm" | "tools" | "audit", boolean>;
  telemetryEnabled: boolean;
  permissionMode: "ask" | "always";
  providerEnv: {
    openrouter: string;
    gemini: string;
    nvidia: string;
  };
}

export interface DashboardSnapshot {
  source: "demo" | "core";
  generatedAt: string;
  runtime: RuntimeStatus;
  run: RunSummary | null;
  tasks: TaskSummary[];
  routes: RouteDecision[];
  budgets: BudgetPool[];
  timeline: TimelineEvent[];
  reviews: ReviewItem[];
  capabilities: CapabilitySummary[];
  audit: AuditEvent[];
  messages: ConversationMessage[];
  voice: VoiceStatus;
  settings: AppSettings;
}

export type ReviewDecision = "approve" | "request_changes" | "reject";
