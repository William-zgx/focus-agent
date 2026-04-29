import { Link } from "@tanstack/react-router";
import type { PropsWithChildren, ReactNode } from "react";

import { useShellUi } from "@/app/shell/shell-ui-context";
import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";
import { SessionExitIcon } from "@/shared/ui/toolbar-icons";

type AdminRouteKey = "users" | "audit";

export function AdminAccessGate({ children }: PropsWithChildren) {
  const { isAdmin, logout } = useFocusAgent();
  const { isChineseUi } = useShellUi();

  if (!isAdmin) {
    return (
      <div className="fa-admin-layout">
        <section className="fa-admin-panel fa-admin-denied">
          <p className="fa-admin-eyebrow">{isChineseUi ? "Admin" : "Admin"}</p>
          <h1>{isChineseUi ? "需要管理员权限" : "Admin Access Required"}</h1>
          <p>
            {isChineseUi
              ? "当前会话没有管理员角色或管理员标记。"
              : "The current principal does not include an admin role or admin flag."}
          </p>
          <div className="fa-auth-actions">
            <Link className="fa-route-state-link" to="/auth">
              {isChineseUi ? "返回 /auth" : "Return to /auth"}
            </Link>
            <button className="fa-auth-button" onClick={() => void logout()} type="button">
              {isChineseUi ? "切换账号 / 退出登录" : "Switch account / sign out"}
            </button>
          </div>
        </section>
      </div>
    );
  }

  return <>{children}</>;
}

export function AdminRouteTabs({ active }: { active: AdminRouteKey }) {
  const { isChineseUi } = useShellUi();

  return (
    <nav
      aria-label={isChineseUi ? "管理员页面" : "Admin pages"}
      className="fa-trajectory-workbench-tabs fa-admin-tabs"
    >
      <Link
        className={`fa-trajectory-workbench-tab ${active === "users" ? "is-active" : ""}`}
        to="/admin/users"
      >
        <span>{isChineseUi ? "用户" : "Users"}</span>
        <strong>{isChineseUi ? "账号 / 角色" : "Accounts / roles"}</strong>
      </Link>
      <Link
        className={`fa-trajectory-workbench-tab ${active === "audit" ? "is-active" : ""}`}
        to="/admin/audit-events"
      >
        <span>{isChineseUi ? "审计" : "Audit"}</span>
        <strong>{isChineseUi ? "操作 / 决策" : "Actions / decisions"}</strong>
      </Link>
    </nav>
  );
}

export function AdminPageHeading({
  active,
  title,
  summary,
  side,
}: {
  active: AdminRouteKey;
  title: string;
  summary: string;
  side?: ReactNode;
}) {
  const { isChineseUi } = useShellUi();
  const { logout } = useFocusAgent();

  return (
    <section className="fa-trajectory-workbench-header fa-admin-header">
      <div className="fa-trajectory-workbench-header-copy">
        <div className="fa-trajectory-workbench-heading">
          <p className="fa-admin-eyebrow">{isChineseUi ? "管理后台" : "Admin Console"}</p>
          <h1>{title}</h1>
          <p>{summary}</p>
        </div>
        <AdminRouteTabs active={active} />
      </div>
      <div className="fa-trajectory-workbench-header-side">
        {side}
        <button
          className="fa-admin-row-link fa-admin-session-button"
          onClick={() => void logout()}
          type="button"
        >
          <span className="fa-toolbar-icon" aria-hidden="true">
            <SessionExitIcon />
          </span>
          <span>{isChineseUi ? "退出登录" : "Sign out"}</span>
        </button>
      </div>
    </section>
  );
}

export function AdminErrorMessage({
  error,
  fallback,
}: {
  error: unknown;
  fallback: string;
}) {
  return (
    <div className="fa-inline-notice is-danger">
      {error instanceof Error ? error.message : fallback}
    </div>
  );
}
