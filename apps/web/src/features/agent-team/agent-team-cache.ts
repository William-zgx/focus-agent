import type { useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "@/shared/query/query-keys";
import { isRecord } from "@/shared/records";

import {
	isTaskQueued,
	isTaskRunning,
	normalizeSessionView,
} from "./agent-team-workbench-utils";
import type {
	AgentTeamActionResponse,
	AgentTeamMergeBundle,
	AgentTeamMergeDecisionResponse,
	AgentTeamSession,
	AgentTeamSessionView,
	AgentTeamTask,
} from "./types";

type QueryClient = ReturnType<typeof useQueryClient>;

export function invalidateMergeReviewCache(
	queryClient: QueryClient,
	sessionId: string | null,
) {
	if (!sessionId) return;
	void queryClient.invalidateQueries({
		queryKey: queryKeys.agentTeamMergeReviews(sessionId),
	});
}

export function shouldPollSessionView(
	data: AgentTeamSession | AgentTeamSessionView | undefined,
) {
	const view = normalizeSessionView(data);
	if (!view) return false;
	return (
		view.session.status === "planning" ||
		view.session.status === "running" ||
		view.tasks.some((task) => isTaskQueued(task) || isTaskRunning(task)) ||
		(view.pending_tool_approvals?.length ?? 0) > 0
	);
}

function isMergeDecisionResponse(
	response: AgentTeamActionResponse,
): response is AgentTeamMergeDecisionResponse {
	return "applied" in response && "merge_bundle" in response;
}

function isMergeBundle(
	response: AgentTeamActionResponse,
): response is AgentTeamMergeBundle {
	return "summary" in response && "session_id" in response;
}

/** Keeps cached tasks, outputs and run state the action response left out. */
function mergeWithPreviousView(
	responseView: AgentTeamSessionView,
	previousView: AgentTeamSessionView | null,
): AgentTeamSessionView {
	return {
		...responseView,
		session: {
			...responseView.session,
			merge_decision:
				responseView.session.merge_decision ??
				previousView?.session.merge_decision ??
				null,
		},
		tasks: responseView.tasks.length
			? responseView.tasks
			: (previousView?.tasks ?? []),
		outputs: responseView.outputs?.length
			? responseView.outputs
			: (previousView?.outputs ?? []),
		artifacts: responseView.artifacts?.length
			? responseView.artifacts
			: (previousView?.artifacts ?? []),
		merge_bundle:
			responseView.merge_bundle ?? previousView?.merge_bundle ?? null,
		run: responseView.run ?? previousView?.run ?? null,
		pending_tool_approvals:
			responseView.pending_tool_approvals ??
			previousView?.pending_tool_approvals ??
			[],
	};
}

/**
 * Merges an SDK Agent Team action response into the cached session view.
 * Returns null when the response cannot be merged and the view must be refetched.
 */
function coerceViewResponse(
	response: AgentTeamActionResponse,
	previous: AgentTeamSession | AgentTeamSessionView | undefined,
): AgentTeamSessionView | null {
	const previousView = normalizeSessionView(previous);

	if (isMergeDecisionResponse(response)) {
		if (!previousView) return null;
		const mergeBundle =
			response.merge_bundle ?? response.session.latest_merge_bundle ?? null;
		return {
			...previousView,
			session: {
				...previousView.session,
				...response.session,
				merge_decision: isRecord(response.decision)
					? response.decision
					: (response.session.merge_decision ??
						previousView.session.merge_decision ??
						null),
				latest_merge_bundle:
					mergeBundle ?? previousView.session.latest_merge_bundle,
			},
			merge_bundle: mergeBundle ?? previousView.merge_bundle ?? null,
		};
	}

	if (isMergeBundle(response)) {
		if (!previousView) return null;
		return {
			...previousView,
			session: { ...previousView.session, latest_merge_bundle: response },
			merge_bundle: response,
		};
	}

	if ("session" in response && response.session) {
		const responseView = normalizeSessionView({
			...response,
			session: response.session,
			tasks: response.tasks ?? [],
			artifacts: response.artifacts ?? [],
		});
		return responseView
			? mergeWithPreviousView(responseView, previousView)
			: null;
	}

	if ("root_thread_id" in response && "goal" in response) {
		const responseView = normalizeSessionView(response);
		return responseView
			? mergeWithPreviousView(responseView, previousView)
			: null;
	}

	const nextTask: AgentTeamTask | null =
		"task" in response
			? (response.task ?? null)
			: "task_id" in response
				? response
				: null;
	if (nextTask) {
		if (!previousView) return null;
		const existingTask = previousView.tasks.some(
			(task) => task.task_id === nextTask.task_id,
		);
		return {
			...previousView,
			tasks: existingTask
				? previousView.tasks.map((task) =>
						task.task_id === nextTask.task_id ? nextTask : task,
					)
				: [...previousView.tasks, nextTask],
			pending_tool_approvals:
				"pending_tool_approvals" in response
					? (response.pending_tool_approvals ?? [])
					: (previousView.pending_tool_approvals ?? []),
		};
	}

	return null;
}

export function updateSessionCache(
	queryClient: QueryClient,
	sessionId: string | null,
	response: AgentTeamActionResponse,
) {
	if (!sessionId) return;
	const queryKey = queryKeys.agentTeamSession(sessionId);
	const previous = queryClient.getQueryData<
		AgentTeamSession | AgentTeamSessionView
	>(queryKey);
	const nextView = coerceViewResponse(response, previous);
	if (nextView) {
		queryClient.setQueryData(queryKey, nextView);
		return;
	}
	void queryClient.invalidateQueries({ queryKey });
}
