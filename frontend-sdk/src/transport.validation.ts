import type { FocusAgentEvent, FocusAgentEventName, FocusAgentEventPayload } from "./types.js";

const KNOWN_EVENT_NAMES = new Set<FocusAgentEventName>([
  "turn.status",
  "turn.interrupt",
  "turn.completed",
  "turn.failed",
  "turn.closed",
  "branch.action.proposed",
  "branch.action.executed",
  "branch.action.dismissed",
  "branch.action.failed",
  "visible_text.delta",
  "visible_text.completed",
  "message.delta",
  "message.completed",
  "reasoning.delta",
  "reasoning.completed",
  "tool_call.delta",
  "tool.call.delta",
  "tool.requested",
  "tool.start",
  "tool.delta",
  "tool.end",
  "tool.error",
  "tool.result",
  "task.update",
  "task.started",
  "task.finished",
  "task.failed",
  "agent.update",
  "custom",
  "status",
  "stream.chunk",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasString(value: Record<string, unknown>, key: string): boolean {
  return typeof value[key] === "string";
}

export function isFocusAgentEventName(value: string): value is FocusAgentEventName {
  return KNOWN_EVENT_NAMES.has(value as FocusAgentEventName);
}

export function validateFocusAgentEventPayload(
  eventName: FocusAgentEventName,
  payload: unknown,
): payload is FocusAgentEventPayload {
  if (!isRecord(payload)) {
    return false;
  }

  switch (eventName) {
    case "visible_text.delta":
    case "message.delta":
      return hasString(payload, "delta");
    case "reasoning.delta":
      return hasString(payload, "delta");
    case "tool_call.delta":
    case "tool.call.delta":
      return (
        (payload.id === undefined || typeof payload.id === "string") &&
        (payload.name === undefined || typeof payload.name === "string") &&
        (payload.args_delta === undefined || typeof payload.args_delta === "string")
      );
    case "visible_text.completed":
    case "message.completed":
    case "reasoning.completed":
      return hasString(payload, "content");
    case "turn.status":
      return hasString(payload, "phase");
    case "turn.interrupt":
      return Object.prototype.hasOwnProperty.call(payload, "interrupt");
    case "turn.completed":
      return isRecord(payload.thread_state);
    case "turn.failed":
      return hasString(payload, "error") && hasString(payload, "message");
    case "turn.closed":
      return hasString(payload, "status");
    case "agent.update":
      return isRecord(payload.data);
    default:
      return true;
  }
}

export function validateFocusAgentEvent(event: unknown): event is FocusAgentEvent {
  if (!isRecord(event) || typeof event.event !== "string") {
    return false;
  }
  if (!isFocusAgentEventName(event.event)) {
    return false;
  }
  return validateFocusAgentEventPayload(event.event, event.data ?? {});
}
