import { useMemo, useState } from "react";

import { useAdminUsers } from "@/features/admin-users/use-admin-users";

export function useAdminUsersListState() {
	const [statusFilter, setStatusFilter] = useState("");
	const [roleFilter, setRoleFilter] = useState("");
	const [tenantFilter, setTenantFilter] = useState("");
	const [queryFilter, setQueryFilter] = useState("");

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
