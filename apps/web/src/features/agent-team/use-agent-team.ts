import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "@/shared/query/query-keys";
import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";

import type {
  AgentTeamActionResponse,
  AgentTeamClientContract,
  AgentTeamCreateSessionRequest,
  AgentTeamCreateTaskRequest,
  AgentTeamDispatchRequest,
  AgentTeamListSessionsRequest,
  AgentTeamMergeDecisionRequest,
  AgentTeamMergeDecisionResponse,
  AgentTeamPlanSessionRequest,
  AgentTeamRunSessionRequest,
  AgentTeamRunTaskRequest,
  AgentTeamMergeBundle,
  AgentTeamSession,
  AgentTeamSessionListResponse,
  AgentTeamSessionView,
  AgentTeamTask,
} from "./types";
import { isTaskQueued, isTaskRunning, normalizeSessionView } from "./agent-team-workbench-utils";

function agentTeamClient(client: unknown): Partial<AgentTeamClientContract> {
  return client as Partial<AgentTeamClientContract>;
}

function missingSdkMethod(method: keyof AgentTeamClientContract): Error {
  return new Error(`Agent Team SDK method ${method} is unavailable. Rebuild the SDK slice with the Agent Team endpoint contract.`);
}

function shouldPollSessionView(data: AgentTeamSession | AgentTeamSessionView | undefined) {
  const view = normalizeSessionView(data);
  if (!view) return false;
  return (
    view.session.status === "planning" ||
    view.session.status === "running" ||
    view.tasks.some((task) => isTaskQueued(task) || isTaskRunning(task))
  );
}

function coerceViewResponse(
  response: AgentTeamActionResponse,
  previous: AgentTeamSession | AgentTeamSessionView | undefined,
): AgentTeamSessionView | null {
  const previousView = normalizeSessionView(previous);
  const responseView =
    "session" in response || ("root_thread_id" in response && "goal" in response)
      ? normalizeSessionView(response as AgentTeamSession | AgentTeamSessionView)
      : null;
  if (responseView) {
    const mergeDecision = coerceMergeDecision(response);
    return {
      ...responseView,
      session: {
        ...responseView.session,
        merge_decision: mergeDecision ?? responseView.session.merge_decision ?? previousView?.session.merge_decision ?? null,
      },
      tasks: responseView.tasks.length ? responseView.tasks : previousView?.tasks ?? [],
      outputs: responseView.outputs?.length ? responseView.outputs : previousView?.outputs ?? [],
      artifacts: responseView.artifacts?.length ? responseView.artifacts : previousView?.artifacts ?? [],
      merge_bundle: responseView.merge_bundle ?? previousView?.merge_bundle ?? null,
      run: responseView.run ?? previousView?.run ?? null,
    };
  }

  const taskResponse = "task" in response && response.task ? response.task : response;
  if ("task_id" in taskResponse) {
    if (!previousView) return null;
    const nextTask = taskResponse as AgentTeamTask;
    const existingTask = previousView.tasks.some((task) => task.task_id === nextTask.task_id);
    return {
      ...previousView,
      tasks: existingTask
        ? previousView.tasks.map((task) => (task.task_id === nextTask.task_id ? nextTask : task))
        : [...previousView.tasks, nextTask],
    };
  }

  const mergeBundle =
    "summary" in response && "session_id" in response
      ? (response as AgentTeamMergeBundle)
      : "bundle" in response
        ? response.bundle ?? null
      : "merge_bundle" in response
        ? response.merge_bundle ?? null
        : null;
  if (mergeBundle && previousView) {
    return {
      ...previousView,
      session: {
        ...previousView.session,
        latest_merge_bundle: mergeBundle,
      },
      merge_bundle: mergeBundle,
    };
  }

  const mergeDecision = coerceMergeDecision(response);
  if (mergeDecision && previousView) {
    return {
      ...previousView,
      session: {
        ...previousView.session,
        ...(mergeDecision.session ?? {}),
        merge_decision: mergeDecision,
        latest_merge_bundle:
          mergeDecision.merge_bundle ?? mergeDecision.session?.latest_merge_bundle ?? previousView.session.latest_merge_bundle,
      },
      merge_bundle:
        mergeDecision.merge_bundle ??
        mergeDecision.session?.latest_merge_bundle ??
        previousView.merge_bundle ??
        null,
    };
  }

  return null;
}

