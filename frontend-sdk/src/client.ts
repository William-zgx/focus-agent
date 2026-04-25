import { iterSSEEvents } from "./parser";
import { reduceStreamEvent, createInitialStreamState } from "./reducers";
import type {
  FocusAgentApplyMergeDecisionRequest,
  FocusAgentAgentTeamCreateSessionRequest,
  FocusAgentAgentTeamCreateTaskRequest,
  FocusAgentAgentTeamDispatchRequest,
  FocusAgentAgentTeamDispatchResponse,
  FocusAgentAgentTeamListSessionsRequest,
  FocusAgentAgentTeamListTasksRequest,
  FocusAgentAgentTeamMergeBundle,
  FocusAgentAgentTeamMergeDecisionRequest,
  FocusAgentAgentTeamMergeDecisionResponse,
  FocusAgentAgentTeamPrepareMergeBundleRequest,
  FocusAgentAgentTeamRecordTaskOutputRequest,
  FocusAgentAgentTeamRecordTaskOutputResponse,
  FocusAgentAgentTeamSession,
  FocusAgentAgentTeamSessionListResponse,
  FocusAgentAgentTeamTask,
  FocusAgentAgentTeamTaskListResponse,
  FocusAgentAgentTeamUpdateTaskRequest,
  FocusAgentApplyMergeDecisionResponse,
  FocusAgentBranchRecord,
  FocusAgentConversationListResponse,
  FocusAgentConversationSummary,
  FocusAgentCreateConversationRequest,
  FocusAgentCapabilityListResponse,
  FocusAgentArtifactListResponse,
  FocusAgentArtifactSynthesisRequest,
  FocusAgentArtifactSynthesisResponse,
  FocusAgentContextArtifactListResponse,
  FocusAgentContextDecisionListResponse,
  FocusAgentContextPolicyResponse,
  FocusAgentContextPreviewRequest,
  FocusAgentContextPreviewResponse,
  FocusAgentCriticEvaluateRequest,
  FocusAgentCriticEvaluateResponse,
  FocusAgentCriticVerdictListResponse,
  FocusAgentDemoTokenRequest,
  FocusAgentDelegationPlanRequest,
  FocusAgentDelegationPlanResponse,
  FocusAgentDelegationPolicyResponse,
  FocusAgentDelegationRunListResponse,
  FocusAgentEvent,
  FocusAgentForkBranchRequest,
  FocusAgentMemoryCuratorDecisionListResponse,
  FocusAgentMemoryCuratorEvaluateRequest,
  FocusAgentMemoryCuratorEvaluateResponse,
  FocusAgentMemoryCuratorPolicyResponse,
  FocusAgentModelRouteRequest,
  FocusAgentModelRouteResponse,
  FocusAgentModelRouterDecisionListResponse,
  FocusAgentModelRouterPolicyResponse,
  FocusAgentModelsResponse,
  FocusAgentObservabilityOverviewRequest,
  FocusAgentObservabilityOverviewResponse,
  FocusAgentPrincipalResponse,
  FocusAgentRenameBranchRequest,
  FocusAgentRoleDecisionListResponse,
  FocusAgentRoleDryRunRequest,
  FocusAgentRoleDryRunResponse,
  FocusAgentRolePolicyResponse,
  FocusAgentReviewQueueDecisionResponse,
  FocusAgentReviewQueueListResponse,
  FocusAgentSelfRepairFailureListResponse,
  FocusAgentSelfRepairPromotePreviewRequest,
  FocusAgentSelfRepairPromotePreviewResponse,
  FocusAgentToolRouteDecisionListResponse,
  FocusAgentToolRouteRequest,
  FocusAgentToolRouteResponse,
  FocusAgentTaskLedgerPlanRequest,
  FocusAgentTaskLedgerPlanResponse,
  FocusAgentTaskLedgerPolicyResponse,
  FocusAgentTaskLedgerRunListResponse,
  FocusAgentUpdateConversationRequest,
  FocusAgentStreamHandlers,
  FocusAgentStreamState,
  FocusAgentTokenResponse,
  FocusAgentTurnRequest,
  FocusAgentResumeRequest,
  FocusAgentTrajectoryBatchPromotionPreviewRequest,
  FocusAgentTrajectoryBatchPromotionPreviewResponse,
  FocusAgentTrajectoryBatchReplayCompareRequest,
  FocusAgentTrajectoryBatchReplayCompareResponse,
  FocusAgentTrajectoryDetailResponse,
  FocusAgentTrajectoryListRequest,
  FocusAgentTrajectoryListResponse,
  FocusAgentTrajectoryPromotionRequest,
  FocusAgentTrajectoryPromotionResponse,
  FocusAgentTrajectoryReplayRequest,
  FocusAgentTrajectoryReplayResponse,
  FocusAgentTrajectoryStatsRequest,
  FocusAgentTrajectoryStatsResponse,
  BranchTreeResponse,
  ThreadStateResponse,
  ThreadContextCompactRequest,
  ThreadContextCompactResponse,
  ThreadContextPreviewRequest,
  ThreadContextPreviewResponse,
  FocusAgentToolEvent,
} from "./types";

