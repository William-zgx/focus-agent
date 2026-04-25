import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "@/shared/query/query-keys";
import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";

import type {
  AgentTeamClientContract,
  AgentTeamCreateSessionRequest,
  AgentTeamCreateTaskRequest,
  AgentTeamDispatchRequest,
  AgentTeamListSessionsRequest,
  AgentTeamMergeBundle,
  AgentTeamSession,
  AgentTeamSessionListResponse,
  AgentTeamSessionView,
  AgentTeamTask,
} from "./types";

function agentTeamClient(client: unknown): Partial<AgentTeamClientContract> {
  return client as Partial<AgentTeamClientContract>;
}

function missingSdkMethod(method: keyof AgentTeamClientContract): Error {
  return new Error(`Agent Team SDK method ${method} is unavailable. Rebuild the SDK slice with the Agent Team endpoint contract.`);
}

export function useAgentTeamSession(sessionId: string | null) {
  const { client, ready } = useFocusAgent();
  const agentTeam = agentTeamClient(client);

  return useQuery<AgentTeamSession | AgentTeamSessionView>({
    queryKey: sessionId ? queryKeys.agentTeamSession(sessionId) : queryKeys.agentTeamSession(""),
    queryFn: async () => {
      if (!sessionId) throw new Error("Missing Agent Team session id.");
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
      };
    },
    enabled: ready && Boolean(sessionId),
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
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentTeamSession(sessionId) });
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
    onSuccess: () => {
      if (sessionId) void queryClient.invalidateQueries({ queryKey: queryKeys.agentTeamSession(sessionId) });
    },
  });
}

export function useDispatchAgentTeamSession(sessionId: string | null) {
  const { client } = useFocusAgent();
  const queryClient = useQueryClient();
  const agentTeam = agentTeamClient(client);

  return useMutation<AgentTeamSessionView, Error, AgentTeamDispatchRequest | undefined>({
    mutationFn: async (request) => {
      if (!sessionId) throw new Error("Missing Agent Team session id.");
      if (!agentTeam.dispatchAgentTeamSession) throw missingSdkMethod("dispatchAgentTeamSession");
      const response = await agentTeam.dispatchAgentTeamSession(sessionId, request);
      const tasks = "tasks" in response ? response.tasks : response.items;
      return {
        session: response.session,
        tasks: tasks ?? [],
        artifacts: "artifacts" in response ? response.artifacts : [],
        merge_bundle: "merge_bundle" in response ? response.merge_bundle : null,
      };
    },
    onSuccess: () => {
      if (sessionId) void queryClient.invalidateQueries({ queryKey: queryKeys.agentTeamSession(sessionId) });
    },
  });
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
    onSuccess: () => {
      if (sessionId) void queryClient.invalidateQueries({ queryKey: queryKeys.agentTeamSession(sessionId) });
    },
  });
}
