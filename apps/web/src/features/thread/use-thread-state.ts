import { useQuery } from "@tanstack/react-query";

import { queryKeys } from "@/shared/query/query-keys";
import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";

export function useThreadState(threadId: string) {
  const { client, ready } = useFocusAgent();

  return useQuery({
    queryKey: queryKeys.thread(threadId),
    queryFn: () => client.getThreadState(threadId),
    enabled: ready && Boolean(threadId),
  });
}
