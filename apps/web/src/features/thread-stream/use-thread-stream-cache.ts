import type { QueryClient } from "@tanstack/react-query";
import type { ThreadStateResponse } from "@focus-agent/web-sdk";

import { queryKeys } from "@/shared/query/query-keys";

export function applyTurnCompletedCacheUpdate(
	queryClient: QueryClient,
	threadId: string,
	threadState: Record<string, unknown> | null | undefined,
) {
	if (threadState && typeof threadState === "object") {
		queryClient.setQueryData(
			queryKeys.thread(threadId),
			threadState as unknown as ThreadStateResponse,
		);
	}
}

export function invalidateThreadStreamSurfaces(
	queryClient: QueryClient,
	rootThreadId: string,
	threadId: string,
) {
	return Promise.allSettled([
		queryClient.invalidateQueries({ queryKey: queryKeys.thread(threadId) }),
		queryClient.invalidateQueries({
			queryKey: queryKeys.branchTree(rootThreadId),
		}),
		queryClient.invalidateQueries({ queryKey: queryKeys.conversations }),
	]);
}

export function invalidateBranchActionNavigationSurfaces(
	queryClient: QueryClient,
	rootThreadId: string,
	sourceThreadId: string,
	targetThreadId: string,
) {
	void queryClient.invalidateQueries({ queryKey: queryKeys.conversations });
	void queryClient.invalidateQueries({
		queryKey: queryKeys.branchTree(rootThreadId),
	});
	void queryClient.invalidateQueries({
		queryKey: queryKeys.thread(sourceThreadId),
	});
	void queryClient.invalidateQueries({
		queryKey: queryKeys.thread(targetThreadId),
	});
}
