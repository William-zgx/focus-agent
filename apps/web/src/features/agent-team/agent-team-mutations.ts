import { useMutation, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "@/shared/query/query-keys";
import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";

import {
	invalidateMergeReviewCache,
	updateSessionCache,
} from "./agent-team-cache";
import type {
	AgentTeamActionResponse,
	AgentTeamCreateSessionRequest,
	AgentTeamMergeBundle,
	AgentTeamMergeDecisionRequest,
	AgentTeamMergeDecisionResponse,
	AgentTeamMergeReviewPreviewResponse,
	AgentTeamMergeReviewResponse,
	AgentTeamPlanSessionRequest,
	AgentTeamRunSessionRequest,
	AgentTeamRunTaskRequest,
	AgentTeamSession,
	AgentTeamToolApprovalDecisionRequest,
	AgentTeamToolApprovalDecisionResponse,
} from "./types";

function requireSessionId(sessionId: string | null): string {
	if (!sessionId) throw new Error("Missing Agent Team session id.");
	return sessionId;
}

/** Shared shape for mutations whose response is merged into the session cache. */
function useSessionActionMutation<TVariables>(
	sessionId: string | null,
	run: (
		sessionId: string,
		variables: TVariables,
	) => Promise<AgentTeamActionResponse>,
	{ refetchSession = false }: { refetchSession?: boolean } = {},
) {
	const queryClient = useQueryClient();

	return useMutation<AgentTeamActionResponse, Error, TVariables>({
		mutationFn: (variables) => run(requireSessionId(sessionId), variables),
		onSuccess: (data) => {
			updateSessionCache(queryClient, sessionId, data);
			if (refetchSession && sessionId)
				void queryClient.invalidateQueries({
					queryKey: queryKeys.agentTeamSession(sessionId),
				});
		},
	});
}

export function useCreateAgentTeamSession() {
	const { client } = useFocusAgent();
	const queryClient = useQueryClient();

	return useMutation<AgentTeamSession, Error, AgentTeamCreateSessionRequest>({
		mutationFn: (request) => client.createAgentTeamSession(request),
		onSuccess: (data) => {
			updateSessionCache(queryClient, data.session_id, data);
			void queryClient.invalidateQueries({ queryKey: ["agent-team-sessions"] });
		},
	});
}

export function usePlanAgentTeamSession(sessionId: string | null) {
	const { client } = useFocusAgent();
	return useSessionActionMutation<AgentTeamPlanSessionRequest | undefined>(
		sessionId,
		(id, request) => client.planAgentTeamSession(id, request),
	);
}

export function useRunAgentTeamSession(sessionId: string | null) {
	const { client } = useFocusAgent();
	return useSessionActionMutation<AgentTeamRunSessionRequest | undefined>(
		sessionId,
		(id, request) => client.runAgentTeamSession(id, request),
	);
}

export function useRunAgentTeamTask(sessionId: string | null) {
	const { client } = useFocusAgent();
	return useSessionActionMutation<{
		taskId: string;
		request?: AgentTeamRunTaskRequest;
	}>(sessionId, (_id, { taskId, request }) =>
		client.runAgentTeamTask(taskId, request),
	);
}

export function useRetryAgentTeamTask(sessionId: string | null) {
	const { client } = useFocusAgent();
	return useSessionActionMutation<{ taskId: string }>(
		sessionId,
		(_id, { taskId }) => client.retryAgentTeamTask(taskId),
		{ refetchSession: true },
	);
}

export function useCancelAgentTeamTask(sessionId: string | null) {
	const { client } = useFocusAgent();
	return useSessionActionMutation<{ taskId: string }>(
		sessionId,
		(_id, { taskId }) => client.cancelAgentTeamTask(taskId),
		{ refetchSession: true },
	);
}

export function useCancelAgentTeamSession(sessionId: string | null) {
	const { client } = useFocusAgent();
	const queryClient = useQueryClient();

	return useMutation<AgentTeamActionResponse, Error>({
		mutationFn: () =>
			client.cancelAgentTeamSession(requireSessionId(sessionId)),
		onSuccess: (data) => {
			updateSessionCache(queryClient, sessionId, data);
			void queryClient.invalidateQueries({
				queryKey: queryKeys.agentTeamSession(sessionId ?? ""),
			});
			void queryClient.invalidateQueries({ queryKey: ["agent-team-sessions"] });
		},
	});
}

export function useAgentTeamMergeProposal(sessionId: string | null) {
	const { client } = useFocusAgent();
	const queryClient = useQueryClient();

	return useMutation<AgentTeamMergeBundle, Error>({
		mutationFn: () =>
			client.prepareAgentTeamMergeBundle(requireSessionId(sessionId)),
		onSuccess: (data) => updateSessionCache(queryClient, sessionId, data),
	});
}

export function useAgentTeamMergeDecision(sessionId: string | null) {
	const { client } = useFocusAgent();
	const queryClient = useQueryClient();

	return useMutation<
		AgentTeamMergeDecisionResponse,
		Error,
		AgentTeamMergeDecisionRequest
	>({
		mutationFn: (request) =>
			client.recordAgentTeamMergeDecision(requireSessionId(sessionId), request),
		onSuccess: (data) => {
			updateSessionCache(queryClient, sessionId, data);
			void queryClient.invalidateQueries({
				queryKey: queryKeys.agentTeamSession(sessionId ?? ""),
			});
		},
	});
}

export function useDecideAgentTeamToolApproval(sessionId: string | null) {
	const { client } = useFocusAgent();
	const queryClient = useQueryClient();

	return useMutation<
		AgentTeamToolApprovalDecisionResponse,
		Error,
		{ requestId: string } & AgentTeamToolApprovalDecisionRequest
	>({
		mutationFn: ({ requestId, approved, reason }) => {
			const id = requireSessionId(sessionId);
			return approved
				? client.approveAgentTeamToolApproval(id, requestId, { reason })
				: client.rejectAgentTeamToolApproval(id, requestId, { reason });
		},
		onSuccess: () => {
			if (!sessionId) return;
			void queryClient.invalidateQueries({
				queryKey: queryKeys.agentTeamToolApprovals(sessionId),
			});
			void queryClient.invalidateQueries({
				queryKey: queryKeys.agentTeamSession(sessionId),
			});
		},
	});
}

export function useCreateAgentTeamMergeReview(sessionId: string | null) {
	const { client } = useFocusAgent();
	const queryClient = useQueryClient();

	return useMutation<
		AgentTeamMergeReviewResponse,
		Error,
		{ selected_task_ids?: string[]; excluded_task_ids?: string[] }
	>({
		mutationFn: (request) =>
			client.createAgentTeamMergeReview(requireSessionId(sessionId), request),
		onSuccess: () => invalidateMergeReviewCache(queryClient, sessionId),
	});
}

export function useUpdateAgentTeamMergeReview(sessionId: string | null) {
	const { client } = useFocusAgent();
	const queryClient = useQueryClient();

	return useMutation<
		AgentTeamMergeReviewResponse,
		Error,
		{
			reviewId: string;
			selected_task_ids?: string[];
			excluded_task_ids?: string[];
		}
	>({
		mutationFn: ({ reviewId, ...request }) =>
			client.updateAgentTeamMergeReview(
				requireSessionId(sessionId),
				reviewId,
				request,
			),
		onSuccess: () => invalidateMergeReviewCache(queryClient, sessionId),
	});
}

export function usePreviewAgentTeamMergeReview(sessionId: string | null) {
	const { client } = useFocusAgent();
	const queryClient = useQueryClient();

	return useMutation<
		AgentTeamMergeReviewPreviewResponse,
		Error,
		{ reviewId: string }
	>({
		mutationFn: ({ reviewId }) =>
			client.previewAgentTeamMergeReview(requireSessionId(sessionId), reviewId),
		onSuccess: () => invalidateMergeReviewCache(queryClient, sessionId),
	});
}

export function useApplyAgentTeamMergeReview(sessionId: string | null) {
	const { client } = useFocusAgent();
	const queryClient = useQueryClient();

	return useMutation<AgentTeamMergeReviewResponse, Error, { reviewId: string }>(
		{
			mutationFn: ({ reviewId }) =>
				client.applyAgentTeamMergeReview(requireSessionId(sessionId), reviewId),
			onSuccess: () => {
				invalidateMergeReviewCache(queryClient, sessionId);
				if (sessionId)
					void queryClient.invalidateQueries({
						queryKey: queryKeys.agentTeamSession(sessionId),
					});
			},
		},
	);
}

export function useRejectAgentTeamMergeReview(sessionId: string | null) {
	const { client } = useFocusAgent();
	const queryClient = useQueryClient();

	return useMutation<AgentTeamMergeReviewResponse, Error, { reviewId: string }>(
		{
			mutationFn: ({ reviewId }) =>
				client.rejectAgentTeamMergeReview(
					requireSessionId(sessionId),
					reviewId,
					{ rationale: "Rejected from Agent Team adoption workbench." },
				),
			onSuccess: () => invalidateMergeReviewCache(queryClient, sessionId),
		},
	);
}

export function useCaptureAgentTeamMergeReview(sessionId: string | null) {
	const { client } = useFocusAgent();

	return useMutation<Record<string, unknown>, Error, { reviewId: string }>({
		mutationFn: ({ reviewId }) =>
			client.captureAgentTeamMergeReview(requireSessionId(sessionId), reviewId),
	});
}
