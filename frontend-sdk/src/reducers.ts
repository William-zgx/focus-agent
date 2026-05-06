import type {
  FocusAgentEvent,
  FocusAgentStreamState,
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
      return { ...state, reasoningText: state.reasoningText + delta };
    }
    case "reasoning.completed": {
      const content = typeof event.data.content === "string" ? event.data.content : state.reasoningText;
      return { ...state, reasoningText: content };
    }
    case "tool_call.delta":
    case "tool.call.delta":
      return { ...state, toolCalls: [...state.toolCalls, event as FocusAgentToolCallEvent] };
    case "tool.requested":
    case "tool.start":
    case "tool.delta":
    case "tool.end":
    case "tool.error":
    case "tool.result":
      return { ...state, toolEvents: [...state.toolEvents, event as FocusAgentToolEvent] };
    case "branch.action.proposed":
    case "branch.action.executed":
    case "branch.action.dismissed":
    case "branch.action.failed":
      return upsertBranchAction(state, event.data.branch_action);
    case "turn.interrupt":
      return { ...state, interrupts: [...state.interrupts, event.data.interrupt] };
    case "turn.completed":
      return {
        ...state,
        latestTurnState: (event.data.thread_state as Record<string, unknown>) ?? state.latestTurnState,
      };
    case "turn.failed":
      return { ...state, failed: event.data, isClosed: true };
    case "turn.closed":
      return { ...state, isClosed: true };
    default:
      return state;
  }
}