function coerceMergeDecision(response: AgentTeamActionResponse): AgentTeamMergeDecisionResponse | null {
  if (!response || typeof response !== "object") return null;
  const record = response as Record<string, unknown>;
  if (record.merge_decision && typeof record.merge_decision === "object") {
    return record.merge_decision as AgentTeamMergeDecisionResponse;
  }
  if (record.decision && typeof record.decision === "object") {
    return record.decision as AgentTeamMergeDecisionResponse;
  }
  if (
    "action" in record ||
    "next_action" in record ||
    "approved" in record ||
    "apply" in record ||
    "rationale" in record
  ) {
    return response as AgentTeamMergeDecisionResponse;
  }
  return null;
}

function updateSessionCache(
  queryClient: ReturnType<typeof useQueryClient>,
  sessionId: string | null,
  response: AgentTeamActionResponse,
) {
  if (!sessionId) return;
  const queryKey = queryKeys.agentTeamSession(sessionId);
  const previous = queryClient.getQueryData<AgentTeamSession | AgentTeamSessionView>(queryKey);
  const nextView = coerceViewResponse(response, previous);
  if (nextView) {
    queryClient.setQueryData(queryKey, nextView);
    return;
  }
  void queryClient.invalidateQueries({ queryKey });
}

async function getLegacySessionView(
  agentTeam: Partial<AgentTeamClientContract>,
  sessionId: string,
): Promise<AgentTeamSession | AgentTeamSessionView> {
  if (!agentTeam.getAgentTeamSession) throw missingSdkMethod("getAgentTeamSession");
  const session = await agentTeam.getAgentTeamSession(sessionId);
  if ("session" in session) return session;
  if (!agentTeam.listAgentTeamTasks) return session;
  const taskResponse = await agentTeam.listAgentTeamTasks(sessionId);
  const tasks = Array.isArray(taskResponse) ? taskResponse : taskResponse.items ?? [];
  return {
    session,
    tasks,
    artifacts: [],
    merge_bundle: null,
    run: null,
  };
}

export function useAgentTeamSession(sessionId: string | null) {
  const { client, ready } = useFocusAgent();
  const agentTeam = agentTeamClient(client);

  return useQuery<AgentTeamSession | AgentTeamSessionView>({
    queryKey: sessionId ? queryKeys.agentTeamSession(sessionId) : queryKeys.agentTeamSession(""),
    queryFn: async () => {
      if (!sessionId) throw new Error("Missing Agent Team session id.");
      if (agentTeam.getAgentTeamSessionView) return agentTeam.getAgentTeamSessionView(sessionId);
      return getLegacySessionView(agentTeam, sessionId);
    },
    enabled: ready && Boolean(sessionId),
    refetchInterval: (query) => (shouldPollSessionView(query.state.data) ? 1500 : false),
  });
}

export function useAgentTeamSessions(request: AgentTeamListSessionsRequest = {}) {
  const { client, ready } = useFocusAgent();
  const agentTeam = agentTeamClient(client);
  const filtersKey = JSON.stringify(request);

  return useQuery<AgentTeamSessionListResponse>({
    queryKey: queryKeys.agentTeamSessions(filtersKey),
    queryFn: async () => {
      if (!agentTeam.listAgentTeamSessions) throw missingSdkMethod("listAgentTeamSessions");
      const response = await agentTeam.listAgentTeamSessions(request);
      const items = Array.isArray(response)
        ? response
        : response.items ?? ("sessions" in response ? response.sessions : undefined) ?? [];
      return { items, count: Array.isArray(response) ? items.length : response.count ?? items.length };
    },
    enabled: ready,
  });
}

