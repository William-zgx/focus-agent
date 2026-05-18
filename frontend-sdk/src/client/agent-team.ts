import { buildAgentTeamQueryString } from "./query.js";
import { applyEndpointMethods } from "./endpoint.js";
import type { EndpointClientConstructor, FocusAgentEndpointContext, FocusAgentEndpointMethodMap } from "./endpoint.js";
import type {
  FocusAgentAgentTeamCreateSessionRequest,
  FocusAgentAgentTeamCreateTaskRequest,
  FocusAgentAgentTeamDispatchRequest,
  FocusAgentAgentTeamDispatchResponse,
  FocusAgentAgentTeamPlanSessionRequest,
  FocusAgentAgentTeamPlanSessionResponse,
  FocusAgentAgentTeamListSessionsRequest,
  FocusAgentAgentTeamListTasksRequest,
  FocusAgentAgentTeamRunSessionRequest,
  FocusAgentAgentTeamRunSessionResponse,
  FocusAgentAgentTeamRunTaskResponse,
  FocusAgentAgentTeamTaskRunRequest,
  FocusAgentAgentTeamRunMetadata,
  FocusAgentAgentTeamMergeBundle,
  FocusAgentAgentTeamCreateMergeReviewRequest,
  FocusAgentAgentTeamMergeReviewApplyRequest,
  FocusAgentAgentTeamMergeReviewListResponse,
  FocusAgentAgentTeamMergeReviewPreviewRequest,
  FocusAgentAgentTeamMergeReviewPreviewResponse,
  FocusAgentAgentTeamMergeReviewRejectRequest,
  FocusAgentAgentTeamMergeReviewResponse,
  FocusAgentAgentTeamUpdateMergeReviewRequest,
  FocusAgentAgentTeamMergeDecisionRequest,
  FocusAgentAgentTeamMergeDecisionResponse,
  FocusAgentAgentTeamToolApprovalDecisionRequest,
  FocusAgentAgentTeamToolApprovalDecisionResponse,
  FocusAgentAgentTeamToolApprovalListResponse,
  FocusAgentAgentTeamPrepareMergeBundleRequest,
  FocusAgentAgentTeamRecordTaskOutputRequest,
  FocusAgentAgentTeamRecordTaskOutputResponse,
  FocusAgentAgentTeamSession,
  FocusAgentAgentTeamSessionView,
  FocusAgentAgentTeamPlanningMetadata,
  FocusAgentAgentTeamSessionListResponse,
  FocusAgentAgentTeamTask,
  FocusAgentAgentTeamTaskOutput,
  FocusAgentAgentTeamToolApproval,
  FocusAgentAgentTeamArtifact,
  FocusAgentAgentTeamTaskListResponse,
  FocusAgentAgentTeamUpdateTaskRequest,
} from "../types.js";

type AgentTeamSessionActionResponse = {
  session: FocusAgentAgentTeamSession;
  tasks?: FocusAgentAgentTeamTask[];
  items?: FocusAgentAgentTeamTask[];
  outputs?: FocusAgentAgentTeamTaskOutput[];
  artifacts?: FocusAgentAgentTeamArtifact[];
  merge_bundle?: FocusAgentAgentTeamMergeBundle | null;
  planning?: FocusAgentAgentTeamPlanningMetadata | null;
  run?: FocusAgentAgentTeamRunMetadata | null;
  pending_tool_approvals?: FocusAgentAgentTeamToolApproval[];
  count?: number;
};

type AgentTeamTaskActionResponse = Omit<AgentTeamSessionActionResponse, "session"> & {
  session?: FocusAgentAgentTeamSession | null;
  task?: FocusAgentAgentTeamTask | null;
};

function normalizeAgentTeamSessionActionResponse<T extends AgentTeamSessionActionResponse>(
  response: T,
): T & FocusAgentAgentTeamRunSessionResponse {
  const items = response.items ?? response.tasks ?? [];
  return {
    ...response,
    tasks: response.tasks ?? items,
    items,
    outputs: response.outputs ?? [],
    artifacts: response.artifacts ?? [],
    planning: response.planning ?? response.session.planning ?? null,
    run: response.run ?? null,
    pending_tool_approvals: response.pending_tool_approvals ?? [],
    count: response.count ?? items.length,
  };
}

