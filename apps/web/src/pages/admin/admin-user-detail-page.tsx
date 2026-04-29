import { Link, useRouterState } from "@tanstack/react-router";
import { type FormEvent, useEffect, useMemo, useState } from "react";

import { useShellUi } from "@/app/shell/shell-ui-context";
import {
  ADMIN_USER_STATUSES,
  formatAdminDate,
  formatUserLabel,
  metadataToDraft,
  parseMetadataDraft,
  splitRoleDraft,
  statusTone,
} from "@/features/admin-users/admin-user-utils";
import {
  useAdminAuditEvents,
  useAdminUser,
  useAdminUserSessions,
  useResetAdminUserPassword,
  useRevokeAdminUserSession,
  useUpdateAdminUser,
  useUpdateAdminUserRoles,
  useUpdateAdminUserStatus,
} from "@/features/admin-users/use-admin-users";

import {
  AdminAccessGate,
  AdminErrorMessage,
  AdminPageHeading,
} from "./admin-page-chrome";

export function AdminUserDetailPage() {
  const { isChineseUi } = useShellUi();
  const locale = isChineseUi ? "zh-CN" : "en-US";
  const userId = useRouterState({
    select: (state) => {
      const params = state.matches.at(-1)?.params as Partial<Record<"userId", string>> | undefined;
      return params?.userId ?? "";
    },
  });
  const userQuery = useAdminUser(userId || null);
  const user = userQuery.data ?? null;
  const updateUser = useUpdateAdminUser(userId || null);
  const updateRoles = useUpdateAdminUserRoles(userId || null);
  const updateStatus = useUpdateAdminUserStatus(userId || null);
  const sessionsQuery = useAdminUserSessions(userId || null);
  const revokeSession = useRevokeAdminUserSession(userId || null);
  const resetPassword = useResetAdminUserPassword(userId || null);
  const auditQuery = useAdminAuditEvents({
    resource_type: "user",
    resource_id: userId || undefined,
    limit: 20,
    offset: 0,
  });
  const [displayName, setDisplayName] = useState("");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [tenantId, setTenantId] = useState("");
  const [metadataDraft, setMetadataDraft] = useState("{}");
  const [roleDraft, setRoleDraft] = useState("");
  const [statusDraft, setStatusDraft] = useState("active");
  const [reasonDraft, setReasonDraft] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const busy = updateUser.isPending || updateRoles.isPending || updateStatus.isPending || resetPassword.isPending || revokeSession.isPending;
  const auditItems = auditQuery.data?.items ?? [];
  const sessionItems = sessionsQuery.data?.items ?? [];
  const roleChips = useMemo(() => splitRoleDraft(roleDraft), [roleDraft]);

  useEffect(() => {
    if (!user) return;
    setUsername(user.username ?? "");
    setDisplayName(user.display_name ?? "");
    setEmail(user.email ?? "");
    setTenantId(user.tenant_id ?? "");
    setMetadataDraft(metadataToDraft(user.metadata));
    setRoleDraft(user.roles.join(", "));
    setStatusDraft(user.status);
  }, [user]);

  async function handleSaveProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage(null);
    const parsed = parseMetadataDraft(metadataDraft);
    if (parsed.error || !parsed.metadata) {
      setMessage(parsed.error ?? "Metadata JSON is invalid.");
      return;
    }
    try {
      await updateUser.mutateAsync({
        username: username.trim() || null,
        display_name: displayName.trim() || null,
        email: email.trim() || null,
        tenant_id: tenantId.trim() || null,
        metadata: parsed.metadata,
      });
      setMessage(isChineseUi ? "资料已保存。" : "Profile saved.");
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : "Failed to save user.");
    }
  }

  async function handleSaveRoles() {
    setMessage(null);
    if (!reasonDraft.trim()) {
      setMessage(isChineseUi ? "请填写审计原因。" : "Audit reason is required.");
      return;
    }
    try {
      await updateRoles.mutateAsync({
        roles: roleChips,
        reason: reasonDraft.trim() || null,
      });
      setMessage(isChineseUi ? "角色已更新。" : "Roles updated.");
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : "Failed to update roles.");
    }
  }

  async function handleSaveStatus() {
    setMessage(null);
    if (!reasonDraft.trim()) {
      setMessage(isChineseUi ? "请填写审计原因。" : "Audit reason is required.");
      return;
    }
    try {
      await updateStatus.mutateAsync({
        status: statusDraft,
        reason: reasonDraft.trim() || null,
      });
      setMessage(isChineseUi ? "状态已更新。" : "Status updated.");
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : "Failed to update status.");
    }
  }

  async function handleResetPassword() {
    setMessage(null);
    if (!newPassword.trim() || !reasonDraft.trim()) {
      setMessage(isChineseUi ? "请填写新密码和审计原因。" : "New password and audit reason are required.");
      return;
    }
    try {
      await resetPassword.mutateAsync({
        new_password: newPassword,
        reason: reasonDraft.trim(),
      });
      setNewPassword("");
      setMessage(isChineseUi ? "密码已重置。" : "Password reset.");
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : "Failed to reset password.");
    }
  }

  async function handleRevokeSession(sessionId: string) {
    setMessage(null);
    if (!reasonDraft.trim()) {
      setMessage(isChineseUi ? "请填写审计原因。" : "Audit reason is required.");
      return;
    }
    try {
      await revokeSession.mutateAsync({
        session_id: sessionId,
        reason: reasonDraft.trim(),
      });
      setMessage(isChineseUi ? "会话已撤销。" : "Session revoked.");
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : "Failed to revoke session.");
    }
  }

  return (
    <AdminAccessGate>
      <div className="fa-admin-layout">
        <AdminPageHeading
          active="users"
          title={user ? formatUserLabel(user) : isChineseUi ? "用户详情" : "User Detail"}
          summary={
            isChineseUi
              ? "编辑基础资料、账号状态、角色并查看此用户相关的审计事件。"
              : "Edit profile fields, account status, roles, and inspect related audit events."
          }
          side={
            <div className="fa-admin-stat-stack">
              <Link className="fa-admin-row-link" to="/admin/users">
                {isChineseUi ? "返回用户列表" : "Back to users"}
              </Link>
              {user ? (
                <span className={`fa-observability-pill is-${statusTone(user.status)}`}>
                  {user.status}
                </span>
              ) : null}
            </div>
          }
        />

        {userQuery.error ? (
          <AdminErrorMessage error={userQuery.error} fallback="Failed to load user." />
        ) : null}

        <section className="fa-admin-detail-grid">
          <form className="fa-admin-panel" onSubmit={handleSaveProfile}>
            <div className="fa-observability-panel-header">
              <div>
                <strong>{isChineseUi ? "Profile" : "Profile"}</strong>
                <h2>{isChineseUi ? "基础资料" : "Profile"}</h2>
              </div>
              <span>{userQuery.isLoading ? "loading" : userId}</span>
            </div>
            <div className="fa-admin-summary-grid">
              <div>
                <span>User ID</span>
                <strong>{user?.user_id ?? "-"}</strong>
              </div>
              <div>
                <span>{isChineseUi ? "创建" : "Created"}</span>
                <strong>{formatAdminDate(user?.created_at, locale)}</strong>
              </div>
              <div>
                <span>{isChineseUi ? "最近登录" : "Last seen"}</span>
                <strong>{formatAdminDate(user?.last_seen_at, locale)}</strong>
              </div>
            </div>
            <label className="fa-observability-filter">
              <span>{isChineseUi ? "用户名" : "Username"}</span>
              <input value={username} onChange={(event) => setUsername(event.target.value)} />
            </label>
            <label className="fa-observability-filter">
              <span>{isChineseUi ? "显示名" : "Display name"}</span>
              <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
            </label>
            <label className="fa-observability-filter">
              <span>Email</span>
              <input value={email} onChange={(event) => setEmail(event.target.value)} type="email" />
            </label>
            <label className="fa-observability-filter">
              <span>{isChineseUi ? "租户" : "Tenant"}</span>
              <input value={tenantId} onChange={(event) => setTenantId(event.target.value)} />
            </label>
            <label className="fa-observability-filter">
              <span>Metadata JSON</span>
              <textarea
                value={metadataDraft}
                onChange={(event) => setMetadataDraft(event.target.value)}
                rows={8}
                spellCheck={false}
              />
            </label>
            <div className="fa-observability-command-bar">
              <button className="fa-observability-preset is-primary" disabled={busy} type="submit">
                {updateUser.isPending
                  ? isChineseUi ? "保存中..." : "Saving..."
                  : isChineseUi ? "保存资料" : "Save Profile"}
              </button>
            </div>
          </form>

          <div className="fa-admin-panel">
            <div className="fa-observability-panel-header">
              <div>
                <strong>{isChineseUi ? "Access" : "Access"}</strong>
                <h2>{isChineseUi ? "状态与角色" : "Status And Roles"}</h2>
              </div>
              <span>{roleChips.length} roles</span>
            </div>
            <label className="fa-observability-filter">
              <span>{isChineseUi ? "状态" : "Status"}</span>
              <select value={statusDraft} onChange={(event) => setStatusDraft(event.target.value)}>
                {ADMIN_USER_STATUSES.map((status) => (
                  <option key={status} value={status}>{status}</option>
                ))}
              </select>
            </label>
            <label className="fa-observability-filter">
              <span>{isChineseUi ? "角色" : "Roles"}</span>
              <input value={roleDraft} onChange={(event) => setRoleDraft(event.target.value)} />
            </label>
            <div className="fa-admin-chip-row">
              {roleChips.map((role) => <span key={role}>{role}</span>)}
            </div>
            <label className="fa-observability-filter">
              <span>{isChineseUi ? "审计原因" : "Audit reason"}</span>
              <textarea
                value={reasonDraft}
                onChange={(event) => setReasonDraft(event.target.value)}
                rows={4}
              />
            </label>
            {message ? (
              <div className={`fa-inline-notice ${message.includes("Failed") || message.includes("invalid") ? "is-danger" : "is-success"}`}>
                {message}
              </div>
            ) : null}
            <div className="fa-admin-action-row">
              <button
                className="fa-observability-preset is-primary"
                disabled={busy}
                onClick={() => void handleSaveStatus()}
                type="button"
              >
                {updateStatus.isPending
                  ? isChineseUi ? "更新中..." : "Updating..."
                  : isChineseUi ? "更新状态" : "Update Status"}
              </button>
              <button
                className="fa-observability-preset"
                disabled={busy}
                onClick={() => void handleSaveRoles()}
                type="button"
              >
                {updateRoles.isPending
                  ? isChineseUi ? "保存中..." : "Saving..."
                  : isChineseUi ? "保存角色" : "Save Roles"}
              </button>
            </div>
          </div>

          <div className="fa-admin-panel">
            <div className="fa-observability-panel-header">
              <div>
                <strong>{isChineseUi ? "Security" : "Security"}</strong>
                <h2>{isChineseUi ? "密码与会话" : "Password And Sessions"}</h2>
              </div>
              <span>{sessionItems.length} sessions</span>
            </div>
            <label className="fa-observability-filter">
              <span>{isChineseUi ? "新密码" : "New password"}</span>
              <input
                autoComplete="new-password"
                onChange={(event) => setNewPassword(event.target.value)}
                type="password"
                value={newPassword}
              />
            </label>
            <div className="fa-observability-command-bar">
              <button
                className="fa-observability-preset is-primary"
                disabled={busy}
                onClick={() => void handleResetPassword()}
                type="button"
              >
                {resetPassword.isPending
                  ? isChineseUi ? "重置中..." : "Resetting..."
                  : isChineseUi ? "重置密码" : "Reset Password"}
              </button>
            </div>
            {sessionsQuery.error ? (
              <AdminErrorMessage error={sessionsQuery.error} fallback="Failed to load sessions." />
            ) : null}
            <div className="fa-admin-event-list">
              {sessionItems.map((session) => (
                <div className="fa-admin-event-row" key={session.session_id}>
                  <div>
                    <strong>{session.current ? isChineseUi ? "当前会话" : "Current session" : session.session_id.slice(0, 12)}</strong>
                    <span>{formatAdminDate(session.last_seen_at ?? session.created_at, locale)}</span>
                  </div>
                  <span className={`fa-observability-pill is-${session.revoked_at ? "danger" : "success"}`}>
                    {session.revoked_at ? "revoked" : "active"}
                  </span>
                  <p>{session.user_agent || "-"}</p>
                  {!session.revoked_at ? (
                    <button
                      className="fa-admin-row-link"
                      disabled={busy}
                      onClick={() => void handleRevokeSession(session.session_id)}
                      type="button"
                    >
                      {isChineseUi ? "撤销" : "Revoke"}
                    </button>
                  ) : null}
                </div>
              ))}
              {!sessionItems.length && !sessionsQuery.isLoading ? (
                <div className="fa-observability-empty is-compact">
                  {isChineseUi ? "暂无会话。" : "No sessions yet."}
                </div>
              ) : null}
            </div>
          </div>

          <div className="fa-admin-panel fa-admin-audit-side">
            <div className="fa-observability-panel-header">
              <div>
                <strong>{isChineseUi ? "Audit" : "Audit"}</strong>
                <h2>{isChineseUi ? "近期事件" : "Recent Events"}</h2>
              </div>
              <Link className="fa-admin-row-link" to="/admin/audit-events">
                {isChineseUi ? "全部审计" : "All audit"}
              </Link>
            </div>
            {auditQuery.error ? (
              <AdminErrorMessage error={auditQuery.error} fallback="Failed to load audit events." />
            ) : null}
            <div className="fa-admin-event-list">
              {auditItems.map((event) => (
                <div className="fa-admin-event-row" key={event.event_id}>
                  <div>
                    <strong>{event.action}</strong>
                    <span>{event.actor_user_id || "-"}</span>
                  </div>
                  <span className={`fa-observability-pill is-${event.decision === "allow" ? "success" : "neutral"}`}>
                    {event.decision}
                  </span>
                  <p>{event.reason || event.resource_id || "-"}</p>
                  <small>{formatAdminDate(event.created_at, locale)}</small>
                </div>
              ))}
              {!auditItems.length && !auditQuery.isLoading ? (
                <div className="fa-observability-empty is-compact">
                  {isChineseUi ? "暂无相关审计事件。" : "No related audit events yet."}
                </div>
              ) : null}
            </div>
          </div>
        </section>
      </div>
    </AdminAccessGate>
  );
}