export function useCreateAgentTeamSession() {
  const { client } = useFocusAgent();
  const queryClient = useQueryClient();
  const agentTeam = agentTeamClient(client);

  return useMutation<AgentTeamSession | AgentTeamSessionView, Error, AgentTeamCreateSessionRequest>({
    mutationFn: (request) => {
      if (!agentTeam.createAgentTeamSession) throw missingSdkMethod("createAgentTeamSession");
      return agentTeam.createAgentTeamSession(request);
    },
    onSuccess: (data) => {
      const sessionId = "session" in data ? data.session.session_id : data.session_id;
      updateSessionCache(queryClient, sessionId, data);
      void queryClient.invalidateQueries({ queryKey: ["agent-team-sessions"] });
    },
  });
}

export function useCreateAgentTeamTask(sessionId: string | null) {
  const { client } = useFocusAgent();
  const queryClient = useQueryClient();
  const agentTeam = agentTeamClient(client);

  return useMutation<AgentTeamTask | AgentTeamSessionView, Error, AgentTeamCreateTaskRequest>({
    mutationFn: (request) => {
      if (!sessionId) throw new Error("Missing Agent Team session id.");
      if (!agentTeam.createAgentTeamTask) throw missingSdkMethod("createAgentTeamTask");
      return agentTeam.createAgentTeamTask(sessionId, request);
    },
    onSuccess: (data) => {
      updateSessionCache(queryClient, sessionId, data);
    },
  });
}

export function usePlanAgentTeamSession(sessionId: string | null) {
  const { client } = useFocusAgent();
  const queryClient = useQueryClient();
  const agentTeam = agentTeamClient(client);

  return useMutation<AgentTeamActionResponse, Error, AgentTeamPlanSessionRequest | undefined>({
    mutationFn: async (request) => {
      if (!sessionId) throw new Error("Missing Agent Team session id.");
      if (agentTeam.planAgentTeamSession) return agentTeam.planAgentTeamSession(sessionId, request);
      if (!agentTeam.dispatchAgentTeamSession) throw missingSdkMethod("dispatchAgentTeamSession");
      return agentTeam.dispatchAgentTeamSession(sessionId, {
        create_branches: request?.create_branches ?? true,
        parent_thread_id: request?.parent_thread_id,
      });
    },
    onSuccess: (data) => {
      updateSessionCache(queryClient, sessionId, data);
    },
  });
}

export function useRunAgentTeamSession(sessionId: string | null) {
  const { client } = useFocusAgent();
  const queryClient = useQueryClient();
  const agentTeam = agentTeamClient(client);

  return useMutation<AgentTeamActionResponse, Error, AgentTeamRunSessionRequest | undefined>({
    mutationFn: async (request) => {
      if (!sessionId) throw new Error("Missing Agent Team session id.");
      if (agentTeam.runAgentTeamSession) return agentTeam.runAgentTeamSession(sessionId, request);
      if (!agentTeam.dispatchAgentTeamSession) throw missingSdkMethod("dispatchAgentTeamSession");
      return agentTeam.dispatchAgentTeamSession(sessionId, { create_branches: true });
    },
    onSuccess: (data) => {
      updateSessionCache(queryClient, sessionId, data);
    },
  });
}

export function useRunAgentTeamTask(sessionId: string | null) {
  const { client } = useFocusAgent();
  const queryClient = useQueryClient();
  const agentTeam = agentTeamClient(client);

  return useMutation<AgentTeamActionResponse, Error, { taskId: string; request?: AgentTeamRunTaskRequest }>({
    mutationFn: async ({ taskId, request }) => {
      if (!sessionId) throw new Error("Missing Agent Team session id.");
      if (agentTeam.runAgentTeamTask) return agentTeam.runAgentTeamTask(taskId, request);
      if (!agentTeam.dispatchAgentTeamSession) throw missingSdkMethod("dispatchAgentTeamSession");
      return agentTeam.dispatchAgentTeamSession(sessionId, { create_branches: true });
    },
    onSuccess: (data) => {
      updateSessionCache(queryClient, sessionId, data);
    },
  });
}

