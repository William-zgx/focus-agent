import { type FocusAgentTrajectoryDetailResponse } from "@focus-agent/web-sdk";
import { useQuery } from "@tanstack/react-query";

import { queryKeys } from "@/shared/query/query-keys";
import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";

export function useTrajectoryDetail(turnId: string) {
  const { client, ready } = useFocusAgent();

  return useQuery<FocusAgentTrajectoryDetailResponse>({
    queryKey: queryKeys.trajectoryDetail(turnId),
    queryFn: () => client.getTrajectoryTurn(turnId),
    enabled: ready && Boolean(turnId),
  });
}
