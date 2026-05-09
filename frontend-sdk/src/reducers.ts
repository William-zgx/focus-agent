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

function stepStatusForTask(payloadStatus: unknown): FocusAgentStreamStepStatus {
  if (payloadStatus === "completed" || payloadStatus === "failed") {
    return payloadStatus;
  }
  if (payloadStatus === "running" || payloadStatus === "pending") {
    return payloadStatus;
  }
  return "running";
}

function stepStatusForToolEvent(eventName: FocusAgentEventName): FocusAgentStreamStepStatus {
  if (eventName === "tool.result") return "completed";
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
  event: FocusAgentEvent<"reasoning.delta">,
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
  const result = event.data.output ?? event.data.result ?? event.data.content;
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
  event: FocusAgentEvent<"task.update">,
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
    status: stepStatusForTask(data.status),
    content: compactText(data.message) ?? compactText(data.value),
    metadata: data.metadata,
    namespace: data.namespace,
    eventName: event.event,
  });
}

function failOpenProcessingSteps(state: FocusAgentStreamState): FocusAgentStreamStep[] {
  return state.processingSteps.map((step) =>
    step.status === "running" || step.status === "pending"
      ? { ...step, status: "failed", eventName: "run.failed" }
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
    case "message.delta": {
      return applyVisibleTextDelta(state, event.data.delta);
    }
    case "message.completed": {
      return applyVisibleTextCompleted(state, event.data.content);
    }
    case "reasoning.delta": {
      const delta = typeof event.data.delta === "string" ? event.data.delta : "";
      const completed = event.data.completed === true;
      const reasoningText =
        completed && typeof event.data.content === "string"
          ? event.data.content
          : state.reasoningText + delta;
      return upsertReasoningStep(
        { ...state, reasoningText },
        event,
        reasoningText,
        completed ? "completed" : "running",
      );
    }
    case "tool.call.delta":
      return upsertToolCallStep(
        { ...state, toolCalls: [...state.toolCalls, event as FocusAgentToolCallEvent] },
        event as FocusAgentToolCallEvent,
      );
    case "tool.requested":
    case "tool.error":
    case "tool.result":
      return upsertToolLifecycleStep(
        { ...state, toolEvents: [...state.toolEvents, event as FocusAgentToolEvent] },
        event as FocusAgentToolEvent,
      );
    case "task.update":
      return upsertTaskStep(state, event);
    case "run.status":
      return { ...state, activePhase: event.data.phase };
    case "run.completed":
      return {
        ...state,
        activePhase: event.data.status,
        latestTurnState: event.data.thread_state ?? state.latestTurnState,
        isClosed: true,
      };
    case "run.interrupt":
      return { ...state, activePhase: event.data.action };
    case "run.failed":
      return {
        ...state,
        processingSteps: failOpenProcessingSteps(state),
        activePhase: "failed",
        failed: event.data,
        isClosed: true,
      };
    case "run.closed":
      return { ...state, isClosed: true };
    default:
      return state;
  }
}
