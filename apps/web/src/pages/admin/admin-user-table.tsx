import { Link } from "@tanstack/react-router";
import type { FocusAgentUser } from "@focus-agent/web-sdk";

import {
	formatAdminDate,
	formatUserLabel,
	statusTone,
} from "@/features/admin-users/admin-user-utils";

function userStatusClass(user: FocusAgentUser) {
	return `fa-observability-pill is-${statusTone(user.status)}`;
}

type AdminUsersTableProps = {
	isChineseUi: boolean;
	isLoading: boolean;
	locale: string;
	selectedUserId?: string | null;
	users: FocusAgentUser[];
};

export function AdminUsersTable({
	isChineseUi,
	isLoading,
	locale,
	selectedUserId,
	users,
}: AdminUsersTableProps) {
	return (
		<div className="fa-admin-table-scroll">
			<table className="fa-admin-table">
				<thead>
					<tr>
						<th>{isChineseUi ? "用户" : "User"}</th>
						<th>{isChineseUi ? "租户" : "Tenant"}</th>
						<th>{isChineseUi ? "状态" : "Status"}</th>
						<th>{isChineseUi ? "角色" : "Roles"}</th>
						<th>{isChineseUi ? "最近更新" : "Updated"}</th>
						<th>{isChineseUi ? "操作" : "Actions"}</th>
					</tr>
				</thead>
				<tbody>
					{users.map((user) => (
						<tr
							className={
								selectedUserId === user.user_id ? "is-selected" : undefined
							}
							key={user.user_id}
						>
							<td data-label={isChineseUi ? "用户" : "User"}>
								<div className="fa-admin-identity-cell">
									<strong>{formatUserLabel(user)}</strong>
									<span>{user.email || user.user_id}</span>
								</div>
							</td>
							<td data-label={isChineseUi ? "租户" : "Tenant"}>
								{user.tenant_id || "-"}
							</td>
							<td data-label={isChineseUi ? "状态" : "Status"}>
								<span className={userStatusClass(user)}>{user.status}</span>
							</td>
							<td data-label={isChineseUi ? "角色" : "Roles"}>
								<div className="fa-admin-chip-row">
									{user.roles.map((role) => (
										<span key={role}>{role}</span>
									))}
								</div>
							</td>
							<td data-label={isChineseUi ? "最近更新" : "Updated"}>
								{formatAdminDate(user.updated_at ?? user.created_at, locale)}
							</td>
							<td data-label={isChineseUi ? "操作" : "Actions"}>
								<Link
									className="fa-admin-row-link"
									params={{ userId: user.user_id }}
									to="/admin/users/$userId"
								>
									{isChineseUi ? "管理" : "Manage"}
								</Link>
							</td>
						</tr>
					))}
					{!users.length && !isLoading ? (
						<tr>
							<td colSpan={6}>
								<div className="fa-observability-empty is-compact">
									{isChineseUi
										? "没有匹配的用户。"
										: "No users match these filters."}
								</div>
							</td>
						</tr>
					) : null}
				</tbody>
			</table>
		</div>
	);
}
