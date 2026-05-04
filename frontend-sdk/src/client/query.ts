import type {
  FocusAgentAgentTeamListSessionsRequest,
  FocusAgentAgentTeamListTasksRequest,
  FocusAgentAuditEventListRequest,
  FocusAgentObservabilityOverviewRequest,
  FocusAgentTrajectoryListRequest,
  FocusAgentTrajectoryStatsRequest,
  FocusAgentUserListRequest,
} from "../types";

export function appendQueryValue(params: URLSearchParams, key: string, value: unknown): void {
  if (value === undefined || value === null) {
    return;
  }
  if (Array.isArray(value)) {
    for (const item of value) {
      appendQueryValue(params, key, item);
    }
    return;
  }
  if (typeof value === "boolean") {
    if (value) {
      params.append(key, "true");
    }
    return;
  }
  params.append(key, String(value));
}

export function buildTrajectoryQueryString(
  request: FocusAgentTrajectoryListRequest | FocusAgentTrajectoryStatsRequest | FocusAgentObservabilityOverviewRequest,
): string {
  const params = new URLSearchParams();
  appendQueryValue(params, "turn_id", request.turn_id);
  appendQueryValue(params, "turn_ids", request.turn_ids);
  appendQueryValue(params, "request_id", request.request_id);
  appendQueryValue(params, "trace_id", request.trace_id);
  appendQueryValue(params, "thread_id", request.thread_id);
  appendQueryValue(params, "root_thread_id", request.root_thread_id);
  appendQueryValue(params, "parent_thread_id", request.parent_thread_id);
  appendQueryValue(params, "branch_id", request.branch_id);
  appendQueryValue(params, "branch_role", request.branch_role);
  appendQueryValue(params, "status", request.status);
  appendQueryValue(params, "scene", request.scene);
  appendQueryValue(params, "kind", request.kind);
  appendQueryValue(params, "tool", request.tool);
  appendQueryValue(params, "model", request.selected_model ?? request.model);
  appendQueryValue(params, "started_after", request.started_after ?? request.since);
  appendQueryValue(params, "started_before", request.started_before ?? request.until);
  appendQueryValue(params, "fallback_used", request.fallback_used);
  appendQueryValue(params, "cache_hit", request.cache_hit);
  appendQueryValue(params, "has_error", request.has_error);
  appendQueryValue(params, "min_latency_ms", request.min_latency_ms);
  appendQueryValue(params, "max_latency_ms", request.max_latency_ms);
  appendQueryValue(params, "min_tool_calls", request.min_tool_calls);
  appendQueryValue(params, "max_tool_calls", request.max_tool_calls);
  appendQueryValue(params, "newest_first", request.newest_first);
  if ("limit" in request) {
    appendQueryValue(params, "limit", request.limit);
  }
  if ("offset" in request) {
    appendQueryValue(params, "offset", request.offset);
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

export function buildAgentTeamQueryString(
  request: FocusAgentAgentTeamListSessionsRequest | FocusAgentAgentTeamListTasksRequest = {},
): string {
  const params = new URLSearchParams();
  if ("root_thread_id" in request) {
    appendQueryValue(params, "root_thread_id", request.root_thread_id);
  }
  appendQueryValue(params, "status", request.status);
  if ("role" in request) {
    appendQueryValue(params, "role", request.role);
  }
  appendQueryValue(params, "limit", request.limit);
  appendQueryValue(params, "offset", request.offset);
  const query = params.toString();
  return query ? `?${query}` : "";
}

export function buildAdminUserQueryString(request: FocusAgentUserListRequest = {}): string {
  const params = new URLSearchParams();
  appendQueryValue(params, "status", request.status);
  appendQueryValue(params, "role", request.role);
  appendQueryValue(params, "tenant_id", request.tenant_id);
  appendQueryValue(params, "query", request.query);
  appendQueryValue(params, "limit", request.limit);
  appendQueryValue(params, "offset", request.offset);
  const query = params.toString();
  return query ? `?${query}` : "";
}

export function buildAuditEventQueryString(request: FocusAgentAuditEventListRequest = {}): string {
  const params = new URLSearchParams();
  appendQueryValue(params, "actor_user_id", request.actor_user_id);
  appendQueryValue(params, "resource_type", request.resource_type);
  appendQueryValue(params, "resource_id", request.resource_id);
  appendQueryValue(params, "decision", request.decision);
  appendQueryValue(params, "limit", request.limit);
  appendQueryValue(params, "offset", request.offset);
  const query = params.toString();
  return query ? `?${query}` : "";
}
