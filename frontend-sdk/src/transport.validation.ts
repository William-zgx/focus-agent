import type { FocusAgentEvent, FocusAgentEventName, FocusAgentEventPayload } from "./types.js";

const KNOWN_EVENT_NAMES = new Set<FocusAgentEventName>([
  "run.metadata",
  "run.status",
  "run.completed",
  "run.failed",
  "run.interrupt",
  "run.rollback.started",
  "run.rollback.succeeded",
  "run.rollback.failed",
  "run.closed",
  "server_shutdown",
  "heartbeat",
  "state.update",
  "message.delta",
  "message.completed",
  "reasoning.delta",
  "tool.call.delta",
  "tool.requested",
  "tool.error",
  "tool.result",
  "task.update",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasString(value: Record<string, unknown>, key: string): boolean {
  return typeof value[key] === "string";
}

function optionalString(value: Record<string, unknown>, key: string): boolean {
  return value[key] === undefined || typeof value[key] === "string";
}

function optionalRecordOrNull(value: Record<string, unknown>, key: string): boolean {
  return value[key] === undefined || value[key] === null || isRecord(value[key]);
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
    case "message.delta":
      return hasString(payload, "delta");
    case "reasoning.delta":
      return hasString(payload, "delta");
    case "tool.call.delta":
      return (
        (payload.id === undefined || typeof payload.id === "string") &&
        (payload.name === undefined || typeof payload.name === "string") &&
        (payload.args_delta === undefined || typeof payload.args_delta === "string")
      );
    case "message.completed":
      return hasString(payload, "content") && optionalRecordOrNull(payload, "task_outcome");
    case "run.status":
      return hasString(payload, "phase");
    case "run.failed":
      return (
        hasString(payload, "error") &&
        hasString(payload, "message") &&
        optionalRecordOrNull(payload, "thread_state") &&
        optionalRecordOrNull(payload, "task_outcome")
      );
    case "run.rollback.failed":
      return (
        (payload.error === undefined || typeof payload.error === "string") &&
        (payload.message === undefined || typeof payload.message === "string") &&
        optionalRecordOrNull(payload, "rollback_result")
      );
    case "run.interrupt":
      return hasString(payload, "action");
    case "server_shutdown":
      return optionalString(payload, "message");
    case "run.rollback.started":
    case "run.rollback.succeeded":
      return true;
    case "run.closed":
    case "run.completed":
      return (
        hasString(payload, "status") &&
        optionalRecordOrNull(payload, "thread_state") &&
        optionalRecordOrNull(payload, "task_outcome")
      );
    case "tool.requested":
      return optionalString(payload, "tool_name") && optionalString(payload, "tool_call_id");
    case "tool.error":
    case "tool.result":
      return (
        optionalString(payload, "tool_name") &&
        optionalString(payload, "tool_call_id") &&
        optionalRecordOrNull(payload, "runtime") &&
        optionalRecordOrNull(payload, "tool_outcome")
      );
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
