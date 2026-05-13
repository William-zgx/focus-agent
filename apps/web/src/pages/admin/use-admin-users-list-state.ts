import { useMemo, useState } from "react";

import { useAdminUsers } from "@/features/admin-users/use-admin-users";

import { readAdminSearchParam, useAdminUrlSync } from "./admin-url-state";

export function useAdminUsersListState() {
	const [statusFilter, setStatusFilter] = useState(() => readAdminSearchParam("status"));
	const [roleFilter, setRoleFilter] = useState(() => readAdminSearchParam("role"));
	const [tenantFilter, setTenantFilter] = useState(() => readAdminSearchParam("tenant"));
	const [queryFilter, setQueryFilter] = useState(() => readAdminSearchParam("query"));

	const filters = useMemo(
		() => ({
			status: statusFilter || undefined,
			role: roleFilter || undefined,
			tenant_id: tenantFilter.trim() || undefined,
			query: queryFilter.trim() || undefined,
			limit: 80,
			offset: 0,
		}),
		[queryFilter, roleFilter, statusFilter, tenantFilter],
	);
	const urlFilters = useMemo(
		() => ({
			query: queryFilter,
			role: roleFilter,
			status: statusFilter,
			tenant: tenantFilter,
		}),
		[queryFilter, roleFilter, statusFilter, tenantFilter],
	);
	useAdminUrlSync(urlFilters);

	const usersQuery = useAdminUsers(filters);
	const users = usersQuery.data?.items ?? [];
	const activeCount = users.filter((user) => user.status === "active").length;
	const adminCount = users.filter((user) => user.roles.includes("admin")).length;

	return {
		activeCount,
		adminCount,
		filters,
		queryFilter,
		roleFilter,
		setQueryFilter,
		setRoleFilter,
		setStatusFilter,
		setTenantFilter,
		statusFilter,
		tenantFilter,
		users,
		usersQuery,
	};
}
