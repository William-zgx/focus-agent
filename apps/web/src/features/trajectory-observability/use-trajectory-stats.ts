import {
  type FocusAgentTrajectoryStatsRequest,
  type FocusAgentTrajectoryStatsResponse,
} from "@focus-agent/web-sdk";
import { useQuery } from "@tanstack/react-query";

import { queryKeys } from "@/shared/query/query-keys";
import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";

export function useTrajectoryStats(filters: FocusAgentTrajectoryStatsRequest) {
  const { client, ready } = useFocusAgent();
  const filtersKey = JSON.stringify(filters);

  return useQuery<FocusAgentTrajectoryStatsResponse>({
    queryKey: queryKeys.trajectoryStats(filtersKey),
    queryFn: () => client.getTrajectoryStats(filters),
    enabled: ready,
  });
}
