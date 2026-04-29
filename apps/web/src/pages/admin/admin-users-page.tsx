import type { FocusAgentCreateUserRequest, FocusAgentUser } from "@focus-agent/web-sdk";
import { Link, useNavigate } from "@tanstack/react-router";
import { type FormEvent, useMemo, useState } from "react";

import { useShellUi } from "@/app/shell/shell-ui-context";
import {
  ADMIN_ROLE_OPTIONS,
  ADMIN_USER_STATUSES,
  formatAdminDate,
  formatUserLabel,
  parseMetadataDraft,
  splitRoleDraft,
  statusTone,
} from "@/features/admin-users/admin-user-utils";
import { useAdminUsers, useCreateAdminUser } from "@/features/admin-users/use-admin-users";

import {
  AdminAccessGate,
  AdminErrorMessage,
  AdminPageHeading,
} from "./admin-page-chrome";

function userStatusClass(user: FocusAgentUser) {
  return `fa-observability-pill is-${statusTone(user.status)}`;
}

export function AdminUsersPage() {
  const navigate = useNavigate();
  const { isChineseUi } = useShellUi();
  const locale = isChineseUi ? "zh-CN" : "en-US";
  const [statusFilter, setStatusFilter] = useState("");
  const [roleFilter, setRoleFilter] = useState("");
  const [tenantFilter, setTenantFilter] = useState("");
  const [queryFilter, setQueryFilter] = useState("");
  const [newUserId, setNewUserId] = useState("");
  const [newDisplayName, setNewDisplayName] = useState("");
  const [newEmail, setNewEmail] = useState("");
  const [newTenantId, setNewTenantId] = useState("");
  const [newRoles, setNewRoles] = useState("member");
  const [newMetadata, setNewMetadata] = useState("{}");
  const [formError, setFormError] = useState<string | null>(null);
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
  const createUser = useCreateAdminUser();
  const users = usersQuery.data?.items ?? [];
  const activeCount = users.filter((user) => user.status === "active").length;
  const adminCount = users.filter((user) => user.roles.includes("admin")).length;

  async function handleCreateUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);
    const parsed = parseMetadataDraft(newMetadata);
    if (parsed.error || !parsed.metadata) {
      setFormError(parsed.error ?? "Metadata JSON is invalid.");
      return;
    }
    const request: FocusAgentCreateUserRequest = {
      user_id: newUserId.trim(),
      display_name: newDisplayName.trim() || undefined,
      email: newEmail.trim() || undefined,
      tenant_id: newTenantId.trim() || undefined,
      status: "active",
      roles: splitRoleDraft(newRoles),
      metadata: parsed.metadata,
    };
    try {
      const user = await createUser.mutateAsync(request);
      setNewUserId("");
      setNewDisplayName("");
      setNewEmail("");
      setNewTenantId("");
      setNewRoles("member");
      setNewMetadata("{}");
      await navigate({
        to: "/admin/users/$userId",
        params: { userId: user.user_id },
      });
    } catch (error: unknown) {
      setFormError(error instanceof Error ? error.message : "Failed to create user.");
    }
  }

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
            <div className="fa-observability-panel-header">
              <div>
                <strong>{isChineseUi ? "Directory" : "Directory"}</strong>
                <h2>{isChineseUi ? "用户列表" : "Users"}</h2>
              </div>
              <span>{usersQuery.isLoading ? "loading" : `${users.length} rows`}</span>
            </div>
            <div className="fa-observability-filters fa-admin-filters">
              <label className="fa-observability-filter">
                <span>{isChineseUi ? "状态" : "Status"}</span>
                <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
                  <option value="">{isChineseUi ? "全部状态" : "All statuses"}</option>
                  {ADMIN_USER_STATUSES.map((status) => (
                    <option key={status} value={status}>{status}</option>
                  ))}
                </select>
              </label>
              <label className="fa-observability-filter">
                <span>{isChineseUi ? "角色" : "Role"}</span>
                <select value={roleFilter} onChange={(event) => setRoleFilter(event.target.value)}>
                  <option value="">{isChineseUi ? "全部角色" : "All roles"}</option>
                  {ADMIN_ROLE_OPTIONS.map((role) => (
                    <option key={role} value={role}>{role}</option>
                  ))}
                </select>
              </label>
              <label className="fa-observability-filter">
                <span>{isChineseUi ? "租户" : "Tenant"}</span>
                <input value={tenantFilter} onChange={(event) => setTenantFilter(event.target.value)} />
              </label>
              <label className="fa-observability-filter">
                <span>{isChineseUi ? "搜索" : "Search"}</span>
                <input value={queryFilter} onChange={(event) => setQueryFilter(event.target.value)} />
              </label>
            </div>
            {usersQuery.error ? (
              <AdminErrorMessage error={usersQuery.error} fallback="Failed to load users." />
            ) : null}
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
                    <tr key={user.user_id}>
                      <td>
                        <div className="fa-admin-identity-cell">
                          <strong>{formatUserLabel(user)}</strong>
                          <span>{user.email || user.user_id}</span>
                        </div>
                      </td>
                      <td>{user.tenant_id || "-"}</td>
                      <td><span className={userStatusClass(user)}>{user.status}</span></td>
                      <td>
                        <div className="fa-admin-chip-row">
                          {user.roles.map((role) => <span key={role}>{role}</span>)}
                        </div>
                      </td>
                      <td>{formatAdminDate(user.updated_at ?? user.created_at, locale)}</td>
                      <td>
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
                  {!users.length && !usersQuery.isLoading ? (
                    <tr>
                      <td colSpan={6}>
                        <div className="fa-observability-empty is-compact">
                          {isChineseUi ? "没有匹配的用户。" : "No users match these filters."}
                        </div>
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </div>

          <form className="fa-admin-panel fa-admin-create-panel" onSubmit={handleCreateUser}>
            <div className="fa-observability-panel-header">
              <div>
                <strong>{isChineseUi ? "Create" : "Create"}</strong>
                <h2>{isChineseUi ? "新增用户" : "New User"}</h2>
              </div>
              <span>{createUser.isPending ? "saving" : "active"}</span>
            </div>
            <label className="fa-observability-filter">
              <span>User ID</span>
              <input
                value={newUserId}
                onChange={(event) => setNewUserId(event.target.value)}
                required
              />
            </label>
            <label className="fa-observability-filter">
              <span>{isChineseUi ? "显示名" : "Display name"}</span>
              <input value={newDisplayName} onChange={(event) => setNewDisplayName(event.target.value)} />
            </label>
            <label className="fa-observability-filter">
              <span>Email</span>
              <input value={newEmail} onChange={(event) => setNewEmail(event.target.value)} type="email" />
            </label>
            <label className="fa-observability-filter">
              <span>{isChineseUi ? "租户" : "Tenant"}</span>
              <input value={newTenantId} onChange={(event) => setNewTenantId(event.target.value)} />
            </label>
            <label className="fa-observability-filter">
              <span>{isChineseUi ? "角色" : "Roles"}</span>
              <input value={newRoles} onChange={(event) => setNewRoles(event.target.value)} />
            </label>
            <label className="fa-observability-filter">
              <span>Metadata JSON</span>
              <textarea
                value={newMetadata}
                onChange={(event) => setNewMetadata(event.target.value)}
                rows={6}
                spellCheck={false}
              />
            </label>
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
