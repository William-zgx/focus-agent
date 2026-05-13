import type {
  FocusAgentAuditEvent,
  FocusAgentSession,
  FocusAgentUser,
} from "@focus-agent/web-sdk";
import { Link } from "@tanstack/react-router";
import type { FormEvent } from "react";

import {
  ADMIN_USER_STATUSES,
  formatAdminDate,
} from "@/features/admin-users/admin-user-utils";

import { AdminErrorMessage } from "./admin-page-chrome";
import { AdminField, AdminPanelHeader } from "./admin-page-sections";

export function messageNoticeTone(message: string) {
  const normalized = message.toLowerCase();
  return normalized.includes("failed") ||
    normalized.includes("invalid") ||
    normalized.includes("required") ||
    message.includes("请填写") ||
    message.includes("失败") ||
    message.includes("无效")
    ? "is-danger"
    : "is-success";
}

type ProfilePanelProps = {
  busy: boolean;
  displayName: string;
  email: string;
  isChineseUi: boolean;
  isLoading: boolean;
  isSaving: boolean;
  locale: string;
  metadataDraft: string;
  onDisplayNameChange: (value: string) => void;
  onEmailChange: (value: string) => void;
  onMetadataDraftChange: (value: string) => void;
  onSaveProfile: (event: FormEvent<HTMLFormElement>) => void;
  onTenantIdChange: (value: string) => void;
  onUsernameChange: (value: string) => void;
  tenantId: string;
  user: FocusAgentUser | null;
  userId: string;
  username: string;
};

export function ProfilePanel({
  busy,
  displayName,
  email,
  isChineseUi,
  isLoading,
  isSaving,
  locale,
  metadataDraft,
  onDisplayNameChange,
  onEmailChange,
  onMetadataDraftChange,
  onSaveProfile,
  onTenantIdChange,
  onUsernameChange,
  tenantId,
  user,
  userId,
  username,
}: ProfilePanelProps) {
  return (
    <form className="fa-admin-panel" onSubmit={onSaveProfile}>
      <AdminPanelHeader
        eyebrow={isChineseUi ? "Profile" : "Profile"}
        status={isLoading ? "loading" : userId}
        title={isChineseUi ? "基础资料" : "Profile"}
      />
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
      <AdminField label={isChineseUi ? "用户名" : "Username"}>
        <input value={username} onChange={(event) => onUsernameChange(event.target.value)} />
      </AdminField>
      <AdminField label={isChineseUi ? "显示名" : "Display name"}>
        <input value={displayName} onChange={(event) => onDisplayNameChange(event.target.value)} />
      </AdminField>
      <AdminField label="Email">
        <input value={email} onChange={(event) => onEmailChange(event.target.value)} type="email" />
      </AdminField>
      <AdminField label={isChineseUi ? "租户" : "Tenant"}>
        <input value={tenantId} onChange={(event) => onTenantIdChange(event.target.value)} />
      </AdminField>
      <AdminField label="Metadata JSON">
        <textarea
          value={metadataDraft}
          onChange={(event) => onMetadataDraftChange(event.target.value)}
          rows={8}
          spellCheck={false}
        />
      </AdminField>
      <div className="fa-observability-command-bar">
        <button className="fa-observability-preset is-primary" disabled={busy} type="submit">
          {isSaving
            ? isChineseUi ? "保存中..." : "Saving..."
            : isChineseUi ? "保存资料" : "Save Profile"}
        </button>
      </div>
    </form>
  );
}

type AccessPanelProps = {
  busy: boolean;
  isChineseUi: boolean;
  isSavingRoles: boolean;
  isSavingStatus: boolean;
  message: string | null;
  onReasonDraftChange: (value: string) => void;
  onRoleDraftChange: (value: string) => void;
  onSaveRoles: () => void;
  onSaveStatus: () => void;
  onStatusDraftChange: (value: string) => void;
  reasonDraft: string;
  roleChips: string[];
  roleDraft: string;
  statusDraft: string;
};

