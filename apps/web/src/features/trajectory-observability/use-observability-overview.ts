import {
  type FocusAgentObservabilityOverviewRequest,
  type FocusAgentObservabilityOverviewResponse,
} from "@focus-agent/web-sdk";
import { useQuery } from "@tanstack/react-query";

import { queryKeys } from "@/shared/query/query-keys";
import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";

export function useObservabilityOverview(filters: FocusAgentObservabilityOverviewRequest) {
  const { client, ready } = useFocusAgent();
  const filtersKey = JSON.stringify(filters);

  return useQuery<FocusAgentObservabilityOverviewResponse>({
    queryKey: queryKeys.observabilityOverview(filtersKey),
    queryFn: () => client.getObservabilityOverview(filters),
    enabled: ready,
  });
}
