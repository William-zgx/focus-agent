import type { QueryClient } from "@tanstack/react-query";
import type { ThreadStateResponse } from "@focus-agent/web-sdk";

import { queryKeys } from "@/shared/query/query-keys";

function isCompleteThreadState(
	threadState: unknown,
): threadState is ThreadStateResponse {
	if (!threadState || typeof threadState !== "object") {
		return false;
	}
	const record = threadState as Record<string, unknown>;
	return (
		typeof record.thread_id === "string" &&
		typeof record.root_thread_id === "string" &&
		Array.isArray(record.messages) &&
		Array.isArray(record.branch_actions)
	);
}

export function applyTurnCompletedCacheUpdate(
	queryClient: QueryClient,
	threadId: string,
	threadState: Record<string, unknown> | null | undefined,
) {
	if (!threadState || typeof threadState !== "object") {
		return;
	}
	if (!isCompleteThreadState(threadState)) {
		void queryClient.invalidateQueries({ queryKey: queryKeys.thread(threadId) });
		return;
	}
	queryClient.setQueryData(queryKeys.thread(threadId), threadState);
}

export function invalidateThreadStreamSurfaces(
	queryClient: QueryClient,
	threadId: string,
) {
	return Promise.allSettled([
		queryClient.invalidateQueries({ queryKey: queryKeys.thread(threadId) }),
		queryClient.invalidateQueries({
			queryKey: queryKeys.branchTrees,
		}),
		queryClient.invalidateQueries({ queryKey: queryKeys.conversations }),
	]);
}

export function invalidateBranchActionNavigationSurfaces(
	queryClient: QueryClient,
	sourceThreadId: string,
	targetThreadId: string,
) {
	void queryClient.invalidateQueries({ queryKey: queryKeys.conversations });
	void queryClient.invalidateQueries({
		queryKey: queryKeys.branchTrees,
	});
	void queryClient.invalidateQueries({
		queryKey: queryKeys.thread(sourceThreadId),
	});
	void queryClient.invalidateQueries({
		queryKey: queryKeys.thread(targetThreadId),
	});
}
