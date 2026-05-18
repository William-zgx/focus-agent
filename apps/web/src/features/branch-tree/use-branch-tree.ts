import { FocusAgentRequestError } from "@focus-agent/web-sdk";
import { useQuery } from "@tanstack/react-query";

import { queryKeys } from "@/shared/query/query-keys";
import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";

function isThreadResolutionUnavailable(error: unknown) {
	return (
		error instanceof FocusAgentRequestError &&
		(error.status === 404 || error.status === 405)
	);
}

export function useBranchTree(threadId: string) {
	const { client, ready } = useFocusAgent();

	return useQuery({
		queryKey: queryKeys.branchTree(threadId),
		queryFn: async () => {
			let rootThreadId = threadId;
			try {
				const resolution = await client.getThreadResolution(threadId);
				rootThreadId = resolution.root_thread_id || threadId;
			} catch (error) {
				if (!isThreadResolutionUnavailable(error)) throw error;
			}
			return client.getBranchTree(rootThreadId);
		},
		enabled: ready && Boolean(threadId),
	});
}
