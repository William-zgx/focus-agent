import type { FocusAgentEvent, FocusAgentToolApprovalInterrupt } from "./types.js";

export function isVisibleTextDeltaEvent(
  event: FocusAgentEvent,
): event is FocusAgentEvent<"visible_text.delta"> {
  return event.event === "visible_text.delta" || event.event === "message.delta";
}

export function isReasoningDeltaEvent(
  event: FocusAgentEvent,
): event is FocusAgentEvent<"reasoning.delta"> {
  return event.event === "reasoning.delta";
}

export function isToolCallDeltaEvent(
  event: FocusAgentEvent,
): event is FocusAgentEvent<"tool_call.delta"> {
  return event.event === "tool_call.delta" || event.event === "tool.call.delta";
}

export function isToolLifecycleEvent(event: FocusAgentEvent): boolean {
  return [
    "tool.requested",
    "tool.start",
    "tool.delta",
    "tool.end",
    "tool.error",
    "tool.result",
  ].includes(event.event);
}

export function isToolApprovalInterrupt(
  interrupt: unknown,
): interrupt is FocusAgentToolApprovalInterrupt {
  if (!interrupt || typeof interrupt !== "object") {
    return false;
  }
  const payload = interrupt as Record<string, unknown>;
  return (
    payload.kind === "tool_approval" &&
    typeof payload.tool_name === "string" &&
    typeof payload.tool_call_id === "string" &&
    !!payload.args &&
    typeof payload.args === "object" &&
    !Array.isArray(payload.args) &&
    typeof payload.risk_level === "string"
  );
}

export function isTerminalEvent(event: FocusAgentEvent): boolean {
  return event.event === "turn.completed" || event.event === "turn.failed" || event.event === "turn.closed";
}
