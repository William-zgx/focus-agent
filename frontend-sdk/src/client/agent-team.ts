import { buildAgentTeamQueryString } from "./query";
import { applyEndpointMethods } from "./endpoint";
import type { EndpointClientConstructor, FocusAgentEndpointContext, FocusAgentEndpointMethodMap } from "./endpoint";
import type {
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
} from "../types";

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
  dispatchAgentTeamSession: OmitThisParameter<typeof dispatchAgentTeamSession>;
  createAgentTeamTask: OmitThisParameter<typeof createAgentTeamTask>;
  listAgentTeamTasks: OmitThisParameter<typeof listAgentTeamTasks>;
  getAgentTeamTaskStatus: OmitThisParameter<typeof getAgentTeamTaskStatus>;
  updateAgentTeamTask: OmitThisParameter<typeof updateAgentTeamTask>;
  recordAgentTeamTaskOutput: OmitThisParameter<typeof recordAgentTeamTaskOutput>;
  prepareAgentTeamMergeBundle: OmitThisParameter<typeof prepareAgentTeamMergeBundle>;
  recordAgentTeamMergeDecision: OmitThisParameter<typeof recordAgentTeamMergeDecision>;
}

const agentTeamEndpoints: FocusAgentEndpointMethodMap<AgentTeamEndpoints> = {
  createAgentTeamSession,
  listAgentTeamSessions,
  getAgentTeamSession,
  dispatchAgentTeamSession,
  createAgentTeamTask,
  listAgentTeamTasks,
  getAgentTeamTaskStatus,
  updateAgentTeamTask,
  recordAgentTeamTaskOutput,
  prepareAgentTeamMergeBundle,
  recordAgentTeamMergeDecision,
};

export function applyAgentTeamEndpoints(Client: EndpointClientConstructor): void {
  applyEndpointMethods(Client, agentTeamEndpoints);
}
