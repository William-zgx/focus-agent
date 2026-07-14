import { useQuery } from "@tanstack/react-query";

import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";

import type {
	AgentTeamClientContract,
	AgentTeamEvidenceListResponse,
	AgentTeamReadiness,
} from "./types";

function agentTeamClient(client: unknown): Partial<AgentTeamClientContract> {
	return client as Partial<AgentTeamClientContract>;
}

function missingSdkMethod(method: keyof AgentTeamClientContract): Error {
	return new Error(
		`Agent Team SDK method ${method} is unavailable. Rebuild the SDK slice with the Agent Team endpoint contract.`,
	);
}

function supportsV2Evidence(readiness: AgentTeamReadiness | null | undefined) {
	return Boolean(
		readiness?.enabled &&
			readiness.service_available &&
			readiness.capabilities.evidence_queries,
	);
}

export function useAgentTeamReadiness({
	enabled = true,
}: {
	enabled?: boolean;
} = {}) {
	const { client, ready } = useFocusAgent();
	const agentTeam = agentTeamClient(client);
	const available = Boolean(agentTeam.getAgentTeamReadiness);

	return useQuery<AgentTeamReadiness | null>({
		queryKey: ["agent-team-v2-readiness"],
		queryFn: async () => {
			if (!agentTeam.getAgentTeamReadiness) return null;
			return agentTeam.getAgentTeamReadiness();
		},
		enabled: enabled && ready && available,
		retry: false,
		staleTime: 30_000,
	});
}

export function useAgentTeamEvidence(
	sessionId: string | null,
	{ enabled = true, poll = false }: { enabled?: boolean; poll?: boolean } = {},
) {
	const { client, ready } = useFocusAgent();
	const agentTeam = agentTeamClient(client);
	const readinessQuery = useAgentTeamReadiness({ enabled });
	const available = Boolean(agentTeam.listAgentTeamEvidence);
	const canQuery =
		enabled &&
		ready &&
		Boolean(sessionId) &&
		available &&
		supportsV2Evidence(readinessQuery.data);

	return useQuery<AgentTeamEvidenceListResponse>({
		queryKey: sessionId
			? ["agent-team-v2-evidence", sessionId]
			: ["agent-team-v2-evidence", ""],
		queryFn: async () => {
			if (!sessionId) throw new Error("Missing Agent Team session id.");
			if (!agentTeam.listAgentTeamEvidence)
				throw missingSdkMethod("listAgentTeamEvidence");
			return agentTeam.listAgentTeamEvidence(sessionId);
		},
		enabled: canQuery,
		refetchInterval: poll ? 1500 : false,
		retry: false,
	});
}
