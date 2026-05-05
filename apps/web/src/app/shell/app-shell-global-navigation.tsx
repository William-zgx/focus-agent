import { Link } from "@tanstack/react-router";

import type {
  AdminNavTarget,
  AgentTeamNavTarget,
  ChatNavTarget,
} from "@/app/shell/app-shell-config";
import {
  AdminConsoleIcon,
  AgentTeamIcon,
  ChatBubbleIcon,
} from "@/shared/ui/toolbar-icons";
import { tooltipProps } from "@/shared/ui/tooltip";

type AppShellGlobalNavigationProps = {
  adminNavTarget: AdminNavTarget;
  agentTeamRootThreadId: string;
  chatNavTarget: ChatNavTarget | null;
  isAdminRoute: boolean;
  isAgentWorkbenchShell: boolean;
  isChatRoute: boolean;
  isChineseUi: boolean;
  lastAgentTeamTarget: AgentTeamNavTarget | null;
};

export function AppShellGlobalNavigation({
  adminNavTarget,
  agentTeamRootThreadId,
  chatNavTarget,
  isAdminRoute,
  isAgentWorkbenchShell,
  isChatRoute,
  isChineseUi,
  lastAgentTeamTarget,
}: AppShellGlobalNavigationProps) {
  const chatNavLabel = isChineseUi ? "对话" : "Chat";
  const agentTeamNavLabel = "Agent Team";
  const adminNavLabel = isChineseUi ? "管理后台" : "Admin";

  return (
    <nav
      aria-label={isChineseUi ? "全局导航" : "Global navigation"}
      className="fa-sidebar-global-nav"
    >
      {chatNavTarget ? (
        <Link
          aria-label={chatNavLabel}
          className={`fa-sidebar-nav-link ${isChatRoute ? "is-active" : ""}`.trim()}
          params={chatNavTarget}
          {...tooltipProps(chatNavLabel)}
          to="/c/$conversationId/t/$threadId"
        >
          <span className="fa-sidebar-nav-icon" aria-hidden="true">
            <ChatBubbleIcon />
          </span>
          <span>{chatNavLabel}</span>
        </Link>
      ) : (
        <Link
          aria-label={chatNavLabel}
          className={`fa-sidebar-nav-link ${isChatRoute ? "is-active" : ""}`.trim()}
          {...tooltipProps(chatNavLabel)}
          to="/"
        >
          <span className="fa-sidebar-nav-icon" aria-hidden="true">
            <ChatBubbleIcon />
          </span>
          <span>{chatNavLabel}</span>
        </Link>
      )}
      {!isChatRoute ? (
        lastAgentTeamTarget?.sessionId ? (
          <Link
            aria-label={agentTeamNavLabel}
            className={`fa-sidebar-nav-link ${isAgentWorkbenchShell ? "is-active" : ""}`.trim()}
            params={{ sessionId: lastAgentTeamTarget.sessionId }}
            {...tooltipProps(agentTeamNavLabel)}
            to="/agent-team/$sessionId"
          >
            <span className="fa-sidebar-nav-icon" aria-hidden="true">
              <AgentTeamIcon />
            </span>
            <span>{agentTeamNavLabel}</span>
          </Link>
        ) : (
          <Link
            aria-label={agentTeamNavLabel}
            className={`fa-sidebar-nav-link ${isAgentWorkbenchShell ? "is-active" : ""}`.trim()}
            search={agentTeamRootThreadId ? { root_thread_id: agentTeamRootThreadId } : undefined}
            {...tooltipProps(agentTeamNavLabel)}
            to="/agent-team"
          >
            <span className="fa-sidebar-nav-icon" aria-hidden="true">
              <AgentTeamIcon />
            </span>
            <span>{agentTeamNavLabel}</span>
          </Link>
        )
      ) : null}
      {!isChatRoute ? (
        adminNavTarget.page === "audit" ? (
          <Link
            aria-label={adminNavLabel}
            className={`fa-sidebar-nav-link ${isAdminRoute ? "is-active" : ""}`.trim()}
            {...tooltipProps(adminNavLabel)}
            to="/admin/audit-events"
          >
            <span className="fa-sidebar-nav-icon" aria-hidden="true">
              <AdminConsoleIcon />
            </span>
            <span>{adminNavLabel}</span>
          </Link>
        ) : adminNavTarget.page === "user" ? (
          <Link
            aria-label={adminNavLabel}
            className={`fa-sidebar-nav-link ${isAdminRoute ? "is-active" : ""}`.trim()}
            params={{ userId: adminNavTarget.userId }}
            {...tooltipProps(adminNavLabel)}
            to="/admin/users/$userId"
          >
            <span className="fa-sidebar-nav-icon" aria-hidden="true">
              <AdminConsoleIcon />
            </span>
            <span>{adminNavLabel}</span>
          </Link>
        ) : (
          <Link
            aria-label={adminNavLabel}
            className={`fa-sidebar-nav-link ${isAdminRoute ? "is-active" : ""}`.trim()}
            {...tooltipProps(adminNavLabel)}
            to="/admin/users"
          >
            <span className="fa-sidebar-nav-icon" aria-hidden="true">
              <AdminConsoleIcon />
            </span>
            <span>{adminNavLabel}</span>
          </Link>
        )
      ) : null}
    </nav>
  );
}
