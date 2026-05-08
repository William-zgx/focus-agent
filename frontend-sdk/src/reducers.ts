import type {
  FocusAgentEvent,
  FocusAgentEventName,
  FocusAgentStreamState,
  FocusAgentStreamStep,
  FocusAgentStreamStepStatus,
  FocusAgentToolCallEvent,
  FocusAgentToolEvent,
} from "./types.js";
import { safeVisibleText, safeVisibleTextTransition } from "./toolProtocol.js";

type InternalFocusAgentStreamState = FocusAgentStreamState & {
  _visibleTextPending?: string;
};

export function createInitialStreamState(): FocusAgentStreamState {
  return {
    visibleText: "",
    reasoningText: "",
    processingSteps: [],
    activePhase: undefined,
    toolCalls: [],
    toolEvents: [],
    interrupts: [],
    branchActions: [],
    latestTurnState: undefined,
    isClosed: false,
    failed: undefined,
  };
}

function upsertBranchAction(
  state: FocusAgentStreamState,
  action: FocusAgentStreamState["branchActions"][number] | null | undefined,
): FocusAgentStreamState {
  if (!action) return state;
  const existing = state.branchActions.filter((item) => item.action_id !== action.action_id);
  return { ...state, branchActions: [...existing, action] };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function stringifyValue(value: unknown): string | undefined {
  if (value === undefined || value === null) return undefined;
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function compactText(value: unknown, maxLength = 240): string | undefined {
  const text = stringifyValue(value)?.replace(/\s+/g, " ").trim();
  if (!text) return undefined;
  return text.length > maxLength ? `${text.slice(0, maxLength - 3)}...` : text;
}

function namespaceKey(namespace: string[] | undefined): string | undefined {
  return namespace && namespace.length > 0 ? namespace.join("/") : undefined;
}

function upsertProcessingStep(
  state: FocusAgentStreamState,
  step: FocusAgentStreamStep,
): FocusAgentStreamState {
  const index = state.processingSteps.findIndex(
    (item) => item.id === step.id && item.kind === step.kind,
  );
  if (index === -1) {
    return { ...state, processingSteps: [...state.processingSteps, step] };
  }
  const nextSteps = [...state.processingSteps];
  nextSteps[index] = { ...nextSteps[index], ...step };
  return { ...state, processingSteps: nextSteps };
}

function stepStatusForTask(
  eventName: FocusAgentEventName,
  payloadStatus: unknown,
): FocusAgentStreamStepStatus {
  if (eventName === "task.finished") return "completed";
  if (eventName === "task.failed") return "failed";
  if (eventName === "task.started") return "running";
  if (payloadStatus === "completed" || payloadStatus === "failed") {
    return payloadStatus;
  }
  if (payloadStatus === "running" || payloadStatus === "pending") {
    return payloadStatus;
  }
  return "running";
}

function stepStatusForToolEvent(eventName: FocusAgentEventName): FocusAgentStreamStepStatus {
  if (eventName === "tool.end" || eventName === "tool.result") return "completed";
  if (eventName === "tool.error") return "failed";
  if (eventName === "tool.requested") return "pending";
  return "running";
}

function toolNameForEvent(event: FocusAgentEvent): string | undefined {
  return stringValue(event.data.tool_name) ?? stringValue(event.data.name);
}

function toolStepIdForEvent(event: FocusAgentEvent): string {
  const data = event.data;
  const namespace = namespaceKey(data.namespace);
  const name = toolNameForEvent(event);
  return (
    stringValue(data.tool_call_id) ??
    stringValue(data.id) ??
    (namespace && name ? `${namespace}:${name}` : undefined) ??
    name ??
    namespace ??
    "tool"
  );
}

function upsertReasoningStep(
  state: FocusAgentStreamState,
  event: FocusAgentEvent<"reasoning.delta" | "reasoning.completed">,
  content: string,
  status: FocusAgentStreamStepStatus,
): FocusAgentStreamState {
  const namespace = namespaceKey(event.data.namespace);
  return upsertProcessingStep(state, {
    id: namespace ? `reasoning:${namespace}` : "reasoning",
    kind: "reasoning",
    label: "Reasoning",
    status,
    content,
    metadata: event.data.metadata,
    namespace: event.data.namespace,
    eventName: event.event,
  });
}

function upsertToolCallStep(
  state: FocusAgentStreamState,
  event: FocusAgentToolCallEvent,
): FocusAgentStreamState {
  const name = toolNameForEvent(event);
  const id = toolStepIdForEvent(event);
  const existing = state.processingSteps.find((step) => step.kind === "tool" && step.id === id);
  const argsDelta = stringValue(event.data.args_delta) ?? "";
  return upsertProcessingStep(state, {
    id,
    kind: "tool",
    label: name ?? existing?.label ?? "Tool call",
    status: existing?.status === "completed" || existing?.status === "failed" ? existing.status : "running",
    content: existing?.content,
    name: name ?? existing?.name,
    argsText: `${existing?.argsText ?? ""}${argsDelta}`,
    result: existing?.result,
    metadata: event.data.metadata,
    namespace: event.data.namespace,
    eventName: event.event,
  });
}

function upsertToolLifecycleStep(
  state: FocusAgentStreamState,
  event: FocusAgentToolEvent,
): FocusAgentStreamState {
  const name = toolNameForEvent(event);
  const id = toolStepIdForEvent(event);
  const existing = state.processingSteps.find((step) => step.kind === "tool" && step.id === id);
  const result = event.data.output ?? event.data.result;
  const summary =
    compactText(event.data.message) ??
    compactText(result) ??
    compactText(event.data.error);
  const argsText =
    event.event === "tool.requested"
      ? compactText(event.data.args) ?? existing?.argsText
      : existing?.argsText;
  return upsertProcessingStep(state, {
    id,
    kind: "tool",
    label: name ?? existing?.label ?? "Tool",
    status: stepStatusForToolEvent(event.event),
    content: summary ?? existing?.content,
    name: name ?? existing?.name,
    argsText,
    result: result ?? existing?.result,
    metadata: event.data.metadata,
    namespace: event.data.namespace,
    eventName: event.event,
  });
}

function upsertTaskStep(
  state: FocusAgentStreamState,
  event: FocusAgentEvent<"task.update" | "task.started" | "task.finished" | "task.failed">,
): FocusAgentStreamState {
  const data = event.data;
  const namespace = namespaceKey(data.namespace);
  const eventLabel = stringValue(data.event);
  const id =
    stringValue(data.id) ??
    (namespace && eventLabel ? `${namespace}:${eventLabel}` : undefined) ??
    namespace ??
    eventLabel ??
    "task";
  const label = stringValue(data.label) ?? eventLabel ?? "Task";
  return upsertProcessingStep(state, {
    id,
    kind: "task",
    label,
    status: stepStatusForTask(event.event, data.status),
    content: compactText(data.message) ?? compactText(data.value),
    metadata: data.metadata,
    namespace: data.namespace,
    eventName: event.event,
  });
}

function upsertAgentStep(
  state: FocusAgentStreamState,
  event: FocusAgentEvent<"agent.update">,
): FocusAgentStreamState {
  const data = event.data;
  const namespace = namespaceKey(data.namespace);
  const agentData = isRecord(data.data) ? data.data : {};
  const id =
    stringValue(agentData.id) ??
    stringValue(agentData.agent_id) ??
    stringValue(agentData.name) ??
    namespace ??
    "agent";
  const label = stringValue(agentData.label) ?? stringValue(agentData.name) ?? "Agent";
  const statusValue = agentData.status;
  const status =
    statusValue === "pending" ||
    statusValue === "running" ||
    statusValue === "completed" ||
    statusValue === "failed"
      ? statusValue
      : "running";
  return upsertProcessingStep(state, {
    id,
    kind: "agent",
    label,
    status,
    content: compactText(agentData.message) ?? compactText(agentData.summary),
    metadata: data.metadata,
    namespace: data.namespace,
    eventName: event.event,
  });
}

function failOpenProcessingSteps(state: FocusAgentStreamState): FocusAgentStreamStep[] {
  return state.processingSteps.map((step) =>
    step.status === "running" || step.status === "pending"
      ? { ...step, status: "failed", eventName: "turn.failed" }
      : step,
  );
}

function applyVisibleTextDelta(
  state: FocusAgentStreamState,
  value: unknown,
): FocusAgentStreamState {
  const internalState = state as InternalFocusAgentStreamState;
  const next = safeVisibleTextTransition(
    state.visibleText,
    value,
    internalState._visibleTextPending ?? "",
  );
  const updated: InternalFocusAgentStreamState = {
    ...state,
    visibleText: next.visibleText,
  };
  if (next.pendingText) {
    updated._visibleTextPending = next.pendingText;
  } else {
    delete updated._visibleTextPending;
  }
  return updated;
}

function applyVisibleTextCompleted(
  state: FocusAgentStreamState,
  value: unknown,
): FocusAgentStreamState {
  const updated: InternalFocusAgentStreamState = {
    ...state,
    visibleText: typeof value === "string" ? safeVisibleText(value) : state.visibleText,
  };
  delete updated._visibleTextPending;
  return updated;
}

export function reduceStreamEvent(
  state: FocusAgentStreamState,
  event: FocusAgentEvent,
): FocusAgentStreamState {
  switch (event.event) {
    case "visible_text.delta":
    case "message.delta": {
      return applyVisibleTextDelta(state, event.data.delta);
    }
    case "visible_text.completed":
    case "message.completed": {
      return applyVisibleTextCompleted(state, event.data.content);
    }
    case "reasoning.delta": {
      const delta = typeof event.data.delta === "string" ? event.data.delta : "";
      const reasoningText = state.reasoningText + delta;
      return upsertReasoningStep({ ...state, reasoningText }, event, reasoningText, "running");
    }
    case "reasoning.completed": {
      const content = typeof event.data.content === "string" ? event.data.content : state.reasoningText;
      return upsertReasoningStep({ ...state, reasoningText: content }, event, content, "completed");
    }
    case "tool_call.delta":
    case "tool.call.delta":
      return upsertToolCallStep(
        { ...state, toolCalls: [...state.toolCalls, event as FocusAgentToolCallEvent] },
        event as FocusAgentToolCallEvent,
      );
    case "tool.requested":
    case "tool.start":
    case "tool.delta":
    case "tool.end":
    case "tool.error":
    case "tool.result":
      return upsertToolLifecycleStep(
        { ...state, toolEvents: [...state.toolEvents, event as FocusAgentToolEvent] },
        event as FocusAgentToolEvent,
      );
    case "task.update":
    case "task.started":
    case "task.finished":
    case "task.failed":
      return upsertTaskStep(state, event);
    case "agent.update":
      return upsertAgentStep(state, event);
    case "branch.action.proposed":
    case "branch.action.executed":
    case "branch.action.dismissed":
    case "branch.action.failed":
      return upsertBranchAction(state, event.data.branch_action);
    case "turn.interrupt":
      return { ...state, interrupts: [...state.interrupts, event.data.interrupt] };
    case "turn.status":
      return { ...state, activePhase: event.data.phase };
    case "turn.completed":
      return {
        ...state,
        latestTurnState: (event.data.thread_state as Record<string, unknown>) ?? state.latestTurnState,
      };
    case "turn.failed":
      return {
        ...state,
        processingSteps: failOpenProcessingSteps(state),
        activePhase: "failed",
        failed: event.data,
        isClosed: true,
      };
    case "turn.closed":
      return { ...state, isClosed: true };
    default:
      return state;
  }
}