export function AccessPanel({
  busy,
  isChineseUi,
  isSavingRoles,
  isSavingStatus,
  message,
  onReasonDraftChange,
  onRoleDraftChange,
  onSaveRoles,
  onSaveStatus,
  onStatusDraftChange,
  reasonDraft,
  roleChips,
  roleDraft,
  statusDraft,
}: AccessPanelProps) {
  return (
    <div className="fa-admin-panel">
      <AdminPanelHeader
        eyebrow={isChineseUi ? "Access" : "Access"}
        status={`${roleChips.length} roles`}
        title={isChineseUi ? "状态与角色" : "Status And Roles"}
      />
      <AdminField label={isChineseUi ? "状态" : "Status"}>
        <select value={statusDraft} onChange={(event) => onStatusDraftChange(event.target.value)}>
          {ADMIN_USER_STATUSES.map((status) => (
            <option key={status} value={status}>{status}</option>
          ))}
        </select>
      </AdminField>
      <AdminField label={isChineseUi ? "角色" : "Roles"}>
        <input value={roleDraft} onChange={(event) => onRoleDraftChange(event.target.value)} />
      </AdminField>
      <div className="fa-admin-chip-row">
        {roleChips.map((role) => <span key={role}>{role}</span>)}
      </div>
      <AdminField label={isChineseUi ? "审计原因" : "Audit reason"}>
        <textarea
          value={reasonDraft}
          onChange={(event) => onReasonDraftChange(event.target.value)}
          rows={4}
        />
      </AdminField>
      {message ? (
        <div className={`fa-inline-notice ${messageNoticeTone(message)}`}>
          {message}
        </div>
      ) : null}
      <div className="fa-admin-action-row">
        <button
          className="fa-observability-preset is-primary"
          disabled={busy}
          onClick={() => void onSaveStatus()}
          type="button"
        >
          {isSavingStatus
            ? isChineseUi ? "更新中..." : "Updating..."
            : isChineseUi ? "更新状态" : "Update Status"}
        </button>
        <button
          className="fa-observability-preset"
          disabled={busy}
          onClick={() => void onSaveRoles()}
          type="button"
        >
          {isSavingRoles
            ? isChineseUi ? "保存中..." : "Saving..."
            : isChineseUi ? "保存角色" : "Save Roles"}
        </button>
      </div>
    </div>
  );
}

type SecuritySessionsPanelProps = {
  busy: boolean;
  error: Error | null;
  isChineseUi: boolean;
  isLoading: boolean;
  isResettingPassword: boolean;
  locale: string;
  newPassword: string;
  onNewPasswordChange: (value: string) => void;
  onResetPassword: () => void;
  onRevokeSession: (sessionId: string) => void;
  sessions: FocusAgentSession[];
};

export function SecuritySessionsPanel({
  busy,
  error,
  isChineseUi,
  isLoading,
  isResettingPassword,
  locale,
  newPassword,
  onNewPasswordChange,
  onResetPassword,
  onRevokeSession,
  sessions,
}: SecuritySessionsPanelProps) {
  return (
    <div className="fa-admin-panel">
      <AdminPanelHeader
        eyebrow={isChineseUi ? "Security" : "Security"}
        status={`${sessions.length} sessions`}
        title={isChineseUi ? "密码与会话" : "Password And Sessions"}
      />
      <AdminField label={isChineseUi ? "新密码" : "New password"}>
        <input
          autoComplete="new-password"
          onChange={(event) => onNewPasswordChange(event.target.value)}
          type="password"
          value={newPassword}
        />
      </AdminField>
      <div className="fa-observability-command-bar">
        <button
          className="fa-observability-preset is-primary"
          disabled={busy}
          onClick={() => void onResetPassword()}
          type="button"
        >
          {isResettingPassword
            ? isChineseUi ? "重置中..." : "Resetting..."
            : isChineseUi ? "重置密码" : "Reset Password"}
        </button>
      </div>
      {error ? (
        <AdminErrorMessage error={error} fallback="Failed to load sessions." />
      ) : null}
      <div className="fa-admin-event-list">
        {sessions.map((session) => (
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
                onClick={() => void onRevokeSession(session.session_id)}
                type="button"
              >
                {isChineseUi ? "撤销" : "Revoke"}
              </button>
            ) : null}
          </div>
        ))}
        {!sessions.length && !isLoading ? (
          <div className="fa-observability-empty is-compact">
            {isChineseUi ? "暂无会话。" : "No sessions yet."}
          </div>
        ) : null}
      </div>
    </div>
  );
}

type AuditEventsPanelProps = {
  auditEvents: FocusAgentAuditEvent[];
  error: Error | null;
  isChineseUi: boolean;
  isLoading: boolean;
  locale: string;
};

export function AuditEventsPanel({
  auditEvents,
  error,
  isChineseUi,
  isLoading,
  locale,
}: AuditEventsPanelProps) {
  return (
    <div className="fa-admin-panel fa-admin-audit-side">
      <AdminPanelHeader
        eyebrow={isChineseUi ? "Audit" : "Audit"}
        status={(
          <Link className="fa-admin-row-link" to="/admin/audit-events">
            {isChineseUi ? "全部审计" : "All audit"}
          </Link>
        )}
        title={isChineseUi ? "近期事件" : "Recent Events"}
      />
      {error ? (
        <AdminErrorMessage error={error} fallback="Failed to load audit events." />
      ) : null}
      <div className="fa-admin-event-list">
        {auditEvents.map((event) => (
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
        {!auditEvents.length && !isLoading ? (
          <div className="fa-observability-empty is-compact">
            {isChineseUi ? "暂无相关审计事件。" : "No related audit events yet."}
          </div>
        ) : null}
      </div>
    </div>
  );
}
