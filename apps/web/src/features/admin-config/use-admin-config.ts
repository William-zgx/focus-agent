import type {
	FocusAgentAdminConfig,
	FocusAgentUpdateAdminModelConfigRequest,
	FocusAgentUpdateAdminPolicyConfigRequest,
	FocusAgentUpdateAdminToolConfigRequest,
} from "@focus-agent/web-sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "@/shared/query/query-keys";
import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";

export type {
	FocusAgentAdminConfig,
	FocusAgentUpdateAdminModelConfigRequest,
	FocusAgentUpdateAdminPolicyConfigRequest,
	FocusAgentUpdateAdminToolConfigRequest,
} from "@focus-agent/web-sdk";

type AdminConfigClient = {
	getAdminConfig(): Promise<FocusAgentAdminConfig>;
	updateAdminModelConfig(
		request: FocusAgentUpdateAdminModelConfigRequest,
	): Promise<FocusAgentAdminConfig>;
	updateAdminToolConfig(
		request: FocusAgentUpdateAdminToolConfigRequest,
	): Promise<FocusAgentAdminConfig>;
	updateAdminPolicyConfig(
		request: FocusAgentUpdateAdminPolicyConfigRequest,
	): Promise<FocusAgentAdminConfig>;
};

export function useAdminConfig() {
	const { client, ready, isAdmin } = useFocusAgent();
	const adminConfigClient = client as unknown as AdminConfigClient;

	return useQuery<FocusAgentAdminConfig>({
		queryKey: queryKeys.adminConfig,
		queryFn: () => adminConfigClient.getAdminConfig(),
		enabled: ready && isAdmin,
	});
}

export function useUpdateAdminModelConfig() {
	const { client } = useFocusAgent();
	const queryClient = useQueryClient();
	const adminConfigClient = client as unknown as AdminConfigClient;

	return useMutation<
		FocusAgentAdminConfig,
		Error,
		FocusAgentUpdateAdminModelConfigRequest
	>({
		mutationFn: (request) => adminConfigClient.updateAdminModelConfig(request),
		onSuccess: (config) => {
			queryClient.setQueryData(queryKeys.adminConfig, config);
			void queryClient.invalidateQueries({ queryKey: queryKeys.adminConfig });
		},
	});
}

export function useUpdateAdminToolConfig() {
	const { client } = useFocusAgent();
	const queryClient = useQueryClient();
	const adminConfigClient = client as unknown as AdminConfigClient;

	return useMutation<
		FocusAgentAdminConfig,
		Error,
		FocusAgentUpdateAdminToolConfigRequest
	>({
		mutationFn: (request) => adminConfigClient.updateAdminToolConfig(request),
		onSuccess: (config) => {
			queryClient.setQueryData(queryKeys.adminConfig, config);
			void queryClient.invalidateQueries({ queryKey: queryKeys.adminConfig });
		},
	});
}

export function useUpdateAdminPolicyConfig() {
	const { client } = useFocusAgent();
	const queryClient = useQueryClient();
	const adminConfigClient = client as unknown as AdminConfigClient;

	return useMutation<
		FocusAgentAdminConfig,
		Error,
		FocusAgentUpdateAdminPolicyConfigRequest
	>({
		mutationFn: (request) => adminConfigClient.updateAdminPolicyConfig(request),
		onSuccess: (config) => {
			queryClient.setQueryData(queryKeys.adminConfig, config);
			void queryClient.invalidateQueries({ queryKey: queryKeys.adminConfig });
		},
	});
}
