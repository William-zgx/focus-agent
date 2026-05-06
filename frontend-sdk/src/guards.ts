import type {
  FocusAgentEvent,
  FocusAgentToolApprovalDecision,
  FocusAgentToolApprovalInterrupt,
} from "./types.js";

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
    typeof payload.interrupt_id === "string" &&
    typeof payload.tool_name === "string" &&
    typeof payload.tool_call_id === "string" &&
    !("args" in payload) &&
    !!payload.redacted_args &&
    typeof payload.redacted_args === "object" &&
    !Array.isArray(payload.redacted_args) &&
    typeof payload.risk_level === "string" &&
    typeof payload.policy_version === "string" &&
    typeof payload.created_at === "string"
  );
}

export function createToolApprovalDecision(
  interrupt: FocusAgentToolApprovalInterrupt,
  approved: boolean,
  reason?: string | null,
): FocusAgentToolApprovalDecision {
  return {
    kind: "tool_approval",
    interrupt_id: interrupt.interrupt_id,
    tool_call_id: interrupt.tool_call_id,
    approved,
    reason: reason ?? null,
  };
}

export function isTerminalEvent(event: FocusAgentEvent): boolean {
  return event.event === "turn.completed" || event.event === "turn.failed" || event.event === "turn.closed";
}
