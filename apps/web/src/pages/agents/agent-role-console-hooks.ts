import type {
	FocusAgentArtifactListResponse,
	FocusAgentCapabilityListResponse,
	FocusAgentContextArtifactListResponse,
	FocusAgentContextDecisionListResponse,
	FocusAgentContextMemoryEvidenceListResponse,
	FocusAgentContextPolicyResponse,
	FocusAgentCriticVerdictListResponse,
	FocusAgentDelegationPolicyResponse,
	FocusAgentDelegationRunListResponse,
	FocusAgentFeedbackTrendResponse,
	FocusAgentMemoryCuratorDecisionListResponse,
	FocusAgentMemoryCuratorPolicyResponse,
	FocusAgentModelRouterDecisionListResponse,
	FocusAgentModelRouterPolicyResponse,
	FocusAgentReviewQueueListResponse,
	FocusAgentRoleDecisionListResponse,
	FocusAgentRolePolicyResponse,
	FocusAgentSelfRepairFailureListResponse,
	FocusAgentSkillCatalogResponse,
	FocusAgentSkillSelectionListResponse,
	FocusAgentTaskLedgerPolicyResponse,
	FocusAgentTaskLedgerRunListResponse,
	FocusAgentToolRouteDecisionListResponse,
} from "@focus-agent/web-sdk";
import { useQuery } from "@tanstack/react-query";

import { queryKeys } from "@/shared/query/query-keys";
import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";

export function useAgentRolePolicy() {
	const { client, ready } = useFocusAgent();
	return useQuery<FocusAgentRolePolicyResponse>({
		queryKey: queryKeys.agentRolePolicy,
		queryFn: () => client.getAgentRolePolicy(),
		enabled: ready,
	});
}

export function useAgentRoleDecisions() {
	const { client, ready } = useFocusAgent();
	return useQuery<FocusAgentRoleDecisionListResponse>({
		queryKey: queryKeys.agentRoleDecisions(50),
		queryFn: () => client.listAgentRoleDecisions(50),
		enabled: ready,
	});
}

export function useAgentCapabilities() {
	const { client, ready } = useFocusAgent();
	return useQuery<FocusAgentCapabilityListResponse>({
		queryKey: queryKeys.agentCapabilities,
		queryFn: () => client.listAgentCapabilities(),
		enabled: ready,
	});
}

export function useAgentToolRouteDecisions() {
	const { client, ready } = useFocusAgent();
	return useQuery<FocusAgentToolRouteDecisionListResponse>({
		queryKey: queryKeys.agentToolRouteDecisions(50),
		queryFn: () => client.listAgentToolRouteDecisions(50),
		enabled: ready,
	});
}

export function useAgentMemoryCuratorPolicy() {
	const { client, ready } = useFocusAgent();
	return useQuery<FocusAgentMemoryCuratorPolicyResponse>({
		queryKey: queryKeys.agentMemoryCuratorPolicy,
		queryFn: () => client.getAgentMemoryCuratorPolicy(),
		enabled: ready,
	});
}

export function useAgentMemoryCuratorDecisions() {
	const { client, ready } = useFocusAgent();
	return useQuery<FocusAgentMemoryCuratorDecisionListResponse>({
		queryKey: queryKeys.agentMemoryCuratorDecisions(50),
		queryFn: () => client.listAgentMemoryCuratorDecisions(50),
		enabled: ready,
	});
}

export function useAgentDelegationPolicy() {
	const { client, ready } = useFocusAgent();
	return useQuery<FocusAgentDelegationPolicyResponse>({
		queryKey: queryKeys.agentDelegationPolicy,
		queryFn: () => client.getAgentDelegationPolicy(),
		enabled: ready,
	});
}

export function useAgentDelegationRuns() {
	const { client, ready } = useFocusAgent();
	return useQuery<FocusAgentDelegationRunListResponse>({
		queryKey: queryKeys.agentDelegationRuns(50),
		queryFn: () => client.listAgentDelegationRuns(50),
		enabled: ready,
	});
}

export function useAgentModelRouterPolicy() {
	const { client, ready } = useFocusAgent();
	return useQuery<FocusAgentModelRouterPolicyResponse>({
		queryKey: queryKeys.agentModelRouterPolicy,
		queryFn: () => client.getAgentModelRouterPolicy(),
		enabled: ready,
	});
}

