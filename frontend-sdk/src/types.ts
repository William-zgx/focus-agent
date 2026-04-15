export type FocusAgentStreamChannel =
  | "visible_text"
  | "reasoning_tool_call"
  | "tool"
  | "system";

export type FocusAgentEventName =
  | "turn.status"
  | "turn.interrupt"
  | "turn.completed"
  | "turn.failed"
  | "turn.closed"
  | "visible_text.delta"
  | "visible_text.completed"
  | "message.delta"
  | "message.completed"
  | "reasoning.delta"
  | "reasoning.completed"
  | "tool_call.delta"
  | "tool.call.delta"
  | "tool.requested"
  | "tool.start"
  | "tool.delta"
  | "tool.end"
  | "tool.error"
  | "tool.result"
  | "task.update"
  | "task.started"
  | "task.finished"
  | "task.failed"
  | "agent.update"
  | "custom"
  | "status"
  | "stream.chunk";

export interface FocusAgentStreamMetadata {
  langgraph_node?: string;
  langgraph_path?: string | string[];
  langgraph_step?: number;
  tags?: string[];
  run_id?: string;
  model_name?: string;
  ls_provider?: string;
  [key: string]: unknown;
}

export interface FocusAgentBaseEventPayload {
  thread_id?: string;
  namespace?: string[];
  channel?: FocusAgentStreamChannel;
  metadata?: FocusAgentStreamMetadata;
  [key: string]: unknown;
}

export interface VisibleTextDeltaPayload extends FocusAgentBaseEventPayload {
  delta: string;
  channel: "visible_text";
}

export interface VisibleTextCompletedPayload extends FocusAgentBaseEventPayload {
  content: string;
}

export interface ReasoningDeltaPayload extends FocusAgentBaseEventPayload {
  delta: string;
  channel: "reasoning_tool_call";
}

export interface ReasoningCompletedPayload extends FocusAgentBaseEventPayload {
  content: string;
}

export interface ToolCallDeltaPayload extends FocusAgentBaseEventPayload {
  id?: string;
  name?: string;
  args_delta?: string;
  raw?: Record<string, unknown>;
  channel: "reasoning_tool_call";
}

export interface ToolRequestedPayload extends FocusAgentBaseEventPayload {
  node?: string;
  tool_name?: string;
  tool_call_id?: string;
  args?: unknown;
}

export interface ToolLifecyclePayload extends FocusAgentBaseEventPayload {
  event?: string;
  stage?: string;
  tool_name?: string;
  tool_call_id?: string;
  message?: string;
  output?: unknown;
}

export interface TurnStatusPayload extends FocusAgentBaseEventPayload {
  phase: string;
  kind?: string;
}

export interface TurnInterruptPayload extends FocusAgentBaseEventPayload {
  interrupt: unknown;
}

export interface TurnCompletedPayload extends FocusAgentBaseEventPayload {
  thread_state: Record<string, unknown>;
}

export interface TurnFailedPayload extends FocusAgentBaseEventPayload {
  error: string;
  message: string;
}

export interface TurnClosedPayload extends FocusAgentBaseEventPayload {
  status: string;
}

export interface AgentUpdatePayload extends FocusAgentBaseEventPayload {
  data: Record<string, unknown>;
}

export interface TaskPayload extends FocusAgentBaseEventPayload {
  event?: string;
  status?: string;
  value?: unknown;
}

export interface CustomPayload extends FocusAgentBaseEventPayload {
  value?: unknown;
}

export interface StreamChunkPayload extends FocusAgentBaseEventPayload {
  type?: string;
  data?: unknown;
}

export interface FocusAgentEventPayloadMap {
  "turn.status": TurnStatusPayload;
  "turn.interrupt": TurnInterruptPayload;
  "turn.completed": TurnCompletedPayload;
  "turn.failed": TurnFailedPayload;
  "turn.closed": TurnClosedPayload;
  "visible_text.delta": VisibleTextDeltaPayload;
  "visible_text.completed": VisibleTextCompletedPayload;
  "message.delta": VisibleTextDeltaPayload;
  "message.completed": VisibleTextCompletedPayload;
  "reasoning.delta": ReasoningDeltaPayload;
  "reasoning.completed": ReasoningCompletedPayload;
  "tool_call.delta": ToolCallDeltaPayload;
  "tool.call.delta": ToolCallDeltaPayload;
  "tool.requested": ToolRequestedPayload;
  "tool.start": ToolLifecyclePayload;
  "tool.delta": ToolLifecyclePayload;
  "tool.end": ToolLifecyclePayload;
  "tool.error": ToolLifecyclePayload;
  "tool.result": ToolLifecyclePayload;
  "task.update": TaskPayload;
  "task.started": TaskPayload;
  "task.finished": TaskPayload;
  "task.failed": TaskPayload;
  "agent.update": AgentUpdatePayload;
  "custom": CustomPayload;
  "status": CustomPayload;
  "stream.chunk": StreamChunkPayload;
}

