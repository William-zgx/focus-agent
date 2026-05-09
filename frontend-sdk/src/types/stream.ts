import type {
  FocusAgentBranchActionNavigation,
  FocusAgentBranchActionProposal,
  FocusAgentBranchRecord,
} from "./branch.js";

export type FocusAgentStreamChannel =
  | "message"
  | "reasoning_tool_call"
  | "tool"
  | "system";

export type FocusAgentEventName =
  | "run.metadata"
  | "run.status"
  | "run.completed"
  | "run.failed"
  | "run.interrupt"
  | "run.closed"
  | "heartbeat"
  | "state.update"
  | "message.delta"
  | "message.completed"
  | "reasoning.delta"
  | "tool.call.delta"
  | "tool.requested"
  | "tool.error"
  | "tool.result"
  | "task.update";

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

export interface MessageDeltaPayload extends FocusAgentBaseEventPayload {
  delta: string;
  channel?: "message";
  message_id?: string;
}

export interface MessageCompletedPayload extends FocusAgentBaseEventPayload {
  content: string;
  message_id?: string;
  source?: string;
}

export interface ReasoningDeltaPayload extends FocusAgentBaseEventPayload {
  delta: string;
  channel?: "reasoning_tool_call";
  completed?: boolean;
  content?: string;
}

export interface ToolCallDeltaPayload extends FocusAgentBaseEventPayload {
  id?: string;
  name?: string;
  args_delta?: string;
  raw?: Record<string, unknown>;
  channel?: "reasoning_tool_call";
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

export interface RunMetadataPayload extends FocusAgentBaseEventPayload {
  run_id?: string;
  turn_id?: string;
  sequence?: number;
  source_node?: string;
}

export interface RunStatusPayload extends FocusAgentBaseEventPayload {
  run_id?: string;
  turn_id?: string;
  sequence?: number;
  source_node?: string;
  phase: string;
}

export interface RunCompletedPayload extends FocusAgentBaseEventPayload {
  run_id?: string;
  turn_id?: string;
  sequence?: number;
  source_node?: string;
  status: string;
  thread_state?: Record<string, unknown>;
  branch_action?: FocusAgentBranchActionProposal | null;
  branch_record?: FocusAgentBranchRecord | null;
  navigation?: FocusAgentBranchActionNavigation | null;
}

export interface RunFailedPayload extends FocusAgentBaseEventPayload {
  run_id?: string;
  turn_id?: string;
  sequence?: number;
  source_node?: string;
  error: string;
  message: string;
}

export interface RunInterruptPayload extends FocusAgentBaseEventPayload {
  run_id?: string;
  turn_id?: string;
  sequence?: number;
  source_node?: string;
  action: string;
  message?: string;
}

export interface RunClosedPayload extends FocusAgentBaseEventPayload {
  run_id?: string;
  turn_id?: string;
  sequence?: number;
  source_node?: string;
  status: string;
}

export interface TaskPayload extends FocusAgentBaseEventPayload {
  event?: string;
  status?: string;
  value?: unknown;
}

export interface StreamChunkPayload extends FocusAgentBaseEventPayload {
  type?: string;
  data?: unknown;
}

export interface FocusAgentEventPayloadMap {
  "run.metadata": RunMetadataPayload;
  "run.status": RunStatusPayload;
  "run.completed": RunCompletedPayload;
  "run.failed": RunFailedPayload;
  "run.interrupt": RunInterruptPayload;
  "run.closed": RunClosedPayload;
  "heartbeat": RunMetadataPayload;
  "state.update": StreamChunkPayload;
  "message.delta": MessageDeltaPayload;
  "message.completed": MessageCompletedPayload;
  "reasoning.delta": ReasoningDeltaPayload;
  "tool.call.delta": ToolCallDeltaPayload;
  "tool.requested": ToolRequestedPayload;
  "tool.error": ToolLifecyclePayload;
  "tool.result": ToolLifecyclePayload;
  "task.update": TaskPayload;
}

export type FocusAgentEventPayload = FocusAgentEventPayloadMap[FocusAgentEventName];

export type FocusAgentStreamStepStatus = "pending" | "running" | "completed" | "failed";

export interface FocusAgentStreamStepBase {
  id: string;
  kind: "reasoning" | "tool" | "task" | "agent";
  label: string;
  status: FocusAgentStreamStepStatus;
  content?: string;
  name?: string;
  argsText?: string;
  result?: unknown;
  metadata?: FocusAgentStreamMetadata;
  namespace?: string[];
  eventName?: FocusAgentEventName;
}

export interface FocusAgentReasoningStreamStep extends FocusAgentStreamStepBase {
  kind: "reasoning";
}

export interface FocusAgentToolStreamStep extends FocusAgentStreamStepBase {
  kind: "tool";
}

export interface FocusAgentTaskStreamStep extends FocusAgentStreamStepBase {
  kind: "task";
}

export interface FocusAgentAgentStreamStep extends FocusAgentStreamStepBase {
  kind: "agent";
}

export type FocusAgentStreamStep =
  | FocusAgentReasoningStreamStep
  | FocusAgentToolStreamStep
  | FocusAgentTaskStreamStep
  | FocusAgentAgentStreamStep;

export type FocusAgentEvent<K extends FocusAgentEventName = FocusAgentEventName> =
  K extends FocusAgentEventName
    ? {
        event: K;
        data: FocusAgentEventPayloadMap[K];
        raw?: string;
      }
    : never;

export type FocusAgentToolCallEvent = FocusAgentEvent<"tool.call.delta">;

export type FocusAgentToolEvent =
  | FocusAgentEvent<"tool.requested">
  | FocusAgentEvent<"tool.error">
  | FocusAgentEvent<"tool.result">;

export interface FocusAgentStreamHandlers {
  onEvent?: (event: FocusAgentEvent) => void;
  onMessageDelta?: (event: FocusAgentEvent<"message.delta">) => void;
  onReasoningDelta?: (event: FocusAgentEvent<"reasoning.delta">) => void;
  onToolCallDelta?: (event: FocusAgentToolCallEvent) => void;
  onToolEvent?: (event: FocusAgentToolEvent) => void;
  onCompleted?: (event: FocusAgentEvent<"run.completed">) => void;
  onFailed?: (event: FocusAgentEvent<"run.failed">) => void;
}

export interface FocusAgentStreamState {
  visibleText: string;
  reasoningText: string;
  processingSteps: FocusAgentStreamStep[];
  activePhase?: string;
  toolCalls: FocusAgentToolCallEvent[];
  toolEvents: FocusAgentToolEvent[];
  interrupts: unknown[];
  branchActions: FocusAgentBranchActionProposal[];
  latestTurnState?: Record<string, unknown>;
  isClosed: boolean;
  failed?: RunFailedPayload;
}
