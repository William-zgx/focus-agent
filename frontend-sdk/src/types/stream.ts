import type {
  FocusAgentBranchActionNavigation,
  FocusAgentBranchActionProposal,
  FocusAgentBranchRecord,
} from "./branch.js";

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
  | "branch.action.proposed"
  | "branch.action.executed"
  | "branch.action.dismissed"
  | "branch.action.failed"
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

export interface BranchActionPayload extends FocusAgentBaseEventPayload {
  branch_action?: FocusAgentBranchActionProposal | null;
  branch_record?: FocusAgentBranchRecord | null;
  navigation?: FocusAgentBranchActionNavigation | null;
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
  "branch.action.proposed": BranchActionPayload;
  "branch.action.executed": BranchActionPayload;
  "branch.action.dismissed": BranchActionPayload;
  "branch.action.failed": BranchActionPayload;
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
  processingSteps: FocusAgentStreamStep[];
  activePhase?: string;
  toolCalls: FocusAgentToolCallEvent[];
  toolEvents: FocusAgentToolEvent[];
  interrupts: unknown[];
  branchActions: FocusAgentBranchActionProposal[];
  latestTurnState?: Record<string, unknown>;
  isClosed: boolean;
  failed?: TurnFailedPayload;
}