export type FocusAgentEventPayload = FocusAgentEventPayloadMap[FocusAgentEventName];

export type FocusAgentEvent<K extends FocusAgentEventName = FocusAgentEventName> =
  K extends FocusAgentEventName
    ? {
        event: K;
        data: FocusAgentEventPayloadMap[K];
        raw?: string;
      }
    : never;

export interface FocusAgentTurnRequest {
  thread_id: string;
  message: string;
  model?: string;
  thinking_mode?: string;
  skill_hints?: string[];
}

export interface FocusAgentResumeRequest {
  thread_id: string;
  resume: unknown;
}

export interface FocusAgentDemoTokenRequest {
  user_id?: string;
  tenant_id?: string | null;
  scopes?: string[];
}

export interface FocusAgentTokenResponse {
  access_token: string;
  token_type: "bearer";
  expires_in_seconds: number;
  issuer: string;
}

export interface FocusAgentPrincipalResponse {
  user_id: string;
  tenant_id?: string | null;
  scopes: string[];
  auth_enabled: boolean;
}

export interface FocusAgentModelOption {
  id: string;
  provider: string;
  provider_label: string;
  name: string;
  label: string;
  is_default: boolean;
  supports_thinking: boolean;
  default_thinking_enabled: boolean;
}

export interface FocusAgentModelsResponse {
  default_model: string;
  models: FocusAgentModelOption[];
}

export type BranchRole = "main" | "explore_alternatives" | "deep_dive" | "verify" | "writeup";
export type BranchStatus =
  | "active"
  | "paused"
  | "awaiting_merge_review"
  | "merged"
  | "discarded"
  | "closed";
export type MergeMode = "none" | "summary_only" | "summary_plus_evidence" | "selected_artifacts";

export interface BranchMeta {
  branch_id: string;
  root_thread_id: string;
  parent_thread_id: string;
  return_thread_id: string;
  branch_name: string;
  branch_role: BranchRole;
  branch_depth: number;
  branch_status: BranchStatus;
  is_archived?: boolean;
  archived_at?: string | null;
  fork_checkpoint_id?: string | null;
  fork_strategy: string;
}

export interface BranchTreeNode {
  thread_id: string;
  root_thread_id: string;
  parent_thread_id?: string | null;
  branch_id?: string | null;
  branch_name: string;
  branch_role: BranchRole;
  branch_status: BranchStatus;
  is_archived?: boolean;
  archived_at?: string | null;
  branch_depth: number;
  fork_strategy?: string | null;
  children: BranchTreeNode[];
}

export interface BranchTreeResponse {
  root: BranchTreeNode;
  archived_branches: BranchTreeNode[];
}

export interface ThreadStateResponse {
  thread_id: string;
  root_thread_id: string;
  assistant_message?: string | null;
  rolling_summary: string;
  selected_model: string;
  selected_thinking_mode: string;
  branch_meta?: BranchMeta | null;
  merge_proposal?: Record<string, unknown> | null;
  merge_decision?: Record<string, unknown> | null;
  merge_queue: Array<Record<string, unknown>>;
  active_skill_ids: string[];
  messages: Array<Record<string, unknown>>;
  interrupts: unknown[];
  trace: Record<string, unknown>;
}

export type FocusAgentToolCallEvent =
  | FocusAgentEvent<"tool_call.delta">
  | FocusAgentEvent<"tool.call.delta">;

export type FocusAgentToolEvent =
  | FocusAgentEvent<"tool.requested">
  | FocusAgentEvent<"tool.start">
  | FocusAgentEvent<"tool.delta">
  | FocusAgentEvent<"tool.end">
  | FocusAgentEvent<"tool.error">
  | FocusAgentEvent<"tool.result">;

export interface FocusAgentStreamHandlers {
  onEvent?: (event: FocusAgentEvent) => void;
  onVisibleTextDelta?: (event: FocusAgentEvent<"visible_text.delta">) => void;
  onReasoningDelta?: (event: FocusAgentEvent<"reasoning.delta">) => void;
  onToolCallDelta?: (event: FocusAgentToolCallEvent) => void;
  onToolEvent?: (event: FocusAgentToolEvent) => void;
  onCompleted?: (event: FocusAgentEvent<"turn.completed">) => void;
  onFailed?: (event: FocusAgentEvent<"turn.failed">) => void;
}

export interface FocusAgentStreamState {
  visibleText: string;
  reasoningText: string;
  toolCalls: FocusAgentToolCallEvent[];
  toolEvents: FocusAgentToolEvent[];
  latestTurnState?: Record<string, unknown>;
  isClosed: boolean;
  failed?: TurnFailedPayload;
}
