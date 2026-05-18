import type {
	FocusAgentBranchDecisionDismissRequest,
	FocusAgentBranchDecisionEvent,
} from "@focus-agent/web-sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "@/shared/query/query-keys";
import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";

export function useBranchDecisionConfig() {
	const { client, ready } = useFocusAgent();

	return useQuery({
		queryKey: queryKeys.branchDecisionConfig,
		queryFn: () => client.getBranchDecisionConfig(),
		enabled: ready,
	});
}

export function useThreadBranchDecisions(threadId: string) {
	const { client, ready } = useFocusAgent();

	return useQuery({
		queryKey: queryKeys.threadBranchDecisions(threadId),
		queryFn: () => client.listThreadBranchDecisions(threadId, { limit: 20 }),
		enabled: ready && Boolean(threadId),
	});
}

export function useBranchDecisionActions({
	rootThreadId,
	threadId,
}: {
	rootThreadId?: string;
	threadId: string;
}) {
	const { client } = useFocusAgent();
	const queryClient = useQueryClient();

	const refresh = async () => {
		await Promise.all([
			queryClient.invalidateQueries({ queryKey: queryKeys.thread(threadId) }),
			queryClient.invalidateQueries({
				queryKey: queryKeys.threadBranchDecisions(threadId),
			}),
			rootThreadId
				? queryClient.invalidateQueries({
						queryKey: queryKeys.branchTrees,
					})
				: Promise.resolve(),
		]);
	};

	const promote = useMutation({
		mutationFn: (decision: FocusAgentBranchDecisionEvent) =>
			client.promoteBranchDecision(threadId, decision.decision_id),
		onSuccess: refresh,
	});

	const dismiss = useMutation({
		mutationFn: ({
			decision,
			request,
		}: {
			decision: FocusAgentBranchDecisionEvent;
			request?: FocusAgentBranchDecisionDismissRequest;
		}) => client.dismissBranchDecision(threadId, decision.decision_id, request),
		onSuccess: refresh,
	});

	return { dismiss, promote };
}
