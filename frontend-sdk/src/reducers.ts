import type {
  FocusAgentEvent,
  FocusAgentEventName,
  FocusAgentStreamState,
  FocusAgentStreamStep,
	FocusAgentStreamStepStatus,
	FocusAgentToolCallEvent,
	FocusAgentToolEvent,
	FocusAgentRuntimeOutcome,
} from "./types.js";
import { safeVisibleText, safeVisibleTextTransition } from "./toolProtocol.js";

type InternalFocusAgentStreamState = FocusAgentStreamState & {
  _visibleTextPending?: string;
  _reasoningTextPending?: string;
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
		taskOutcome: null,
		runtimeOutcome: null,
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
  if (!safeVisibleText(text)) return undefined;
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

function stepStatusForTask(data: Record<string, unknown>): FocusAgentStreamStepStatus {
  const payloadStatus = data.status;
  if (payloadStatus === "completed" || payloadStatus === "failed") {
    return payloadStatus;
  }
  if (payloadStatus === "running" || payloadStatus === "pending") {
    return payloadStatus;
  }
  if ("error" in data && data.error !== null && data.error !== undefined) {
    return "failed";
  }
  if ("result" in data || data.error === null) {
    return "completed";
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
	const toolOutcome =
		typeof event.data.tool_outcome === "object" &&
		event.data.tool_outcome !== null
			? (event.data.tool_outcome as FocusAgentRuntimeOutcome)
			: null;
	const runtime =
		typeof event.data.runtime === "object" && event.data.runtime !== null
			? (event.data.runtime as Record<string, unknown>)
			: undefined;
	const summary =
		compactText(event.data.message) ??
		compactText(result) ??
    compactText(event.data.error);
	const existingHistory = existing?.toolOutcomeHistory ?? [];
	const toolOutcomeHistory = toolOutcome
		? [
				...existingHistory.filter(
					(item) =>
						!item.outcome_id ||
						!toolOutcome.outcome_id ||
						item.outcome_id !== toolOutcome.outcome_id,
				),
				toolOutcome,
			]
		: existingHistory;
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
		runtime: runtime ?? existing?.runtime,
		toolOutcome: toolOutcome ?? existing?.toolOutcome,
		toolOutcomeHistory,
	});
}

function upsertTaskStep(
  state: FocusAgentStreamState,
  event: FocusAgentEvent<"task.update">,
): FocusAgentStreamState {
  const data = event.data;
  const namespace = namespaceKey(data.namespace);
  const eventLabel = stringValue(data.event);
  const taskName = stringValue(data.name);
  const id =
    stringValue(data.id) ??
    (namespace && eventLabel ? `${namespace}:${eventLabel}` : undefined) ??
    namespace ??
    taskName ??
    eventLabel ??
    "task";
  const label = stringValue(data.label) ?? taskName ?? eventLabel ?? "Task";
  return upsertProcessingStep(state, {
    id,
    kind: "task",
    label,
    status: stepStatusForTask(data),
    content: compactText(data.message) ?? compactText(data.value),
    name: taskName,
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

function applyReasoningDelta(
  state: FocusAgentStreamState,
  event: FocusAgentEvent<"reasoning.delta">,
): FocusAgentStreamState {
  const internalState = state as InternalFocusAgentStreamState;
  const delta = typeof event.data.delta === "string" ? event.data.delta : "";
  const completed = event.data.completed === true;

  let updated: InternalFocusAgentStreamState;
  if (completed) {
    updated = {
      ...state,
      reasoningText:
        typeof event.data.content === "string"
          ? safeVisibleText(event.data.content)
          : state.reasoningText,
    };
    delete updated._reasoningTextPending;
  } else {
    const next = safeVisibleTextTransition(
      state.reasoningText,
      delta,
      internalState._reasoningTextPending ?? "",
    );
    updated = {
      ...state,
      reasoningText: next.visibleText,
    };
    if (next.pendingText) {
      updated._reasoningTextPending = next.pendingText;
    } else {
      delete updated._reasoningTextPending;
    }
  }

  if (!updated.reasoningText.trim()) {
    return updated;
  }
  return upsertReasoningStep(
    updated,
    event,
    updated.reasoningText,
    completed ? "completed" : "running",
  );
}

export function reduceStreamEvent(
  state: FocusAgentStreamState,
  event: FocusAgentEvent,
): FocusAgentStreamState {
	const runtimeOutcomeValue = (
		value: unknown,
	): FocusAgentRuntimeOutcome | null =>
		typeof value === "object" && value !== null
			? (value as FocusAgentRuntimeOutcome)
			: null;
	const threadStateValue = (data: Record<string, unknown>) =>
		typeof data.thread_state === "object" && data.thread_state !== null
			? (data.thread_state as Record<string, unknown>)
			: undefined;
	const terminalTaskOutcome = (data: Record<string, unknown>) => {
		const threadState = threadStateValue(data);
		return (
			runtimeOutcomeValue(data.task_outcome) ??
			runtimeOutcomeValue(threadState?.task_outcome)
		);
	};
	const terminalRuntimeOutcome = (data: Record<string, unknown>) => {
		const threadState = threadStateValue(data);
		return (
			runtimeOutcomeValue(data.task_outcome) ??
			runtimeOutcomeValue(threadState?.task_outcome) ??
			runtimeOutcomeValue(data.runtime_outcome) ??
			runtimeOutcomeValue(threadState?.runtime_outcome)
		);
	};

	switch (event.event) {
    case "message.delta": {
      return applyVisibleTextDelta(state, event.data.delta);
    }
	case "message.completed": {
		const updated = applyVisibleTextCompleted(state, event.data.content);
		const taskOutcome = runtimeOutcomeValue(event.data.task_outcome);
		const runtimeOutcome = taskOutcome ?? runtimeOutcomeValue(event.data.runtime_outcome);
		return {
			...updated,
			taskOutcome: taskOutcome ?? updated.taskOutcome,
			runtimeOutcome: runtimeOutcome ?? updated.runtimeOutcome,
		};
	}
    case "reasoning.delta": {
      return applyReasoningDelta(state, event as FocusAgentEvent<"reasoning.delta">);
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
			taskOutcome:
				terminalTaskOutcome(event.data) ??
				state.taskOutcome,
			runtimeOutcome:
				terminalRuntimeOutcome(event.data) ??
				state.runtimeOutcome,
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
			latestTurnState: event.data.thread_state ?? state.latestTurnState,
			taskOutcome:
				terminalTaskOutcome(event.data) ??
				state.taskOutcome,
			runtimeOutcome:
				terminalRuntimeOutcome(event.data) ??
				state.runtimeOutcome,
			isClosed: true,
		};
    case "run.closed":
      return { ...state, isClosed: true };
    default:
      return state;
  }
}
