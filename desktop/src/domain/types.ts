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
  /** What the assistant calls you. Preference data, never a credential. */
  operatorName: string;
  localWake: boolean;
  listeningEnabled: boolean;
  startAtLogin: boolean;
  pushToTalkShortcut: string;
  transcription: "local" | "gemini";
  ambientProvider: "auto" | "ollama" | "gemini" | "openrouter" | "nvidia-nim";
  responseModel: string;
  escalation: "automatic" | "confirm";
  voiceProvider: "system" | "gemini" | "openrouter";
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
  /** Serve the LAN phone hub. Off by default: it binds every interface. */
  hubEnabled: boolean;
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
  providers: Record<"ollama" | "openrouter" | "gemini" | "nvidia", boolean>;
}

export type ReviewDecision = "approve" | "request_changes" | "reject";

export interface AgentResponse {
  status: "complete" | "approval";
  text: string;
  route: string;
  rationale: string;
  sessionId: string | null;
}

export interface SpeechAudio {
  data: string;
  mimeType: string;
}

/** One thing a fresh install still needs, and the command that supplies it. */
export interface SetupRequirement {
  id: string;
  label: string;
  present: boolean;
  detail: string;
  fix: string;
  needsRoot: boolean;
  /** The wizard resolves this by asking, not by running `fix`. */
  interactive: boolean;
}

export interface SetupStepResult {
  id: string;
  ok: boolean;
  detail: string;
}

export interface LocalModelOption {
  tier: "low" | "moderate" | "high";
  model: string;
  /** Live from Ollama's registry, or "unknown" when it could not be read. */
  download: string;
  fits: boolean;
  note: string;
}

export interface LocalModelReport {
  headroom: { freeGib: number; totalGib: number; device: string; accelerated: boolean };
  options: LocalModelOption[];
}

export interface HubPairing {
  running: boolean;
  address: string;
  /** Shown on the operator's own screen only; never stored in a snapshot. */
  token: string;
}