export function useRetryAgentTeamTask(sessionId: string | null) {
  const { client } = useFocusAgent();
  const queryClient = useQueryClient();
  const agentTeam = agentTeamClient(client);

  return useMutation<AgentTeamActionResponse, Error, { taskId: string }>({
    mutationFn: async ({ taskId }) => {
      if (!sessionId) throw new Error("Missing Agent Team session id.");
      if (!agentTeam.retryAgentTeamTask) throw missingSdkMethod("retryAgentTeamTask");
      return agentTeam.retryAgentTeamTask(taskId);
    },
    onSuccess: (data) => {
      updateSessionCache(queryClient, sessionId, data);
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentTeamSession(sessionId ?? "") });
    },
  });
}

export function useCancelAgentTeamTask(sessionId: string | null) {
  const { client } = useFocusAgent();
  const queryClient = useQueryClient();
  const agentTeam = agentTeamClient(client);

  return useMutation<AgentTeamActionResponse, Error, { taskId: string }>({
    mutationFn: async ({ taskId }) => {
      if (!sessionId) throw new Error("Missing Agent Team session id.");
      if (!agentTeam.cancelAgentTeamTask) throw missingSdkMethod("cancelAgentTeamTask");
      return agentTeam.cancelAgentTeamTask(taskId);
    },
    onSuccess: (data) => {
      updateSessionCache(queryClient, sessionId, data);
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentTeamSession(sessionId ?? "") });
    },
  });
}

export function useCancelAgentTeamSession(sessionId: string | null) {
  const { client } = useFocusAgent();
  const queryClient = useQueryClient();
  const agentTeam = agentTeamClient(client);

  return useMutation<AgentTeamActionResponse, Error>({
    mutationFn: async () => {
      if (!sessionId) throw new Error("Missing Agent Team session id.");
      if (!agentTeam.cancelAgentTeamSession) throw missingSdkMethod("cancelAgentTeamSession");
      return agentTeam.cancelAgentTeamSession(sessionId);
    },
    onSuccess: (data) => {
      updateSessionCache(queryClient, sessionId, data);
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentTeamSession(sessionId ?? "") });
      void queryClient.invalidateQueries({ queryKey: ["agent-team-sessions"] });
    },
  });
}

export function useDispatchAgentTeamSession(sessionId: string | null) {
  return usePlanAgentTeamSession(sessionId);
}

export function useAgentTeamMergeProposal(sessionId: string | null) {
  const { client } = useFocusAgent();
  const queryClient = useQueryClient();
  const agentTeam = agentTeamClient(client);

  return useMutation<AgentTeamMergeBundle | AgentTeamSessionView, Error>({
    mutationFn: () => {
      if (!sessionId) throw new Error("Missing Agent Team session id.");
      if (agentTeam.prepareAgentTeamMergeBundle) {
        return agentTeam.prepareAgentTeamMergeBundle(sessionId);
      }
      if (agentTeam.createAgentTeamMergeProposal) return agentTeam.createAgentTeamMergeProposal(sessionId);
      throw missingSdkMethod("prepareAgentTeamMergeBundle");
    },
    onSuccess: (data) => {
      updateSessionCache(queryClient, sessionId, data);
    },
  });
}

export function useAgentTeamMergeDecision(sessionId: string | null) {
  const { client } = useFocusAgent();
  const queryClient = useQueryClient();
  const agentTeam = agentTeamClient(client);

  return useMutation<AgentTeamMergeDecisionResponse | AgentTeamSessionView, Error, AgentTeamMergeDecisionRequest>({
    mutationFn: (request) => {
      if (!sessionId) throw new Error("Missing Agent Team session id.");
      if (!agentTeam.recordAgentTeamMergeDecision) throw missingSdkMethod("recordAgentTeamMergeDecision");
      return agentTeam.recordAgentTeamMergeDecision(sessionId, request);
    },
    onSuccess: (data) => {
      updateSessionCache(queryClient, sessionId, data);
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentTeamSession(sessionId ?? "") });
    },
  });
}
