import { useNavigate } from "@tanstack/react-router";

import { useShellUi } from "@/app/shell/shell-ui-context";
import {
  ADMIN_ROLE_OPTIONS,
  ADMIN_USER_STATUSES,
} from "@/features/admin-users/admin-user-utils";

import {
  AdminAccessGate,
  AdminErrorMessage,
  AdminPageHeading,
} from "./admin-page-chrome";
import {
  AdminField,
  AdminFiltersRow,
  AdminPanelHeader,
} from "./admin-page-sections";
import { AdminUsersTable } from "./admin-user-table";
import { useAdminUserCreateForm } from "./use-admin-user-create-form";
import { useAdminUsersListState } from "./use-admin-users-list-state";

export function AdminUsersPage() {
  const navigate = useNavigate();
  const { isChineseUi } = useShellUi();
  const locale = isChineseUi ? "zh-CN" : "en-US";
  const {
    activeCount,
    adminCount,
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
  } = useAdminUsersListState();
  const {
    createUser,
    formError,
    handleCreateUser,
    newDisplayName,
    newEmail,
    newMetadata,
    newRoles,
    newTenantId,
    newUserId,
    setNewDisplayName,
    setNewEmail,
    setNewMetadata,
    setNewRoles,
    setNewTenantId,
    setNewUserId,
  } = useAdminUserCreateForm({
    onCreated: async (user) => {
      await navigate({
        to: "/admin/users/$userId",
        params: { userId: user.user_id },
      });
    },
  });

  return (
    <AdminAccessGate>
      <div className="fa-admin-layout">
        <AdminPageHeading
          active="users"
          title={isChineseUi ? "用户管理" : "User Management"}
          summary={
            isChineseUi
              ? "管理持久化用户、租户、启用状态和业务角色。"
              : "Manage persistent users, tenants, account status, and business roles."
          }
          side={
            <div className="fa-admin-stat-stack">
              <div className="fa-trajectory-overview-runtime">
                <span>{isChineseUi ? "列表总数" : "Listed users"}</span>
                <strong>{usersQuery.data?.count ?? users.length}</strong>
              </div>
              <div className="fa-admin-mini-stats">
                <span>{activeCount} active</span>
                <span>{adminCount} admin</span>
              </div>
            </div>
          }
        />

        <section className="fa-admin-grid">
          <div className="fa-admin-panel fa-admin-users-panel">
            <AdminPanelHeader
              eyebrow={isChineseUi ? "Directory" : "Directory"}
              status={usersQuery.isLoading ? "loading" : `${users.length} rows`}
              title={isChineseUi ? "用户列表" : "Users"}
            />
            <AdminFiltersRow>
              <AdminField label={isChineseUi ? "状态" : "Status"}>
                <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
                  <option value="">{isChineseUi ? "全部状态" : "All statuses"}</option>
                  {ADMIN_USER_STATUSES.map((status) => (
                    <option key={status} value={status}>{status}</option>
                  ))}
                </select>
              </AdminField>
              <AdminField label={isChineseUi ? "角色" : "Role"}>
                <select value={roleFilter} onChange={(event) => setRoleFilter(event.target.value)}>
                  <option value="">{isChineseUi ? "全部角色" : "All roles"}</option>
                  {ADMIN_ROLE_OPTIONS.map((role) => (
                    <option key={role} value={role}>{role}</option>
                  ))}
                </select>
              </AdminField>
              <AdminField label={isChineseUi ? "租户" : "Tenant"}>
                <input value={tenantFilter} onChange={(event) => setTenantFilter(event.target.value)} />
              </AdminField>
              <AdminField label={isChineseUi ? "搜索" : "Search"}>
                <input value={queryFilter} onChange={(event) => setQueryFilter(event.target.value)} />
              </AdminField>
            </AdminFiltersRow>
            {usersQuery.error ? (
              <AdminErrorMessage error={usersQuery.error} fallback="Failed to load users." />
            ) : null}
            <AdminUsersTable
              isChineseUi={isChineseUi}
              isLoading={usersQuery.isLoading}
              locale={locale}
              users={users}
            />
          </div>

          <form className="fa-admin-panel fa-admin-create-panel" onSubmit={handleCreateUser}>
            <AdminPanelHeader
              eyebrow={isChineseUi ? "Create" : "Create"}
              status={createUser.isPending ? "saving" : "active"}
              title={isChineseUi ? "新增用户" : "New User"}
            />
            <AdminField label="User ID">
              <input
                value={newUserId}
                onChange={(event) => setNewUserId(event.target.value)}
                required
              />
            </AdminField>
            <AdminField label={isChineseUi ? "显示名" : "Display name"}>
              <input value={newDisplayName} onChange={(event) => setNewDisplayName(event.target.value)} />
            </AdminField>
            <AdminField label="Email">
              <input value={newEmail} onChange={(event) => setNewEmail(event.target.value)} type="email" />
            </AdminField>
            <AdminField label={isChineseUi ? "租户" : "Tenant"}>
              <input value={newTenantId} onChange={(event) => setNewTenantId(event.target.value)} />
            </AdminField>
            <AdminField label={isChineseUi ? "角色" : "Roles"}>
              <input value={newRoles} onChange={(event) => setNewRoles(event.target.value)} />
            </AdminField>
            <AdminField label="Metadata JSON">
              <textarea
                value={newMetadata}
                onChange={(event) => setNewMetadata(event.target.value)}
                rows={6}
                spellCheck={false}
              />
            </AdminField>
            {formError ? <div className="fa-inline-notice is-danger">{formError}</div> : null}
            <div className="fa-observability-command-bar">
              <button
                className="fa-observability-preset is-primary"
                disabled={createUser.isPending || !newUserId.trim()}
                type="submit"
              >
                {createUser.isPending
                  ? isChineseUi ? "创建中..." : "Creating..."
                  : isChineseUi ? "创建用户" : "Create User"}
              </button>
            </div>
          </form>
        </section>
      </div>
    </AdminAccessGate>
  );
}
