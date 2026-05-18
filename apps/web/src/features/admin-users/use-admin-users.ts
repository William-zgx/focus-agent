import type {
	FocusAgentAuditEventListRequest,
	FocusAgentAuditEventListResponse,
	FocusAgentAdminResetPasswordRequest,
	FocusAgentCreateUserRequest,
	FocusAgentRevokeUserSessionRequest,
	FocusAgentSession,
	FocusAgentSessionListResponse,
	FocusAgentUpdateUserRequest,
	FocusAgentUpdateUserRolesRequest,
	FocusAgentUpdateUserStatusRequest,
	FocusAgentUserSessionListRequest,
	FocusAgentUser,
	FocusAgentUserListRequest,
	FocusAgentUserListResponse,
} from "@focus-agent/web-sdk";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "@/shared/query/query-keys";
import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";

export function useAdminUsers(request: FocusAgentUserListRequest = {}) {
	const { client, ready, isAdmin } = useFocusAgent();
	const filtersKey = JSON.stringify(request);

	return useQuery<FocusAgentUserListResponse>({
		queryKey: queryKeys.adminUsers(filtersKey),
		queryFn: () => client.listUsers(request),
		enabled: ready && isAdmin,
	});
}

export function useAdminUser(userId: string | null) {
	const { client, ready, isAdmin } = useFocusAgent();

	return useQuery<FocusAgentUser>({
		queryKey: userId ? queryKeys.adminUser(userId) : queryKeys.adminUser(""),
		queryFn: () => {
			if (!userId) throw new Error("Missing user id.");
			return client.getUser(userId);
		},
		enabled: ready && isAdmin && Boolean(userId),
	});
}

export function useCreateAdminUser() {
	const { client } = useFocusAgent();
	const queryClient = useQueryClient();

	return useMutation<FocusAgentUser, Error, FocusAgentCreateUserRequest>({
		mutationFn: (request) => client.createUser(request),
		onSuccess: (user) => {
			void queryClient.invalidateQueries({
				queryKey: queryKeys.adminUsersRoot,
			});
			void queryClient.invalidateQueries({
				queryKey: queryKeys.adminUser(user.user_id),
			});
			void queryClient.invalidateQueries({
				queryKey: queryKeys.adminAuditEventsRoot,
			});
		},
	});
}

export function useUpdateAdminUser(userId: string | null) {
	const { client } = useFocusAgent();
	const queryClient = useQueryClient();

	return useMutation<FocusAgentUser, Error, FocusAgentUpdateUserRequest>({
		mutationFn: (request) => {
			if (!userId) throw new Error("Missing user id.");
			return client.updateUser(userId, request);
		},
		onSuccess: (user) => {
			void queryClient.invalidateQueries({
				queryKey: queryKeys.adminUsersRoot,
			});
			void queryClient.invalidateQueries({
				queryKey: queryKeys.adminUser(user.user_id),
			});
			void queryClient.invalidateQueries({
				queryKey: queryKeys.adminAuditEventsRoot,
			});
		},
	});
}

export function useUpdateAdminUserStatus(userId: string | null) {
	const { client } = useFocusAgent();
	const queryClient = useQueryClient();

	return useMutation<FocusAgentUser, Error, FocusAgentUpdateUserStatusRequest>({
		mutationFn: (request) => {
			if (!userId) throw new Error("Missing user id.");
			return client.updateUserStatus(userId, request);
		},
		onSuccess: (user) => {
			void queryClient.invalidateQueries({
				queryKey: queryKeys.adminUsersRoot,
			});
			void queryClient.invalidateQueries({
				queryKey: queryKeys.adminUser(user.user_id),
			});
			void queryClient.invalidateQueries({
				queryKey: queryKeys.adminAuditEventsRoot,
			});
		},
	});
}

export function useUpdateAdminUserRoles(userId: string | null) {
	const { client } = useFocusAgent();
	const queryClient = useQueryClient();

	return useMutation<FocusAgentUser, Error, FocusAgentUpdateUserRolesRequest>({
		mutationFn: (request) => {
			if (!userId) throw new Error("Missing user id.");
			return client.updateUserRoles(userId, request);
		},
		onSuccess: (user) => {
			void queryClient.invalidateQueries({
				queryKey: queryKeys.adminUsersRoot,
			});
			void queryClient.invalidateQueries({
				queryKey: queryKeys.adminUser(user.user_id),
			});
			void queryClient.invalidateQueries({
				queryKey: queryKeys.adminAuditEventsRoot,
			});
		},
	});
}

export function useAdminUserSessions(
	userId: string | null,
	request: FocusAgentUserSessionListRequest = {},
) {
	const { client, ready, isAdmin } = useFocusAgent();
	const filtersKey = JSON.stringify(request);

	return useQuery<FocusAgentSessionListResponse>({
		queryKey: userId
			? [...queryKeys.adminUserSessions(userId), filtersKey]
			: queryKeys.adminUserSessions(""),
		queryFn: () => {
			if (!userId) throw new Error("Missing user id.");
			return client.listUserSessions(userId, request);
		},
		enabled: ready && isAdmin && Boolean(userId),
	});
}

export function useRevokeAdminUserSession(userId: string | null) {
	const { client } = useFocusAgent();
	const queryClient = useQueryClient();

	return useMutation<
		FocusAgentSession,
		Error,
		FocusAgentRevokeUserSessionRequest
	>({
		mutationFn: (request) => {
			if (!userId) throw new Error("Missing user id.");
			return client.revokeUserSession(userId, request);
		},
		onSuccess: () => {
			void queryClient.invalidateQueries({
				queryKey: userId
					? queryKeys.adminUserSessions(userId)
					: queryKeys.adminUsersRoot,
			});
			void queryClient.invalidateQueries({
				queryKey: queryKeys.adminAuditEventsRoot,
			});
		},
	});
}

export function useResetAdminUserPassword(userId: string | null) {
	const { client } = useFocusAgent();
	const queryClient = useQueryClient();

	return useMutation<
		FocusAgentUser,
		Error,
		FocusAgentAdminResetPasswordRequest
	>({
		mutationFn: (request) => {
			if (!userId) throw new Error("Missing user id.");
			return client.resetUserPassword(userId, request);
		},
		onSuccess: (user) => {
			void queryClient.invalidateQueries({
				queryKey: queryKeys.adminUser(user.user_id),
			});
			void queryClient.invalidateQueries({
				queryKey: userId
					? queryKeys.adminUserSessions(userId)
					: queryKeys.adminUsersRoot,
			});
			void queryClient.invalidateQueries({
				queryKey: queryKeys.adminAuditEventsRoot,
			});
		},
	});
}

export function useAdminAuditEvents(
	request: FocusAgentAuditEventListRequest = {},
) {
	const { client, ready, isAdmin } = useFocusAgent();
	const filtersKey = JSON.stringify(request);

	return useQuery<FocusAgentAuditEventListResponse>({
		queryKey: queryKeys.adminAuditEvents(filtersKey),
		queryFn: () => client.listAuditEvents(request),
		enabled: ready && isAdmin,
	});
}
