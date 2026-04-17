import { useQuery } from "@tanstack/react-query";

import { queryKeys } from "@/shared/query/query-keys";
import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";

export function useConversations() {
  const { client, ready } = useFocusAgent();

  return useQuery({
    queryKey: queryKeys.conversations,
    queryFn: () => client.listConversations(),
    enabled: ready,
  });
}