export interface FocusAgentClientOptions {
  baseUrl: string;
  token?: string;
  getToken?: () => string | null | Promise<string | null>;
  fetchImpl?: typeof fetch;
}

export class FocusAgentRequestError extends Error {
  readonly status: number;
  readonly statusText: string;

  constructor(status: number, statusText: string) {
    super(`FocusAgent request failed: ${status} ${statusText}`);
    this.name = "FocusAgentRequestError";
    this.status = status;
    this.statusText = statusText;
  }
}

function appendQueryValue(params: URLSearchParams, key: string, value: unknown): void {
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

function buildTrajectoryQueryString(
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

function buildAgentTeamQueryString(
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

function canonicalizeAliasEvent(event: FocusAgentEvent): FocusAgentEvent {
  switch (event.event) {
    case "message.delta":
      return { ...event, event: "visible_text.delta" } as FocusAgentEvent<"visible_text.delta">;
    case "message.completed":
      return { ...event, event: "visible_text.completed" } as FocusAgentEvent<"visible_text.completed">;
    case "tool.call.delta":
      return { ...event, event: "tool_call.delta" } as FocusAgentEvent<"tool_call.delta">;
    default:
      return event;
  }
}

function aliasDeduplicationKey(event: FocusAgentEvent): string | null {
  switch (event.event) {
    case "visible_text.delta":
    case "visible_text.completed":
    case "tool_call.delta":
      return `${event.event}:${JSON.stringify(event.data)}`;
    default:
      return null;
  }
}

async function* dedupeAndCanonicalizeAliasEvents(
  stream: AsyncIterable<FocusAgentEvent>,
): AsyncGenerator<FocusAgentEvent, void, unknown> {
  let buffered: FocusAgentEvent | null = null;

  for await (const rawEvent of stream) {
    const event = canonicalizeAliasEvent(rawEvent);
    if (!buffered) {
      buffered = event;
      continue;
    }

    const bufferedKey = aliasDeduplicationKey(buffered);
    const eventKey = aliasDeduplicationKey(event);
    if (bufferedKey && bufferedKey === eventKey) {
      continue;
    }

    yield buffered;
    buffered = event;
  }

  if (buffered) {
    yield buffered;
  }
}

export class FocusAgentClient {
  readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;
  private token?: string;
  private readonly getTokenFn?: () => string | null | Promise<string | null>;

  constructor(options: FocusAgentClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/$/, "");
    this.token = options.token;
    this.getTokenFn = options.getToken;
    this.fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
  }

  setToken(token: string | undefined): void {
    this.token = token;
  }

  async createDemoToken(request: FocusAgentDemoTokenRequest = {}): Promise<FocusAgentTokenResponse> {
    return this.requestJson<FocusAgentTokenResponse>("/v1/auth/demo-token", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    }, false);
  }

  async getPrincipal(): Promise<FocusAgentPrincipalResponse> {
    return this.requestJson<FocusAgentPrincipalResponse>("/v1/auth/me", {
      method: "GET",
      headers: {},
    }, true);
  }

  async listModels(): Promise<FocusAgentModelsResponse> {
    return this.requestJson<FocusAgentModelsResponse>("/v1/models", {
      method: "GET",
      headers: {},
    }, true);
  }

  async getAgentRolePolicy(): Promise<FocusAgentRolePolicyResponse> {
    return this.requestJson<FocusAgentRolePolicyResponse>("/v1/agent/roles/policy", {
      method: "GET",
      headers: {},
    }, true);
  }

  async dryRunAgentRoleRoute(
    request: FocusAgentRoleDryRunRequest,
  ): Promise<FocusAgentRoleDryRunResponse> {
    return this.requestJson<FocusAgentRoleDryRunResponse>("/v1/agent/roles/dry-run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    }, true);
  }

  async listAgentRoleDecisions(limit = 50): Promise<FocusAgentRoleDecisionListResponse> {
    const params = new URLSearchParams();
    appendQueryValue(params, "limit", limit);
    const query = params.toString();
    return this.requestJson<FocusAgentRoleDecisionListResponse>(
      `/v1/agent/roles/decisions${query ? `?${query}` : ""}`,
      {
        method: "GET",
        headers: {},
      },
      true,
    );
  }

  async listAgentCapabilities(): Promise<FocusAgentCapabilityListResponse> {
    return this.requestJson<FocusAgentCapabilityListResponse>("/v1/agent/capabilities", {
      method: "GET",
      headers: {},
    }, true);
  }

  async routeAgentTools(request: FocusAgentToolRouteRequest): Promise<FocusAgentToolRouteResponse> {
    return this.requestJson<FocusAgentToolRouteResponse>("/v1/agent/tool-router/route", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    }, true);
  }

  async listAgentToolRouteDecisions(limit = 50): Promise<FocusAgentToolRouteDecisionListResponse> {
    const params = new URLSearchParams();
    appendQueryValue(params, "limit", limit);
    const query = params.toString();
    return this.requestJson<FocusAgentToolRouteDecisionListResponse>(
      `/v1/agent/tool-router/decisions${query ? `?${query}` : ""}`,
      {
        method: "GET",
        headers: {},
      },
      true,
    );
  }

  async getAgentMemoryCuratorPolicy(): Promise<FocusAgentMemoryCuratorPolicyResponse> {
    return this.requestJson<FocusAgentMemoryCuratorPolicyResponse>("/v1/agent/memory/curator/policy", {
      method: "GET",
      headers: {},
    }, true);
  }

  async evaluateAgentMemoryCurator(
    request: FocusAgentMemoryCuratorEvaluateRequest,
  ): Promise<FocusAgentMemoryCuratorEvaluateResponse> {
    return this.requestJson<FocusAgentMemoryCuratorEvaluateResponse>("/v1/agent/memory/curator/evaluate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    }, true);
  }

  async listAgentMemoryCuratorDecisions(limit = 50): Promise<FocusAgentMemoryCuratorDecisionListResponse> {
    const params = new URLSearchParams();
    appendQueryValue(params, "limit", limit);
    const query = params.toString();
    return this.requestJson<FocusAgentMemoryCuratorDecisionListResponse>(
      `/v1/agent/memory/curator/decisions${query ? `?${query}` : ""}`,
      {
        method: "GET",
        headers: {},
      },
      true,
    );
  }

  async getAgentDelegationPolicy(): Promise<FocusAgentDelegationPolicyResponse> {
    return this.requestJson<FocusAgentDelegationPolicyResponse>("/v1/agent/delegation/policy", {
      method: "GET",
      headers: {},
    }, true);
  }

  async planAgentDelegation(
    request: FocusAgentDelegationPlanRequest,
  ): Promise<FocusAgentDelegationPlanResponse> {
    return this.requestJson<FocusAgentDelegationPlanResponse>("/v1/agent/delegation/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    }, true);
  }

  async listAgentDelegationRuns(limit = 50): Promise<FocusAgentDelegationRunListResponse> {
    const params = new URLSearchParams();
    appendQueryValue(params, "limit", limit);
    const query = params.toString();
    return this.requestJson<FocusAgentDelegationRunListResponse>(
      `/v1/agent/delegation/runs${query ? `?${query}` : ""}`,
      {
        method: "GET",
        headers: {},
      },
      true,
    );
  }

  async getAgentModelRouterPolicy(): Promise<FocusAgentModelRouterPolicyResponse> {
    return this.requestJson<FocusAgentModelRouterPolicyResponse>("/v1/agent/model-router/policy", {
      method: "GET",
      headers: {},
    }, true);
  }

  async routeAgentModel(request: FocusAgentModelRouteRequest): Promise<FocusAgentModelRouteResponse> {
    return this.requestJson<FocusAgentModelRouteResponse>("/v1/agent/model-router/route", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    }, true);
  }

  async listAgentModelRouterDecisions(limit = 50): Promise<FocusAgentModelRouterDecisionListResponse> {
    const params = new URLSearchParams();
    appendQueryValue(params, "limit", limit);
    const query = params.toString();
    return this.requestJson<FocusAgentModelRouterDecisionListResponse>(
      `/v1/agent/model-router/decisions${query ? `?${query}` : ""}`,
      {
        method: "GET",
        headers: {},
      },
      true,
    );
  }

  async listAgentSelfRepairFailures(limit = 50): Promise<FocusAgentSelfRepairFailureListResponse> {
    const params = new URLSearchParams();
    appendQueryValue(params, "limit", limit);
    const query = params.toString();
    return this.requestJson<FocusAgentSelfRepairFailureListResponse>(
      `/v1/agent/self-repair/failures${query ? `?${query}` : ""}`,
      {
        method: "GET",
        headers: {},
      },
      true,
    );
  }

  async previewAgentSelfRepairPromotion(
    request: FocusAgentSelfRepairPromotePreviewRequest,
  ): Promise<FocusAgentSelfRepairPromotePreviewResponse> {
    return this.requestJson<FocusAgentSelfRepairPromotePreviewResponse>("/v1/agent/self-repair/promote-preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    }, true);
  }

  async listAgentReviewQueue(limit = 50): Promise<FocusAgentReviewQueueListResponse> {
    const params = new URLSearchParams();
    appendQueryValue(params, "limit", limit);
    const query = params.toString();
    return this.requestJson<FocusAgentReviewQueueListResponse>(
      `/v1/agent/review-queue${query ? `?${query}` : ""}`,
      {
        method: "GET",
        headers: {},
      },
      true,
    );
  }

  async approveAgentReviewQueueItem(itemId: string): Promise<FocusAgentReviewQueueDecisionResponse> {
    return this.requestJson<FocusAgentReviewQueueDecisionResponse>(
      `/v1/agent/review-queue/${encodeURIComponent(itemId)}/approve`,
      {
        method: "POST",
        headers: {},
      },
      true,
    );
  }

  async rejectAgentReviewQueueItem(itemId: string): Promise<FocusAgentReviewQueueDecisionResponse> {
    return this.requestJson<FocusAgentReviewQueueDecisionResponse>(
      `/v1/agent/review-queue/${encodeURIComponent(itemId)}/reject`,
      {
        method: "POST",
        headers: {},
      },
      true,
    );
  }

  async getAgentContextPolicy(): Promise<FocusAgentContextPolicyResponse> {
    return this.requestJson<FocusAgentContextPolicyResponse>("/v1/agent/context/policy", {
      method: "GET",
      headers: {},
    }, true);
  }

  async previewAgentContext(
    request: FocusAgentContextPreviewRequest,
  ): Promise<FocusAgentContextPreviewResponse> {
    return this.requestJson<FocusAgentContextPreviewResponse>("/v1/agent/context/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    }, true);
  }

  async listAgentContextDecisions(limit = 50): Promise<FocusAgentContextDecisionListResponse> {
    const params = new URLSearchParams();
    appendQueryValue(params, "limit", limit);
    const query = params.toString();
    return this.requestJson<FocusAgentContextDecisionListResponse>(
      `/v1/agent/context/decisions${query ? `?${query}` : ""}`,
      {
        method: "GET",
        headers: {},
      },
      true,
    );
  }

  async listAgentContextArtifacts(limit = 50): Promise<FocusAgentContextArtifactListResponse> {
    const params = new URLSearchParams();
    appendQueryValue(params, "limit", limit);
    const query = params.toString();
    return this.requestJson<FocusAgentContextArtifactListResponse>(
      `/v1/agent/context/artifacts${query ? `?${query}` : ""}`,
      {
        method: "GET",
        headers: {},
      },
      true,
    );
  }

  async getAgentTaskLedgerPolicy(): Promise<FocusAgentTaskLedgerPolicyResponse> {
    return this.requestJson<FocusAgentTaskLedgerPolicyResponse>("/v1/agent/task-ledger/policy", {
      method: "GET",
      headers: {},
    }, true);
  }

  async planAgentTaskLedger(
    request: FocusAgentTaskLedgerPlanRequest,
  ): Promise<FocusAgentTaskLedgerPlanResponse> {
    return this.requestJson<FocusAgentTaskLedgerPlanResponse>("/v1/agent/task-ledger/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    }, true);
  }

  async listAgentTaskLedgerRuns(limit = 50): Promise<FocusAgentTaskLedgerRunListResponse> {
    const params = new URLSearchParams();
    appendQueryValue(params, "limit", limit);
    const query = params.toString();
    return this.requestJson<FocusAgentTaskLedgerRunListResponse>(
      `/v1/agent/task-ledger/runs${query ? `?${query}` : ""}`,
      {
        method: "GET",
        headers: {},
      },
      true,
    );
  }

  async listAgentArtifacts(limit = 50): Promise<FocusAgentArtifactListResponse> {
    const params = new URLSearchParams();
    appendQueryValue(params, "limit", limit);
    const query = params.toString();
    return this.requestJson<FocusAgentArtifactListResponse>(
      `/v1/agent/artifacts${query ? `?${query}` : ""}`,
      {
        method: "GET",
        headers: {},
      },
      true,
    );
  }

  async synthesizeAgentArtifacts(
    request: FocusAgentArtifactSynthesisRequest,
  ): Promise<FocusAgentArtifactSynthesisResponse> {
    return this.requestJson<FocusAgentArtifactSynthesisResponse>("/v1/agent/artifacts/synthesize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    }, true);
  }

  async listAgentCriticVerdicts(limit = 50): Promise<FocusAgentCriticVerdictListResponse> {
    const params = new URLSearchParams();
    appendQueryValue(params, "limit", limit);
    const query = params.toString();
    return this.requestJson<FocusAgentCriticVerdictListResponse>(
      `/v1/agent/critic/verdicts${query ? `?${query}` : ""}`,
      {
        method: "GET",
        headers: {},
      },
      true,
    );
  }

  async evaluateAgentCriticGate(
    request: FocusAgentCriticEvaluateRequest,
  ): Promise<FocusAgentCriticEvaluateResponse> {
    return this.requestJson<FocusAgentCriticEvaluateResponse>("/v1/agent/critic/evaluate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    }, true);
  }

  async createAgentTeamSession(
    request: FocusAgentAgentTeamCreateSessionRequest,
  ): Promise<FocusAgentAgentTeamSession> {
    const response = await this.requestJson<{ session: FocusAgentAgentTeamSession }>("/v1/agent-team/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    }, true);
    return response.session;
  }

  async listAgentTeamSessions(
    request: FocusAgentAgentTeamListSessionsRequest = {},
  ): Promise<FocusAgentAgentTeamSessionListResponse> {
    const response = await this.requestJson<FocusAgentAgentTeamSessionListResponse & { sessions?: FocusAgentAgentTeamSession[] }>(
      `/v1/agent-team/sessions${buildAgentTeamQueryString(request)}`,
      {
        method: "GET",
        headers: {},
      },
      true,
    );
    const items = response.items ?? response.sessions ?? [];
    return { items, count: response.count ?? items.length };
  }

  async getAgentTeamSession(sessionId: string): Promise<FocusAgentAgentTeamSession> {
    const response = await this.requestJson<{ session: FocusAgentAgentTeamSession }>(
      `/v1/agent-team/sessions/${encodeURIComponent(sessionId)}`,
      {
        method: "GET",
        headers: {},
      },
      true,
    );
    return response.session;
  }

  async dispatchAgentTeamSession(
    sessionId: string,
    request: FocusAgentAgentTeamDispatchRequest = {},
  ): Promise<FocusAgentAgentTeamDispatchResponse> {
    const response = await this.requestJson<FocusAgentAgentTeamDispatchResponse>(
      `/v1/agent-team/sessions/${encodeURIComponent(sessionId)}/dispatch`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...request,
          create_branches: request.auto_fork_branch ?? request.create_branches,
        }),
      },
      true,
    );
    const items = response.items ?? response.tasks ?? [];
    return { ...response, tasks: response.tasks ?? items, items, count: response.count ?? items.length };
  }

  async createAgentTeamTask(
    sessionId: string,
    request: FocusAgentAgentTeamCreateTaskRequest,
  ): Promise<FocusAgentAgentTeamTask> {
    const response = await this.requestJson<{ task: FocusAgentAgentTeamTask }>(
      `/v1/agent-team/sessions/${encodeURIComponent(sessionId)}/tasks`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...request,
          create_branch: request.auto_fork_branch ?? request.create_branch,
        }),
      },
      true,
    );
    return response.task;
  }

  async listAgentTeamTasks(
    sessionId: string,
    request: FocusAgentAgentTeamListTasksRequest = {},
  ): Promise<FocusAgentAgentTeamTaskListResponse> {
    const response = await this.requestJson<FocusAgentAgentTeamTaskListResponse & { tasks?: FocusAgentAgentTeamTask[] }>(
      `/v1/agent-team/sessions/${encodeURIComponent(sessionId)}/tasks${buildAgentTeamQueryString(request)}`,
      {
        method: "GET",
        headers: {},
      },
      true,
    );
    const items = response.items ?? response.tasks ?? [];
    return { items, count: response.count ?? items.length };
  }

  async getAgentTeamTaskStatus(taskId: string): Promise<FocusAgentAgentTeamTask> {
    const response = await this.requestJson<{ task: FocusAgentAgentTeamTask }>(
      `/v1/agent-team/tasks/${encodeURIComponent(taskId)}`,
      {
        method: "GET",
        headers: {},
      },
      true,
    );
    return response.task;
  }

  async updateAgentTeamTask(
    taskId: string,
    request: FocusAgentAgentTeamUpdateTaskRequest,
  ): Promise<FocusAgentAgentTeamTask> {
    const response = await this.requestJson<{ task: FocusAgentAgentTeamTask }>(
      `/v1/agent-team/tasks/${encodeURIComponent(taskId)}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      },
      true,
    );
    return response.task;
  }

  async recordAgentTeamTaskOutput(
    taskId: string,
    request: FocusAgentAgentTeamRecordTaskOutputRequest,
  ): Promise<FocusAgentAgentTeamRecordTaskOutputResponse> {
    return this.requestJson<FocusAgentAgentTeamRecordTaskOutputResponse>(
      `/v1/agent-team/tasks/${encodeURIComponent(taskId)}/outputs`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...request,
          kind: request.artifact_kind,
          summary: request.summary ?? request.content ?? "",
          test_evidence: request.verification_summary ? [request.verification_summary] : undefined,
        }),
      },
      true,
    );
  }

  async prepareAgentTeamMergeBundle(
    sessionId: string,
    request: FocusAgentAgentTeamPrepareMergeBundleRequest = {},
  ): Promise<FocusAgentAgentTeamMergeBundle> {
    const response = await this.requestJson<{ bundle: FocusAgentAgentTeamMergeBundle }>(
      `/v1/agent-team/sessions/${encodeURIComponent(sessionId)}/merge-bundle`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      },
      true,
    );
    return response.bundle;
  }

  async recordAgentTeamMergeDecision(
    sessionId: string,
    request: FocusAgentAgentTeamMergeDecisionRequest,
  ): Promise<FocusAgentAgentTeamMergeDecisionResponse> {
    return this.requestJson<FocusAgentAgentTeamMergeDecisionResponse>(
      `/v1/agent-team/sessions/${encodeURIComponent(sessionId)}/merge-decision`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          approved: request.apply ?? true,
          action: request.next_action,
          rationale: request.rationale,
          accepted_tasks: request.accepted_tasks,
          rejected_tasks: request.rejected_tasks,
        }),
      },
      true,
    );
  }

  async listConversations(): Promise<FocusAgentConversationListResponse> {
    return this.requestJson<FocusAgentConversationListResponse>("/v1/conversations", {
      method: "GET",
      headers: {},
    }, true);
  }

  async createConversation(
    request: FocusAgentCreateConversationRequest = {},
  ): Promise<FocusAgentConversationSummary> {
    return this.requestJson<FocusAgentConversationSummary>("/v1/conversations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    }, true);
  }

  async renameConversation(
    rootThreadId: string,
    request: FocusAgentUpdateConversationRequest,
  ): Promise<FocusAgentConversationSummary> {
    return this.requestJson<FocusAgentConversationSummary>(
      `/v1/conversations/${encodeURIComponent(rootThreadId)}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      },
      true,
    );
  }

  async archiveConversation(rootThreadId: string): Promise<FocusAgentConversationSummary> {
    return this.requestJson<FocusAgentConversationSummary>(
      `/v1/conversations/${encodeURIComponent(rootThreadId)}/archive`,
      {
        method: "POST",
        headers: {},
      },
      true,
    );
  }

  async activateConversation(rootThreadId: string): Promise<FocusAgentConversationSummary> {
    return this.requestJson<FocusAgentConversationSummary>(
      `/v1/conversations/${encodeURIComponent(rootThreadId)}/activate`,
      {
        method: "POST",
        headers: {},
      },
      true,
    );
  }

  async getThreadState(threadId: string): Promise<ThreadStateResponse> {
    return this.requestJson<ThreadStateResponse>(`/v1/threads/${encodeURIComponent(threadId)}`, {
      method: "GET",
      headers: {},
    }, true);
  }

  async previewThreadContext(
    threadId: string,
    request: ThreadContextPreviewRequest = {},
  ): Promise<ThreadContextPreviewResponse> {
    return this.requestJson<ThreadContextPreviewResponse>(
      `/v1/threads/${encodeURIComponent(threadId)}/context/preview`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      },
      true,
    );
  }

  async compactThreadContext(
    threadId: string,
    request: ThreadContextCompactRequest = {},
  ): Promise<ThreadContextCompactResponse> {
    return this.requestJson<ThreadContextCompactResponse>(
      `/v1/threads/${encodeURIComponent(threadId)}/context/compact`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      },
      true,
    );
  }

  async getBranchTree(rootThreadId: string): Promise<BranchTreeResponse> {
    return this.requestJson<BranchTreeResponse>(`/v1/branches/tree/${encodeURIComponent(rootThreadId)}`, {
      method: "GET",
      headers: {},
    }, true);
  }

  async listTrajectoryTurns(
    request: FocusAgentTrajectoryListRequest = {},
  ): Promise<FocusAgentTrajectoryListResponse> {
    return this.requestJson<FocusAgentTrajectoryListResponse>(
      `/v1/observability/trajectory${buildTrajectoryQueryString(request)}`,
      {
        method: "GET",
        headers: {},
      },
      true,
    );
  }

  async getTrajectoryTurn(turnId: string): Promise<FocusAgentTrajectoryDetailResponse> {
    return this.requestJson<FocusAgentTrajectoryDetailResponse>(
      `/v1/observability/trajectory/${encodeURIComponent(turnId)}`,
      {
        method: "GET",
        headers: {},
      },
      true,
    );
  }

  async getTrajectoryStats(
    request: FocusAgentTrajectoryStatsRequest = {},
  ): Promise<FocusAgentTrajectoryStatsResponse> {
    return this.requestJson<FocusAgentTrajectoryStatsResponse>(
      `/v1/observability/trajectory/stats${buildTrajectoryQueryString(request)}`,
      {
        method: "GET",
        headers: {},
      },
      true,
    );
  }

  async getObservabilityOverview(
    request: FocusAgentObservabilityOverviewRequest = {},
  ): Promise<FocusAgentObservabilityOverviewResponse> {
    return this.requestJson<FocusAgentObservabilityOverviewResponse>(
      `/v1/observability/overview${buildTrajectoryQueryString(request)}`,
      {
        method: "GET",
        headers: {},
      },
      true,
    );
  }

  async replayTrajectoryTurn(
    turnId: string,
    request: FocusAgentTrajectoryReplayRequest = {},
  ): Promise<FocusAgentTrajectoryReplayResponse> {
    return this.requestJson<FocusAgentTrajectoryReplayResponse>(
      `/v1/observability/trajectory/${encodeURIComponent(turnId)}/replay`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      },
      true,
    );
  }

  async promoteTrajectoryTurn(
    turnId: string,
    request: FocusAgentTrajectoryPromotionRequest = {},
  ): Promise<FocusAgentTrajectoryPromotionResponse> {
    return this.requestJson<FocusAgentTrajectoryPromotionResponse>(
      `/v1/observability/trajectory/${encodeURIComponent(turnId)}/promote`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      },
      true,
    );
  }

  async batchPromoteTrajectoryTurnsPreview(
    request: FocusAgentTrajectoryBatchPromotionPreviewRequest,
  ): Promise<FocusAgentTrajectoryBatchPromotionPreviewResponse> {
    return this.requestJson<FocusAgentTrajectoryBatchPromotionPreviewResponse>(
      "/v1/observability/trajectory/batch/promote-preview",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      },
      true,
    );
  }

  async batchReplayCompareTrajectoryTurns(
    request: FocusAgentTrajectoryBatchReplayCompareRequest,
  ): Promise<FocusAgentTrajectoryBatchReplayCompareResponse> {
    return this.requestJson<FocusAgentTrajectoryBatchReplayCompareResponse>(
      "/v1/observability/trajectory/batch/replay-compare",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      },
      true,
    );
  }

  async forkBranch(request: FocusAgentForkBranchRequest): Promise<FocusAgentBranchRecord> {
    return this.requestJson<FocusAgentBranchRecord>("/v1/branches/fork", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    }, true);
  }

  async archiveBranch(threadId: string): Promise<FocusAgentBranchRecord> {
    return this.requestJson<FocusAgentBranchRecord>(`/v1/branches/${encodeURIComponent(threadId)}/archive`, {
      method: "POST",
      headers: {},
    }, true);
  }

  async activateBranch(threadId: string): Promise<FocusAgentBranchRecord> {
    return this.requestJson<FocusAgentBranchRecord>(`/v1/branches/${encodeURIComponent(threadId)}/activate`, {
      method: "POST",
      headers: {},
    }, true);
  }

  async renameBranch(threadId: string, request: FocusAgentRenameBranchRequest): Promise<FocusAgentBranchRecord> {
    return this.requestJson<FocusAgentBranchRecord>(`/v1/branches/${encodeURIComponent(threadId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    }, true);
  }

  async prepareMergeProposal(threadId: string): Promise<ThreadStateResponse["merge_proposal"]> {
    return this.requestJson<ThreadStateResponse["merge_proposal"]>(
      `/v1/branches/${encodeURIComponent(threadId)}/proposal`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      },
      true,
    );
  }

  async applyMergeDecision(
    threadId: string,
    request: FocusAgentApplyMergeDecisionRequest,
  ): Promise<FocusAgentApplyMergeDecisionResponse> {
    return this.requestJson<FocusAgentApplyMergeDecisionResponse>(
      `/v1/branches/${encodeURIComponent(threadId)}/merge`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      },
      true,
    );
  }

  async streamTurn(
    request: FocusAgentTurnRequest,
    options: { signal?: AbortSignal } = {},
  ): Promise<AsyncGenerator<FocusAgentEvent, void, unknown>> {
    return this.stream("/v1/chat/turns/stream", request, options);
  }

  async streamResume(
    request: FocusAgentResumeRequest,
    options: { signal?: AbortSignal } = {},
  ): Promise<AsyncGenerator<FocusAgentEvent, void, unknown>> {
    return this.stream("/v1/chat/resume/stream", request, options);
  }

  async collectStream(
    stream: AsyncIterable<FocusAgentEvent>,
    handlers: FocusAgentStreamHandlers = {},
  ): Promise<FocusAgentStreamState> {
    let state = createInitialStreamState();
    for await (const event of stream) {
      state = reduceStreamEvent(state, event);
      handlers.onEvent?.(event);
      switch (event.event) {
        case "visible_text.delta":
        case "message.delta":
          handlers.onVisibleTextDelta?.(event as FocusAgentEvent<"visible_text.delta">);
          break;
        case "reasoning.delta":
          handlers.onReasoningDelta?.(event);
          break;
        case "tool_call.delta":
        case "tool.call.delta":
          handlers.onToolCallDelta?.(event as FocusAgentEvent<"tool_call.delta">);
          break;
        case "tool.requested":
        case "tool.start":
        case "tool.delta":
        case "tool.end":
        case "tool.error":
        case "tool.result":
          handlers.onToolEvent?.(event as FocusAgentToolEvent);
          break;
        case "turn.completed":
          handlers.onCompleted?.(event);
          break;
        case "turn.failed":
          handlers.onFailed?.(event);
          break;
        default:
          break;
      }
    }
    return state;
  }

  private async stream(
    path: string,
    body: unknown,
    options: { signal?: AbortSignal } = {},
  ): Promise<AsyncGenerator<FocusAgentEvent, void, unknown>> {
    const response = await this.fetchImpl(`${this.baseUrl}${path}`, {
      method: "POST",
      headers: await this.buildHeaders({ "Content-Type": "application/json", Accept: "text/event-stream" }, true),
      body: JSON.stringify(body),
      signal: options.signal,
    });
    this.ensureOk(response);
    if (!response.body) {
      throw new Error("FocusAgent stream response did not include a body.");
    }
    return dedupeAndCanonicalizeAliasEvents(iterSSEEvents(response.body));
  }

  private async requestJson<T>(path: string, init: RequestInit, auth: boolean): Promise<T> {
    const response = await this.fetchImpl(`${this.baseUrl}${path}`, {
      ...init,
      headers: await this.buildHeaders(init.headers ?? {}, auth),
    });
    this.ensureOk(response);
    return (await response.json()) as T;
  }

  private async buildHeaders(headers: HeadersInit, auth: boolean): Promise<HeadersInit> {
    const next = new Headers(headers);
    if (auth) {
      const token = await this.resolveToken();
      if (token) next.set("Authorization", `Bearer ${token}`);
    }
    return next;
  }

  private async resolveToken(): Promise<string | null> {
    if (this.token) return this.token;
    if (this.getTokenFn) return (await this.getTokenFn()) ?? null;
    return null;
  }

  private ensureOk(response: Response): void {
    if (response.ok) return;
    throw new FocusAgentRequestError(response.status, response.statusText);
  }
}
