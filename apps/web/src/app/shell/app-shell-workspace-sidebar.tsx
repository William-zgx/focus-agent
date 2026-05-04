import { Link } from "@tanstack/react-router";

type AppShellWorkspaceSidebarProps = {
  activeAgentWorkbenchModule: "diagnostics" | "governance" | "team";
  agentTeamRootThreadId: string;
  isAgentWorkbenchShell: boolean;
  isChineseUi: boolean;
  pathname: string;
};

export function AppShellWorkspaceSidebar({
  activeAgentWorkbenchModule,
  agentTeamRootThreadId,
  isAgentWorkbenchShell,
  isChineseUi,
  pathname,
}: AppShellWorkspaceSidebarProps) {
  return (
    <div className="fa-workspace-sidebar">
      <div className="fa-workspace-sidebar-heading">
        <span>{isChineseUi ? "工作区" : "Workspace"}</span>
        <strong>
          {isAgentWorkbenchShell
            ? isChineseUi
              ? "Agent Workbench"
              : "Agent Workbench"
            : isChineseUi
              ? "系统管理"
              : "Administration"}
        </strong>
        <p>
          {isAgentWorkbenchShell
            ? isChineseUi
              ? "统一进入协作、诊断和治理，不再切到全屏孤岛。"
              : "One shell for collaboration, diagnostics, and governance."
            : isChineseUi
              ? "管理账号、权限与审计记录。"
              : "Manage accounts, permissions, and audit records."}
        </p>
      </div>
      <div
        className="fa-workspace-sidebar-list"
        aria-label={isChineseUi ? "工作区导航" : "Workspace navigation"}
      >
        {isAgentWorkbenchShell ? (
          <>
            <Link
              className={`fa-workspace-sidebar-item ${
                activeAgentWorkbenchModule === "team" ? "is-active" : ""
              }`.trim()}
              search={agentTeamRootThreadId ? { root_thread_id: agentTeamRootThreadId } : undefined}
              to="/agent-team"
            >
              <span>{isChineseUi ? "协作" : "Team"}</span>
              <strong>{isChineseUi ? "并发任务与会话" : "Tasks and sessions"}</strong>
            </Link>
            <Link
              className={`fa-workspace-sidebar-item ${
                activeAgentWorkbenchModule === "diagnostics" ? "is-active" : ""
              }`.trim()}
              to="/observability/overview"
            >
              <span>{isChineseUi ? "诊断" : "Diagnostics"}</span>
              <strong>{isChineseUi ? "Trajectory 健康与复盘" : "Health and review"}</strong>
            </Link>
            <Link
              className={`fa-workspace-sidebar-item ${
                activeAgentWorkbenchModule === "governance" ? "is-active" : ""
              }`.trim()}
              to="/agent/governance"
            >
              <span>{isChineseUi ? "治理" : "Governance"}</span>
              <strong>{isChineseUi ? "记忆 / 工具 / 路由" : "Memory / tools / routing"}</strong>
            </Link>
          </>
        ) : (
          <>
            <Link
              className={`fa-workspace-sidebar-item ${pathname.startsWith("/admin/users") ? "is-active" : ""}`.trim()}
              to="/admin/users"
            >
              <span>{isChineseUi ? "用户与角色" : "Users and roles"}</span>
              <strong>{isChineseUi ? "账号与权限" : "Accounts and access"}</strong>
            </Link>
            <Link
              className={`fa-workspace-sidebar-item ${pathname === "/admin/audit-events" ? "is-active" : ""}`.trim()}
              to="/admin/audit-events"
            >
              <span>{isChineseUi ? "审计事件" : "Audit events"}</span>
              <strong>{isChineseUi ? "登录与操作记录" : "Login and action records"}</strong>
            </Link>
          </>
        )}
      </div>
    </div>
  );
}
