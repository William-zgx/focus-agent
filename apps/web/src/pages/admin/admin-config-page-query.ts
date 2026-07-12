import type { FocusAgentAdminConfig } from "@focus-agent/web-sdk";
import { useQuery } from "@tanstack/react-query";

import { useAdminConfig } from "@/features/admin-config/use-admin-config";
import { appEnv } from "@/shared/config/env";
import { queryKeys } from "@/shared/query/query-keys";
import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";

export function useSelectedAdminConfigQuery() {
	const { client, isAdmin, ready } = useFocusAgent();
	const adminConfigQuery = useAdminConfig();
	const deviceLocalConfigQuery = useQuery<FocusAgentAdminConfig>({
		queryKey: queryKeys.adminConfig,
		queryFn: () => client.getAdminConfig(),
		enabled: appEnv.useLocalRuntime && ready && !isAdmin,
	});

	return appEnv.useLocalRuntime ? deviceLocalConfigQuery : adminConfigQuery;
}
