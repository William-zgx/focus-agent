import { useQuery } from "@tanstack/react-query";

import { queryKeys } from "@/shared/query/query-keys";
import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";

export function useBranchTree(rootThreadId: string) {
  const { client, ready } = useFocusAgent();

  return useQuery({
    queryKey: queryKeys.branchTree(rootThreadId),
    queryFn: () => client.getBranchTree(rootThreadId),
    enabled: ready && Boolean(rootThreadId),
  });
}
