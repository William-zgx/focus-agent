import type { FocusAgentAttentionCursor } from "@focus-agent/web-sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef } from "react";

import { useThreadState } from "@/features/thread/use-thread-state";
import { queryKeys } from "@/shared/query/query-keys";
import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";

export function useThreadAttention(threadId: string) {
	const { client, ready } = useFocusAgent();
	const queryClient = useQueryClient();
	const queryKey = queryKeys.threadAttention(threadId);
	const query = useQuery({
		queryKey,
		queryFn: () => client.getThreadAttention(threadId),
		enabled: ready && Boolean(threadId),
		refetchOnReconnect: false,
	});
	const { data: threadState } = useThreadState(threadId);
	const previousThreadState = useRef<{
		threadId: string;
		value: unknown;
	} | null>(null);
	const refetch = query.refetch;
	useEffect(() => {
		const previous = previousThreadState.current;
		previousThreadState.current = { threadId, value: threadState };
		if (
			previous?.threadId === threadId &&
			previous.value &&
			threadState &&
			previous.value !== threadState
		) {
			void refetch();
		}
	}, [refetch, threadId, threadState]);

	const reviewed = useMutation({
		mutationFn: ({
			reviewedThreadId,
			cursor,
		}: {
			reviewedThreadId: string;
			cursor: FocusAgentAttentionCursor;
		}) => client.markThreadAttentionReviewed(reviewedThreadId, { cursor }),
		onSuccess: (_cursor, variables) =>
			queryClient.invalidateQueries({
				queryKey: queryKeys.threadAttention(variables.reviewedThreadId),
			}),
		onError: (_error, variables) =>
			queryClient.invalidateQueries({
				queryKey: queryKeys.threadAttention(variables.reviewedThreadId),
			}),
	});
	const markReviewed = useCallback(
		(cursor: FocusAgentAttentionCursor) =>
			reviewed.mutateAsync({ reviewedThreadId: threadId, cursor }),
		[reviewed.mutateAsync, threadId],
	);
	const isCurrentThreadReview =
		reviewed.variables?.reviewedThreadId === threadId;

	return {
		...query,
		markReviewed,
		reviewError: isCurrentThreadReview ? reviewed.error : null,
		isReviewing: reviewed.isPending && isCurrentThreadReview,
	};
}
