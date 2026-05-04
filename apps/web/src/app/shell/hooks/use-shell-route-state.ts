import { useRouterState } from "@tanstack/react-router";

import { resolveShellMode } from "@/app/shell/app-shell-config";

export function useShellRouteState() {
  const routeState = useRouterState({
    select: (state) => {
      const routeParams = (state.matches.at(-1)?.params ?? {}) as Partial<
        Record<"conversationId" | "sessionId" | "threadId" | "userId", string>
      >;
      const routeSearch = (state.location.search ?? {}) as Partial<Record<string, unknown>>;
      const rootThreadSearch =
        typeof routeSearch.root_thread_id === "string" ? routeSearch.root_thread_id : "";

      return {
        conversationId: String(routeParams.conversationId ?? ""),
        threadId: String(routeParams.threadId ?? ""),
        isReviewRoute: state.location.pathname.endsWith("/review"),
        pathname: state.location.pathname,
        rootThreadSearch,
        sessionId: String(routeParams.sessionId ?? ""),
        userId: String(routeParams.userId ?? ""),
      };
    },
  });
  const shellMode = resolveShellMode(routeState.pathname);
  const isChatRoute = routeState.pathname === "/" || routeState.pathname.startsWith("/c/");
  const isAgentTeamRoute =
    routeState.pathname === "/agent-team" || routeState.pathname.startsWith("/agent-team/");
  const isObservabilityRoute =
    routeState.pathname === "/observability/overview" ||
    routeState.pathname === "/observability/trajectory";
  const isAgentGovernanceRoute =
    routeState.pathname === "/agent/governance" || routeState.pathname === "/agent/roles";
  const isAdminRoute =
    routeState.pathname === "/admin/users" ||
    routeState.pathname.startsWith("/admin/users/") ||
    routeState.pathname === "/admin/audit-events";

  return {
    ...routeState,
    shellMode,
    isChatShell: shellMode === "chat",
    isAgentWorkbenchShell: shellMode === "agent-workbench",
    isAdminShell: shellMode === "admin",
    isWorkspaceShell: shellMode === "agent-workbench" || shellMode === "admin",
    isChatRoute,
    isAgentTeamRoute,
    isObservabilityRoute,
    isAgentGovernanceRoute,
    isAdminRoute,
  };
}

export type ShellRouteState = ReturnType<typeof useShellRouteState>;
