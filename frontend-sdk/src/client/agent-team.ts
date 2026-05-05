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
  FocusAgentAgentTeamMergeBundle,
  FocusAgentAgentTeamMergeDecisionRequest,
  FocusAgentAgentTeamMergeDecisionResponse,
  FocusAgentAgentTeamPrepareMergeBundleRequest,
  FocusAgentAgentTeamRecordTaskOutputRequest,
  FocusAgentAgentTeamRecordTaskOutputResponse,
  FocusAgentAgentTeamSession,
  FocusAgentAgentTeamSessionView,
  FocusAgentAgentTeamPlanningMetadata,
  FocusAgentAgentTeamSessionListResponse,
  FocusAgentAgentTeamTask,
  FocusAgentAgentTeamTaskOutput,
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
  recordAgentTeamTaskOutput: OmitThisParameter<typeof recordAgentTeamTaskOutput>;
  prepareAgentTeamMergeBundle: OmitThisParameter<typeof prepareAgentTeamMergeBundle>;
  recordAgentTeamMergeDecision: OmitThisParameter<typeof recordAgentTeamMergeDecision>;
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
  recordAgentTeamTaskOutput,
  prepareAgentTeamMergeBundle,
  recordAgentTeamMergeDecision,
};

export function applyAgentTeamEndpoints(Client: EndpointClientConstructor): void {
  applyEndpointMethods(Client, agentTeamEndpoints);
}
