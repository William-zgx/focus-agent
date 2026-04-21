import {
  type FocusAgentTrajectoryListRequest,
  type FocusAgentTrajectoryListResponse,
} from "@focus-agent/web-sdk";
import { useQuery } from "@tanstack/react-query";

import { queryKeys } from "@/shared/query/query-keys";
import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";

export function useTrajectoryList(filters: FocusAgentTrajectoryListRequest) {
  const { client, ready } = useFocusAgent();
  const filtersKey = JSON.stringify(filters);

  return useQuery<FocusAgentTrajectoryListResponse>({
    queryKey: queryKeys.trajectoryList(filtersKey),
    queryFn: () => client.listTrajectoryTurns(filters),
    enabled: ready,
  });
}
