import { useQuery } from "@tanstack/react-query";

import { queryKeys } from "@/shared/query/query-keys";
import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";

import { shouldPollSessionView } from "./agent-team-cache";
import type {
	AgentTeamEvidenceListResponse,
	AgentTeamListSessionsRequest,
	AgentTeamMergeReview,
	AgentTeamReadiness,
	AgentTeamSessionListResponse,
	AgentTeamSessionView,
	AgentTeamToolApproval,
} from "./types";

function supportsEvidenceQueries(
	readiness: AgentTeamReadiness | null | undefined,
) {
	return Boolean(
		readiness?.enabled &&
			readiness.service_available &&
			readiness.capabilities.evidence_queries,
	);
}

export function useAgentTeamSession(
	sessionId: string | null,
	{ enabled = true }: { enabled?: boolean } = {},
) {
	const { client, ready } = useFocusAgent();

	return useQuery<AgentTeamSessionView>({
		queryKey: queryKeys.agentTeamSession(sessionId ?? ""),
		queryFn: () => {
			if (!sessionId) throw new Error("Missing Agent Team session id.");
			return client.getAgentTeamSessionView(sessionId);
		},
		enabled: enabled && ready && Boolean(sessionId),
		refetchInterval: (query) =>
			shouldPollSessionView(query.state.data) ? 1500 : false,
	});
}

export function useAgentTeamSessions(
	request: AgentTeamListSessionsRequest = {},
) {
	const { client, ready } = useFocusAgent();

	return useQuery<AgentTeamSessionListResponse>({
		queryKey: queryKeys.agentTeamSessions(JSON.stringify(request)),
		queryFn: () => client.listAgentTeamSessions(request),
		enabled: ready,
	});
}

export function useAgentTeamReadiness({
	enabled = true,
}: {
	enabled?: boolean;
} = {}) {
	const { client, ready } = useFocusAgent();

	return useQuery<AgentTeamReadiness>({
		queryKey: ["agent-team-v2-readiness"],
		queryFn: () => client.getAgentTeamReadiness(),
		enabled: enabled && ready,
		retry: false,
		staleTime: 30_000,
	});
}

export function useAgentTeamEvidence(
	sessionId: string | null,
	{ enabled = true, poll = false }: { enabled?: boolean; poll?: boolean } = {},
) {
	const { client, ready } = useFocusAgent();
	const readinessQuery = useAgentTeamReadiness({ enabled });
	const canQuery =
		enabled &&
		ready &&
		Boolean(sessionId) &&
		supportsEvidenceQueries(readinessQuery.data);

	return useQuery<AgentTeamEvidenceListResponse>({
		queryKey: ["agent-team-v2-evidence", sessionId ?? ""],
		queryFn: () => {
			if (!sessionId) throw new Error("Missing Agent Team session id.");
			return client.listAgentTeamEvidence(sessionId);
		},
		enabled: canQuery,
		refetchInterval: poll ? 1500 : false,
		retry: false,
	});
}

export function useAgentTeamMergeReviews(sessionId: string | null) {
	const { client, ready } = useFocusAgent();

	return useQuery<{ items: AgentTeamMergeReview[]; count: number }>({
		queryKey: queryKeys.agentTeamMergeReviews(sessionId ?? ""),
		queryFn: async () => {
			if (!sessionId) throw new Error("Missing Agent Team session id.");
			const response = await client.listAgentTeamMergeReviews(sessionId);
			const items = response.items ?? [];
			return { items, count: response.count ?? items.length };
		},
		enabled: ready && Boolean(sessionId),
		retry: false,
	});
}

export function useAgentTeamToolApprovals(
	sessionId: string | null,
	{ enabled = true }: { enabled?: boolean } = {},
) {
	const { client, ready } = useFocusAgent();

	return useQuery<{ items: AgentTeamToolApproval[]; count: number }>({
		queryKey: queryKeys.agentTeamToolApprovals(sessionId ?? ""),
		queryFn: async () => {
			if (!sessionId) throw new Error("Missing Agent Team session id.");
			const response = await client.listAgentTeamToolApprovals(sessionId);
			return { items: response.items, count: response.count };
		},
		enabled: enabled && ready && Boolean(sessionId),
		refetchInterval: (query) =>
			(query.state.data?.items.length ?? 0) > 0 ? 1500 : false,
		retry: false,
	});
}
