import { Link, useNavigate } from "@tanstack/react-router";
import type { FormEvent } from "react";
import { useState } from "react";

import { useShellUi } from "@/app/shell/shell-ui-context";
import {
  ADMIN_ROLE_OPTIONS,
  ADMIN_USER_STATUSES,
} from "@/features/admin-users/admin-user-utils";

import {
  AdminConsoleLayout,
  AdminErrorMessage,
} from "./admin-page-chrome";
import {
  AdminField,
  AdminFiltersRow,
  AdminPanelHeader,
} from "./admin-page-sections";
import { AdminUserDetailDrawer } from "./admin-user-detail-drawer";
import { AdminUsersTable } from "./admin-user-table";
import { useAdminUserCreateForm } from "./use-admin-user-create-form";
import { useAdminUsersListState } from "./use-admin-users-list-state";

type AdminUsersPageProps = {
  selectedUserId?: string | null;
};

export function AdminUsersPage({ selectedUserId }: AdminUsersPageProps = {}) {
  const navigate = useNavigate();
  const { isChineseUi } = useShellUi();
  const locale = isChineseUi ? "zh-CN" : "en-US";
  const [createDrawerOpen, setCreateDrawerOpen] = useState(false);
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
      setCreateDrawerOpen(false);
      await navigate({
        to: "/admin/users/$userId",
        params: { userId: user.user_id },
        search: currentSearchObject(),
      });
    },
  });
  const listedCount = usersQuery.data?.count ?? users.length;
  const drawer = selectedUserId ? (
    <AdminUserDetailDrawer
      isChineseUi={isChineseUi}
      userId={selectedUserId}
      onClose={() => {
        void navigate({ to: "/admin/users", search: currentSearchObject() });
      }}
    />
  ) : createDrawerOpen ? (
    <CreateUserDrawer
      createPending={createUser.isPending}
      formError={formError}
      isChineseUi={isChineseUi}
      newDisplayName={newDisplayName}
      newEmail={newEmail}
      newMetadata={newMetadata}
      newRoles={newRoles}
      newTenantId={newTenantId}
      newUserId={newUserId}
      onClose={() => setCreateDrawerOpen(false)}
      onCreateUser={handleCreateUser}
      onDisplayNameChange={setNewDisplayName}
      onEmailChange={setNewEmail}
      onMetadataChange={setNewMetadata}
      onRolesChange={setNewRoles}
      onTenantIdChange={setNewTenantId}
      onUserIdChange={setNewUserId}
    />
  ) : null;

  return (
    <AdminConsoleLayout
      active="users"
      title={isChineseUi ? "用户目录" : "User Directory"}
      summary={
        isChineseUi
          ? "查找账号、进入详情抽屉处理资料、权限、安全和审计。"
          : "Find accounts and manage profile, access, security, and audit details from the drawer."
      }
      drawer={drawer}
      drawerLabel={selectedUserId ? (isChineseUi ? "用户详情" : "User detail") : isChineseUi ? "创建用户" : "Create user"}
    >
      <section className="fa-admin-panel fa-admin-primary-panel fa-admin-users-panel">
        <AdminPanelHeader
          eyebrow={isChineseUi ? "Directory" : "Directory"}
          status={
            <div className="fa-admin-panel-status-actions">
              <span>
                {usersQuery.isLoading
                  ? "loading"
                  : `${listedCount} users · ${activeCount} active · ${adminCount} admin`}
              </span>
              <button
                className="fa-observability-preset is-primary"
                type="button"
                onClick={() => setCreateDrawerOpen(true)}
              >
                {isChineseUi ? "创建用户" : "Create user"}
              </button>
              <Link className="fa-observability-preset" to="/admin/audit-events">
                {isChineseUi ? "查看审计" : "View audit"}
              </Link>
            </div>
          }
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
          selectedUserId={selectedUserId}
          users={users}
        />
      </section>
    </AdminConsoleLayout>
  );
}

function CreateUserDrawer({
  createPending,
  formError,
  isChineseUi,
  newDisplayName,
  newEmail,
  newMetadata,
  newRoles,
  newTenantId,
  newUserId,
  onClose,
  onCreateUser,
  onDisplayNameChange,
  onEmailChange,
  onMetadataChange,
  onRolesChange,
  onTenantIdChange,
  onUserIdChange,
}: {
  createPending: boolean;
  formError: string | null;
  isChineseUi: boolean;
  newDisplayName: string;
  newEmail: string;
  newMetadata: string;
  newRoles: string;
  newTenantId: string;
  newUserId: string;
  onClose: () => void;
  onCreateUser: (event: FormEvent<HTMLFormElement>) => void;
  onDisplayNameChange: (value: string) => void;
  onEmailChange: (value: string) => void;
  onMetadataChange: (value: string) => void;
  onRolesChange: (value: string) => void;
  onTenantIdChange: (value: string) => void;
  onUserIdChange: (value: string) => void;
}) {
  return (
    <form className="fa-admin-drawer-shell" onSubmit={onCreateUser}>
      <header className="fa-admin-drawer-header">
        <div>
          <span>{isChineseUi ? "创建用户" : "Create user"}</span>
          <h2>{isChineseUi ? "新增账号" : "New account"}</h2>
          <p>{isChineseUi ? "创建成功后自动进入用户详情继续配置权限。" : "After creation, continue configuration in the user detail drawer."}</p>
        </div>
        <button className="fa-admin-icon-button" type="button" onClick={onClose} aria-label={isChineseUi ? "关闭创建用户" : "Close create user"}>
          x
        </button>
      </header>

      <div className="fa-admin-drawer-body">
        <section className="fa-admin-panel">
          <AdminPanelHeader
            eyebrow={isChineseUi ? "Create" : "Create"}
            status={createPending ? "saving" : "active"}
            title={isChineseUi ? "账号资料" : "Account profile"}
          />
          <AdminField label="User ID">
            <input
              value={newUserId}
              onChange={(event) => onUserIdChange(event.target.value)}
              required
            />
          </AdminField>
          <AdminField label={isChineseUi ? "显示名" : "Display name"}>
            <input value={newDisplayName} onChange={(event) => onDisplayNameChange(event.target.value)} />
          </AdminField>
          <AdminField label="Email">
            <input value={newEmail} onChange={(event) => onEmailChange(event.target.value)} type="email" />
          </AdminField>
          <AdminField label={isChineseUi ? "租户" : "Tenant"}>
            <input value={newTenantId} onChange={(event) => onTenantIdChange(event.target.value)} />
          </AdminField>
          <AdminField label={isChineseUi ? "角色" : "Roles"}>
            <input value={newRoles} onChange={(event) => onRolesChange(event.target.value)} />
          </AdminField>
          <AdminField label="Metadata JSON">
            <textarea
              value={newMetadata}
              onChange={(event) => onMetadataChange(event.target.value)}
              rows={6}
              spellCheck={false}
            />
          </AdminField>
          {formError ? <div className="fa-inline-notice is-danger">{formError}</div> : null}
          <div className="fa-observability-command-bar">
            <button
              className="fa-observability-preset is-primary"
              disabled={createPending || !newUserId.trim()}
              type="submit"
            >
              {createPending
                ? isChineseUi ? "创建中..." : "Creating..."
                : isChineseUi ? "创建用户" : "Create User"}
            </button>
          </div>
        </section>
      </div>
    </form>
  );
}

function currentSearchObject(): Record<string, string> {
  if (typeof window === "undefined") return {};
  return Object.fromEntries(new URLSearchParams(window.location.search).entries());
}
