import { Link } from "@tanstack/react-router";
import { type FormEvent, useEffect, useMemo, useState } from "react";

import { useShellUi } from "@/app/shell/shell-ui-context";
import {
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
import {
  AccessPanel,
  AuditEventsPanel,
  ProfilePanel,
  SecuritySessionsPanel,
} from "./admin-user-detail-panels";
import { useLastRouteParam } from "../use-last-route-param";

export function AdminUserDetailPage() {
  const { isChineseUi } = useShellUi();
  const locale = isChineseUi ? "zh-CN" : "en-US";
  const userId = useLastRouteParam("userId") ?? "";
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
          <ProfilePanel
            busy={busy}
            displayName={displayName}
            email={email}
            isChineseUi={isChineseUi}
            isLoading={userQuery.isLoading}
            isSaving={updateUser.isPending}
            locale={locale}
            metadataDraft={metadataDraft}
            onDisplayNameChange={setDisplayName}
            onEmailChange={setEmail}
            onMetadataDraftChange={setMetadataDraft}
            onSaveProfile={handleSaveProfile}
            onTenantIdChange={setTenantId}
            onUsernameChange={setUsername}
            tenantId={tenantId}
            user={user}
            userId={userId}
            username={username}
          />

          <AccessPanel
            busy={busy}
            isChineseUi={isChineseUi}
            isSavingRoles={updateRoles.isPending}
            isSavingStatus={updateStatus.isPending}
            message={message}
            onReasonDraftChange={setReasonDraft}
            onRoleDraftChange={setRoleDraft}
            onSaveRoles={handleSaveRoles}
            onSaveStatus={handleSaveStatus}
            onStatusDraftChange={setStatusDraft}
            reasonDraft={reasonDraft}
            roleChips={roleChips}
            roleDraft={roleDraft}
            statusDraft={statusDraft}
          />

          <SecuritySessionsPanel
            busy={busy}
            error={sessionsQuery.error}
            isChineseUi={isChineseUi}
            isLoading={sessionsQuery.isLoading}
            isResettingPassword={resetPassword.isPending}
            locale={locale}
            newPassword={newPassword}
            onNewPasswordChange={setNewPassword}
            onResetPassword={handleResetPassword}
            onRevokeSession={handleRevokeSession}
            sessions={sessionItems}
          />

          <AuditEventsPanel
            auditEvents={auditItems}
            error={auditQuery.error}
            isChineseUi={isChineseUi}
            isLoading={auditQuery.isLoading}
            locale={locale}
          />
        </section>
      </div>
    </AdminAccessGate>
  );
}
