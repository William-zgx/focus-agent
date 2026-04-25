import type {
  ThreadContextCompactRequest,
  ThreadContextCompactResponse,
  ThreadContextPreviewRequest,
  ThreadContextPreviewResponse,
} from "@focus-agent/web-sdk";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "@/shared/query/query-keys";
import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";

export function usePreviewThreadContext(threadId: string) {
  const { client } = useFocusAgent();

  return useMutation<ThreadContextPreviewResponse, Error, ThreadContextPreviewRequest>({
    mutationFn: (request) => client.previewThreadContext(threadId, request),
  });
}

export function useCompactThreadContext(threadId: string) {
  const { client } = useFocusAgent();
  const queryClient = useQueryClient();

  return useMutation<ThreadContextCompactResponse, Error, ThreadContextCompactRequest>({
    mutationFn: (request) => client.compactThreadContext(threadId, request),
    onSuccess: (threadState) => {
      queryClient.setQueryData(queryKeys.thread(threadId), threadState);
      void queryClient.invalidateQueries({ queryKey: queryKeys.thread(threadId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.branchTree(threadState.root_thread_id) });
    },
  });
}
