import type {
  FocusAgentEvent,
  FocusAgentStreamState,
  FocusAgentToolCallEvent,
  FocusAgentToolEvent,
} from "./types";
import { safeVisibleText } from "./toolProtocol";

export function createInitialStreamState(): FocusAgentStreamState {
  return {
    visibleText: "",
    reasoningText: "",
    toolCalls: [],
    toolEvents: [],
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

export function reduceStreamEvent(
  state: FocusAgentStreamState,
  event: FocusAgentEvent,
): FocusAgentStreamState {
  switch (event.event) {
    case "visible_text.delta":
    case "message.delta": {
      const delta = safeVisibleText(event.data.delta);
      return { ...state, visibleText: state.visibleText + delta };
    }
    case "visible_text.completed":
    case "message.completed": {
      const content =
        typeof event.data.content === "string"
          ? safeVisibleText(event.data.content)
          : state.visibleText;
      return { ...state, visibleText: content };
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