function normalizeAgentTeamTaskActionResponse(response: AgentTeamTaskActionResponse): FocusAgentAgentTeamRunTaskResponse {
  const items = response.items ?? response.tasks ?? (response.task ? [response.task] : []);
  return {
    ...response,
    tasks: response.tasks ?? items,
    items,
    outputs: response.outputs ?? [],
    artifacts: response.artifacts ?? [],
    planning: response.planning ?? response.session?.planning ?? null,
    run: response.run ?? null,
    pending_tool_approvals: response.pending_tool_approvals ?? [],
    count: response.count ?? items.length,
  };
}

async function createAgentTeamSession(
  this: FocusAgentEndpointContext,
  request: FocusAgentAgentTeamCreateSessionRequest,
): Promise<FocusAgentAgentTeamSession> {
  const response = await this.requestJson<{ session: FocusAgentAgentTeamSession }>("/v1/agent-team/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  }, true);
  return response.session;
}

async function listAgentTeamSessions(
  this: FocusAgentEndpointContext,
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

async function getAgentTeamSession(this: FocusAgentEndpointContext, sessionId: string): Promise<FocusAgentAgentTeamSession> {
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

async function getAgentTeamSessionView(
  this: FocusAgentEndpointContext,
  sessionId: string,
): Promise<FocusAgentAgentTeamSessionView> {
  const response = await this.requestJson<FocusAgentAgentTeamSessionView>(
    `/v1/agent-team/sessions/${encodeURIComponent(sessionId)}/view`,
    {
      method: "GET",
      headers: {},
    },
    true,
  );
  return {
    ...response,
    tasks: response.tasks ?? [],
    artifacts: response.artifacts ?? [],
    outputs: response.outputs ?? [],
    merge_bundle: response.merge_bundle ?? response.session.latest_merge_bundle ?? null,
    planning: response.planning ?? response.session.planning ?? { task_count: response.tasks?.length ?? 0 },
    run: response.run ?? null,
    pending_tool_approvals: response.pending_tool_approvals ?? [],
  };
}

async function planAgentTeamSession(
  this: FocusAgentEndpointContext,
  sessionId: string,
  request: FocusAgentAgentTeamPlanSessionRequest = {},
): Promise<FocusAgentAgentTeamPlanSessionResponse> {
  const response = await this.requestJson<AgentTeamSessionActionResponse>(
    `/v1/agent-team/sessions/${encodeURIComponent(sessionId)}/plan`,
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
  return normalizeAgentTeamSessionActionResponse(response);
}

async function runAgentTeamSession(
  this: FocusAgentEndpointContext,
  sessionId: string,
  request: FocusAgentAgentTeamRunSessionRequest = {},
): Promise<FocusAgentAgentTeamRunSessionResponse> {
  const response = await this.requestJson<AgentTeamSessionActionResponse>(
    `/v1/agent-team/sessions/${encodeURIComponent(sessionId)}/run`,
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
  return normalizeAgentTeamSessionActionResponse(response);
}

async function dispatchAgentTeamSession(
  this: FocusAgentEndpointContext,
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

async function createAgentTeamTask(
  this: FocusAgentEndpointContext,
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

async function listAgentTeamTasks(
  this: FocusAgentEndpointContext,
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

async function getAgentTeamTaskStatus(this: FocusAgentEndpointContext, taskId: string): Promise<FocusAgentAgentTeamTask> {
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

async function updateAgentTeamTask(
  this: FocusAgentEndpointContext,
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

async function runAgentTeamTask(
  this: FocusAgentEndpointContext,
  taskId: string,
  request: FocusAgentAgentTeamTaskRunRequest = {},
): Promise<FocusAgentAgentTeamRunTaskResponse> {
  const response = await this.requestJson<AgentTeamTaskActionResponse>(
    `/v1/agent-team/tasks/${encodeURIComponent(taskId)}/run`,
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
  return normalizeAgentTeamTaskActionResponse(response);
}

async function retryAgentTeamTask(
  this: FocusAgentEndpointContext,
  taskId: string,
): Promise<FocusAgentAgentTeamRunTaskResponse> {
  const response = await this.requestJson<AgentTeamTaskActionResponse>(
    `/v1/agent-team/tasks/${encodeURIComponent(taskId)}/retry`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    },
    true,
  );
  return normalizeAgentTeamTaskActionResponse(response);
}

async function cancelAgentTeamTask(
  this: FocusAgentEndpointContext,
  taskId: string,
): Promise<FocusAgentAgentTeamRunTaskResponse> {
  const response = await this.requestJson<AgentTeamTaskActionResponse>(
    `/v1/agent-team/tasks/${encodeURIComponent(taskId)}/cancel`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    },
    true,
  );
  return normalizeAgentTeamTaskActionResponse(response);
}

async function cancelAgentTeamSession(
  this: FocusAgentEndpointContext,
  sessionId: string,
): Promise<FocusAgentAgentTeamSessionView> {
  const response = await this.requestJson<FocusAgentAgentTeamSessionView>(
    `/v1/agent-team/sessions/${encodeURIComponent(sessionId)}/cancel`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    },
    true,
  );
  return {
    ...response,
    tasks: response.tasks ?? [],
    artifacts: response.artifacts ?? [],
    outputs: response.outputs ?? [],
    merge_bundle: response.merge_bundle ?? response.session.latest_merge_bundle ?? null,
    planning: response.planning ?? response.session.planning ?? { task_count: response.tasks?.length ?? 0 },
    run: response.run ?? null,
    pending_tool_approvals: response.pending_tool_approvals ?? [],
  };
}

async function listAgentTeamToolApprovals(
  this: FocusAgentEndpointContext,
  sessionId: string,
): Promise<FocusAgentAgentTeamToolApprovalListResponse> {
  const response = await this.requestJson<FocusAgentAgentTeamToolApprovalListResponse>(
    `/v1/agent-team/sessions/${encodeURIComponent(sessionId)}/tool-approvals`,
    {
      method: "GET",
      headers: {},
    },
    true,
  );
  const items = response.items ?? response.approvals ?? [];
  return { approvals: response.approvals ?? items, items, count: response.count ?? items.length };
}

async function decideAgentTeamToolApproval(
  this: FocusAgentEndpointContext,
  sessionId: string,
  requestId: string,
  request: FocusAgentAgentTeamToolApprovalDecisionRequest,
): Promise<FocusAgentAgentTeamToolApprovalDecisionResponse> {
  return this.requestJson<FocusAgentAgentTeamToolApprovalDecisionResponse>(
    `/v1/agent-team/sessions/${encodeURIComponent(sessionId)}/tool-approvals/${encodeURIComponent(requestId)}/decision`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
    true,
  );
}

async function approveAgentTeamToolApproval(
  this: FocusAgentEndpointContext,
  sessionId: string,
  requestId: string,
  request: Omit<FocusAgentAgentTeamToolApprovalDecisionRequest, "approved"> = {},
): Promise<FocusAgentAgentTeamToolApprovalDecisionResponse> {
  return decideAgentTeamToolApproval.call(this, sessionId, requestId, {
    ...request,
    approved: true,
  });
}

async function rejectAgentTeamToolApproval(
  this: FocusAgentEndpointContext,
  sessionId: string,
  requestId: string,
  request: Omit<FocusAgentAgentTeamToolApprovalDecisionRequest, "approved"> = {},
): Promise<FocusAgentAgentTeamToolApprovalDecisionResponse> {
  return decideAgentTeamToolApproval.call(this, sessionId, requestId, {
    ...request,
    approved: false,
  });
}

async function recordAgentTeamTaskOutput(
  this: FocusAgentEndpointContext,
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

async function prepareAgentTeamMergeBundle(
  this: FocusAgentEndpointContext,
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

async function recordAgentTeamMergeDecision(
  this: FocusAgentEndpointContext,
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

async function createAgentTeamMergeReview(
  this: FocusAgentEndpointContext,
  sessionId: string,
  request: FocusAgentAgentTeamCreateMergeReviewRequest = {},
): Promise<FocusAgentAgentTeamMergeReviewResponse> {
  return this.requestJson<FocusAgentAgentTeamMergeReviewResponse>(
    `/v1/agent-team/sessions/${encodeURIComponent(sessionId)}/merge-review`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
    true,
  );
}

async function listAgentTeamMergeReviews(
  this: FocusAgentEndpointContext,
  sessionId: string,
): Promise<FocusAgentAgentTeamMergeReviewListResponse> {
  return this.requestJson<FocusAgentAgentTeamMergeReviewListResponse>(
    `/v1/agent-team/sessions/${encodeURIComponent(sessionId)}/merge-review`,
    {
      method: "GET",
      headers: {},
    },
    true,
  );
}

async function updateAgentTeamMergeReview(
  this: FocusAgentEndpointContext,
  sessionId: string,
  reviewId: string,
  request: FocusAgentAgentTeamUpdateMergeReviewRequest,
): Promise<FocusAgentAgentTeamMergeReviewResponse> {
  return this.requestJson<FocusAgentAgentTeamMergeReviewResponse>(
    `/v1/agent-team/sessions/${encodeURIComponent(sessionId)}/merge-review/${encodeURIComponent(reviewId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
    true,
  );
}

async function previewAgentTeamMergeReview(
  this: FocusAgentEndpointContext,
  sessionId: string,
  reviewId: string,
  request: FocusAgentAgentTeamMergeReviewPreviewRequest = {},
): Promise<FocusAgentAgentTeamMergeReviewPreviewResponse> {
  return this.requestJson<FocusAgentAgentTeamMergeReviewPreviewResponse>(
    `/v1/agent-team/sessions/${encodeURIComponent(sessionId)}/merge-review/${encodeURIComponent(reviewId)}/preview`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
    true,
  );
}

async function applyAgentTeamMergeReview(
  this: FocusAgentEndpointContext,
  sessionId: string,
  reviewId: string,
  request: FocusAgentAgentTeamMergeReviewApplyRequest = {},
): Promise<FocusAgentAgentTeamMergeReviewResponse> {
  return this.requestJson<FocusAgentAgentTeamMergeReviewResponse>(
    `/v1/agent-team/sessions/${encodeURIComponent(sessionId)}/merge-review/${encodeURIComponent(reviewId)}/apply`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
    true,
  );
}

async function rejectAgentTeamMergeReview(
  this: FocusAgentEndpointContext,
  sessionId: string,
  reviewId: string,
  request: FocusAgentAgentTeamMergeReviewRejectRequest = {},
): Promise<FocusAgentAgentTeamMergeReviewResponse> {
  return this.requestJson<FocusAgentAgentTeamMergeReviewResponse>(
    `/v1/agent-team/sessions/${encodeURIComponent(sessionId)}/merge-review/${encodeURIComponent(reviewId)}/reject`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
    true,
  );
}

async function captureAgentTeamMergeReview(
  this: FocusAgentEndpointContext,
  sessionId: string,
  reviewId: string,
): Promise<Record<string, unknown>> {
  return this.requestJson<Record<string, unknown>>(
    `/v1/agent-team/sessions/${encodeURIComponent(sessionId)}/merge-review/${encodeURIComponent(reviewId)}/capture`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    },
    true,
  );
}

export interface AgentTeamEndpoints {
  createAgentTeamSession: OmitThisParameter<typeof createAgentTeamSession>;
  listAgentTeamSessions: OmitThisParameter<typeof listAgentTeamSessions>;
  getAgentTeamSession: OmitThisParameter<typeof getAgentTeamSession>;
  getAgentTeamSessionView: OmitThisParameter<typeof getAgentTeamSessionView>;
  planAgentTeamSession: OmitThisParameter<typeof planAgentTeamSession>;
  runAgentTeamSession: OmitThisParameter<typeof runAgentTeamSession>;
  dispatchAgentTeamSession: OmitThisParameter<typeof dispatchAgentTeamSession>;
  createAgentTeamTask: OmitThisParameter<typeof createAgentTeamTask>;
  listAgentTeamTasks: OmitThisParameter<typeof listAgentTeamTasks>;
  getAgentTeamTaskStatus: OmitThisParameter<typeof getAgentTeamTaskStatus>;
  updateAgentTeamTask: OmitThisParameter<typeof updateAgentTeamTask>;
  runAgentTeamTask: OmitThisParameter<typeof runAgentTeamTask>;
  retryAgentTeamTask: OmitThisParameter<typeof retryAgentTeamTask>;
  cancelAgentTeamTask: OmitThisParameter<typeof cancelAgentTeamTask>;
  cancelAgentTeamSession: OmitThisParameter<typeof cancelAgentTeamSession>;
  recordAgentTeamTaskOutput: OmitThisParameter<typeof recordAgentTeamTaskOutput>;
  prepareAgentTeamMergeBundle: OmitThisParameter<typeof prepareAgentTeamMergeBundle>;
  recordAgentTeamMergeDecision: OmitThisParameter<typeof recordAgentTeamMergeDecision>;
  createAgentTeamMergeReview: OmitThisParameter<typeof createAgentTeamMergeReview>;
  listAgentTeamMergeReviews: OmitThisParameter<typeof listAgentTeamMergeReviews>;
  updateAgentTeamMergeReview: OmitThisParameter<typeof updateAgentTeamMergeReview>;
  previewAgentTeamMergeReview: OmitThisParameter<typeof previewAgentTeamMergeReview>;
  applyAgentTeamMergeReview: OmitThisParameter<typeof applyAgentTeamMergeReview>;
  rejectAgentTeamMergeReview: OmitThisParameter<typeof rejectAgentTeamMergeReview>;
  captureAgentTeamMergeReview: OmitThisParameter<typeof captureAgentTeamMergeReview>;
  listAgentTeamToolApprovals: OmitThisParameter<typeof listAgentTeamToolApprovals>;
  decideAgentTeamToolApproval: OmitThisParameter<typeof decideAgentTeamToolApproval>;
  approveAgentTeamToolApproval: OmitThisParameter<typeof approveAgentTeamToolApproval>;
  rejectAgentTeamToolApproval: OmitThisParameter<typeof rejectAgentTeamToolApproval>;
}

const agentTeamEndpoints: FocusAgentEndpointMethodMap<AgentTeamEndpoints> = {
  createAgentTeamSession,
  listAgentTeamSessions,
  getAgentTeamSession,
  getAgentTeamSessionView,
  planAgentTeamSession,
  runAgentTeamSession,
  dispatchAgentTeamSession,
  createAgentTeamTask,
  listAgentTeamTasks,
  getAgentTeamTaskStatus,
  updateAgentTeamTask,
  runAgentTeamTask,
  retryAgentTeamTask,
  cancelAgentTeamTask,
  cancelAgentTeamSession,
  recordAgentTeamTaskOutput,
  prepareAgentTeamMergeBundle,
  recordAgentTeamMergeDecision,
  createAgentTeamMergeReview,
  listAgentTeamMergeReviews,
  updateAgentTeamMergeReview,
  previewAgentTeamMergeReview,
  applyAgentTeamMergeReview,
  rejectAgentTeamMergeReview,
  captureAgentTeamMergeReview,
  listAgentTeamToolApprovals,
  decideAgentTeamToolApproval,
  approveAgentTeamToolApproval,
  rejectAgentTeamToolApproval,
};

export function applyAgentTeamEndpoints(Client: EndpointClientConstructor): void {
  applyEndpointMethods(Client, agentTeamEndpoints);
}