export function useAgentModelRouterDecisions() {
	const { client, ready } = useFocusAgent();
	return useQuery<FocusAgentModelRouterDecisionListResponse>({
		queryKey: queryKeys.agentModelRouterDecisions(50),
		queryFn: () => client.listAgentModelRouterDecisions(50),
		enabled: ready,
	});
}

export function useAgentSelfRepairFailures() {
	const { client, ready } = useFocusAgent();
	return useQuery<FocusAgentSelfRepairFailureListResponse>({
		queryKey: queryKeys.agentSelfRepairFailures(50),
		queryFn: () => client.listAgentSelfRepairFailures(50),
		enabled: ready,
	});
}

export function useAgentReviewQueue() {
	const { client, ready } = useFocusAgent();
	return useQuery<FocusAgentReviewQueueListResponse>({
		queryKey: queryKeys.agentReviewQueue(50),
		queryFn: () => client.listAgentReviewQueue(50),
		enabled: ready,
	});
}

export function useAgentContextPolicy() {
	const { client, ready } = useFocusAgent();
	return useQuery<FocusAgentContextPolicyResponse>({
		queryKey: queryKeys.agentContextPolicy,
		queryFn: () => client.getAgentContextPolicy(),
		enabled: ready,
	});
}

export function useAgentContextDecisions() {
	const { client, ready } = useFocusAgent();
	return useQuery<FocusAgentContextDecisionListResponse>({
		queryKey: queryKeys.agentContextDecisions(50),
		queryFn: () => client.listAgentContextDecisions(50),
		enabled: ready,
	});
}

export function useAgentContextArtifacts() {
	const { client, ready } = useFocusAgent();
	return useQuery<FocusAgentContextArtifactListResponse>({
		queryKey: queryKeys.agentContextArtifacts(50),
		queryFn: () => client.listAgentContextArtifacts(50),
		enabled: ready,
	});
}

export function useAgentContextEvidence() {
	const { client, ready } = useFocusAgent();
	return useQuery<FocusAgentContextMemoryEvidenceListResponse>({
		queryKey: queryKeys.agentContextEvidence("recent"),
		queryFn: () => client.listAgentContextEvidence({ limit: 20 }),
		enabled: ready,
		retry: false,
	});
}

export function useAgentSkillCatalog() {
	const { client, ready } = useFocusAgent();
	return useQuery<FocusAgentSkillCatalogResponse>({
		queryKey: queryKeys.agentSkillCatalog,
		queryFn: () => client.getAgentSkillCatalog(),
		enabled: ready,
		retry: false,
	});
}

export function useAgentSkillSelections() {
	const { client, ready } = useFocusAgent();
	return useQuery<FocusAgentSkillSelectionListResponse>({
		queryKey: queryKeys.agentSkillSelections(50),
		queryFn: () => client.listAgentSkillSelections(50),
		enabled: ready,
		retry: false,
	});
}

export function useAgentFeedbackTrend() {
	const { client, ready } = useFocusAgent();
	return useQuery<FocusAgentFeedbackTrendResponse>({
		queryKey: queryKeys.agentFeedbackTrend,
		queryFn: () => client.getAgentFeedbackTrend(),
		enabled: ready,
		retry: false,
	});
}

export function useAgentTaskLedgerPolicy() {
	const { client, ready } = useFocusAgent();
	return useQuery<FocusAgentTaskLedgerPolicyResponse>({
		queryKey: queryKeys.agentTaskLedgerPolicy,
		queryFn: () => client.getAgentTaskLedgerPolicy(),
		enabled: ready,
	});
}

export function useAgentTaskLedgerRuns() {
	const { client, ready } = useFocusAgent();
	return useQuery<FocusAgentTaskLedgerRunListResponse>({
		queryKey: queryKeys.agentTaskLedgerRuns(50),
		queryFn: () => client.listAgentTaskLedgerRuns(50),
		enabled: ready,
	});
}

export function useAgentArtifacts() {
	const { client, ready } = useFocusAgent();
	return useQuery<FocusAgentArtifactListResponse>({
		queryKey: queryKeys.agentArtifacts(50),
		queryFn: () => client.listAgentArtifacts(50),
		enabled: ready,
	});
}

export function useAgentCriticVerdicts() {
	const { client, ready } = useFocusAgent();
	return useQuery<FocusAgentCriticVerdictListResponse>({
		queryKey: queryKeys.agentCriticVerdicts(50),
		queryFn: () => client.listAgentCriticVerdicts(50),
		enabled: ready,
	});
}
