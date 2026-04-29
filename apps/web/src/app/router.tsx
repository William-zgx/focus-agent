import {
  Link,
  Outlet,
  RouterProvider,
  createRootRoute,
  createRoute,
  createRouter,
  useNavigate,
  useSearch,
  useRouterState,
} from "@tanstack/react-router";
import { type ReactNode, useEffect, useMemo } from "react";

import { useShellUi } from "@/app/shell/shell-ui-context";
import { AppShell } from "@/app/shell/app-shell";
import { useConversations } from "@/features/conversations/use-conversations";
import { AgentRoleConsolePage } from "@/pages/agents/agent-role-console-page";
import { AgentTeamWorkbenchPage } from "@/pages/agent-team/team-workbench-page";
import { AdminAuditEventsPage } from "@/pages/admin/admin-audit-events-page";
import { AdminUserDetailPage } from "@/pages/admin/admin-user-detail-page";
import { AdminUsersPage } from "@/pages/admin/admin-users-page";
import { AccountProfilePage } from "@/pages/account/profile-page";
import { AccountSecurityPage } from "@/pages/account/security-page";
import { AccountSessionsPage } from "@/pages/account/sessions-page";
import { LoginPage } from "@/pages/auth/login-page";
import { RegisterPage } from "@/pages/auth/register-page";
import { TrajectoryPage } from "@/pages/observability/trajectory-page";
import { ThreadPage } from "@/pages/thread/thread-page";
import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";
import { normalizeAuthReturnTo } from "@/pages/auth/return-to";

function RootLayout() {
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const isAuthRoute = pathname === "/auth" || pathname.startsWith("/auth/");

  if (isAuthRoute) {
    return <Outlet />;
  }

  return (
    <AppShell>
      <Outlet />
    </AppShell>
  );
}

function NotFoundPage() {
  const { isChineseUi } = useShellUi();

  return (
    <div className="fa-route-state">
      <div className="fa-route-state-card">
        <p className="fa-route-state-title">{isChineseUi ? "页面不存在" : "Page not found"}</p>
        <Link className="fa-route-state-link" to="/">
          {isChineseUi ? "返回首页" : "Go back home"}
        </Link>
      </div>
    </div>
  );
}

function HomePage() {
  const navigate = useNavigate();
  const { isChineseUi } = useShellUi();
  const { data, isLoading } = useConversations();
  const conversations = data?.conversations ?? [];
  const firstActiveConversation = conversations.find((item) => !item.is_archived) ?? conversations[0];

  useEffect(() => {
    if (isLoading || !firstActiveConversation) return;
    void navigate({
      to: "/c/$conversationId/t/$threadId",
      params: {
        conversationId: firstActiveConversation.root_thread_id,
        threadId: firstActiveConversation.root_thread_id,
      },
      replace: true,
    });
  }, [firstActiveConversation, isLoading, navigate]);

  return (
    <div className="fa-thread-layout">
      <section className="fa-chat-transcript">
        <div className="fa-chat-history">
          <div className="fa-chat-history-content">
            <div className="fa-chat-empty">
              {isChineseUi
                ? "从这里开始聊天。只要 Agent 产生分支，左侧就会显示出来。"
                : "Start chatting here. Branches appear on the left whenever the agent forks work."}
            </div>
          </div>
        </div>
      </section>

      <section className="fa-composer-slot">
        <div className="fa-inline-notice">
          {isChineseUi
            ? "在这里发送第一条消息。需要探索另一条路径时，再新建分支。"
            : "Send the first message here. Create a branch only when you want to explore a separate path."}
        </div>
      </section>
    </div>
  );
}

function AuthGate({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const { principal, ready } = useFocusAgent();
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const search = useRouterState({ select: (state) => state.location.searchStr });
  const isAuthRoute = pathname === "/auth" || pathname.startsWith("/auth/");
  const returnTo = isAuthRoute ? "/" : normalizeAuthReturnTo(`${pathname}${search}`);

  useEffect(() => {
    if (ready && !principal && !isAuthRoute) {
      void navigate({
        to: "/auth/login",
        search: { return_to: returnTo },
        replace: true,
      });
    }
  }, [isAuthRoute, navigate, principal, ready, returnTo]);

  if (!ready || !principal) {
    return (
      <div className="fa-route-state">
        <div className="fa-route-state-card">Redirecting to sign in...</div>
      </div>
    );
  }

  return <>{children}</>;
}

function protect(component: ReactNode) {
  return function ProtectedRouteComponent() {
    return <AuthGate>{component}</AuthGate>;
  };
}

function AuthIndexRedirect() {
  const navigate = useNavigate();
  const search = useSearch({ strict: false });
  const returnTo = useMemo(() => normalizeAuthReturnTo((search as { return_to?: unknown }).return_to), [search]);

  useEffect(() => {
    void navigate({
      to: "/auth/login",
      search: { return_to: returnTo },
      replace: true,
    });
  }, [navigate, returnTo]);

  return (
    <div className="fa-route-state">
      <div className="fa-route-state-card">正在进入登录页...</div>
    </div>
  );
}

const rootRoute = createRootRoute({
  component: RootLayout,
  notFoundComponent: NotFoundPage,
});

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: protect(<HomePage />),
});

const threadRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/c/$conversationId/t/$threadId",
  component: protect(<ThreadPage />),
});

const reviewRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/c/$conversationId/t/$threadId/review",
  component: protect(<ThreadPage />),
});

const trajectoryRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/observability/trajectory",
  component: protect(<TrajectoryPage />),
});

const observabilityOverviewRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/observability/overview",
  component: protect(<TrajectoryPage />),
});

const agentRoleConsoleRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/agent/roles",
  component: protect(<AgentRoleConsolePage />),
});

const agentGovernanceConsoleRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/agent/governance",
  component: protect(<AgentRoleConsolePage />),
});

const agentTeamRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/agent-team",
  component: protect(<AgentTeamWorkbenchPage />),
});

const agentTeamSessionRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/agent-team/$sessionId",
  component: protect(<AgentTeamWorkbenchPage />),
});

const adminUsersRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/admin/users",
  component: protect(<AdminUsersPage />),
});

const adminUserDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/admin/users/$userId",
  component: protect(<AdminUserDetailPage />),
});

const adminAuditEventsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/admin/audit-events",
  component: protect(<AdminAuditEventsPage />),
});

const authRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/auth",
  component: AuthIndexRedirect,
});

const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/auth/login",
  component: LoginPage,
});

const registerRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/auth/register",
  component: RegisterPage,
});

const accountProfileRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/account/profile",
  component: protect(<AccountProfilePage />),
});

const accountSecurityRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/account/security",
  component: protect(<AccountSecurityPage />),
});

const accountSessionsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/account/sessions",
  component: protect(<AccountSessionsPage />),
});

const routeTree = rootRoute.addChildren([
  indexRoute,
  threadRoute,
  reviewRoute,
  trajectoryRoute,
  observabilityOverviewRoute,
  agentRoleConsoleRoute,
  agentGovernanceConsoleRoute,
  agentTeamRoute,
  agentTeamSessionRoute,
  adminUsersRoute,
  adminUserDetailRoute,
  adminAuditEventsRoute,
  authRoute,
  loginRoute,
  registerRoute,
  accountProfileRoute,
  accountSecurityRoute,
  accountSessionsRoute,
]);

const router = createRouter({
  routeTree,
  basepath: "/app",
  context: {
    isAuthenticated: false,
  },
  defaultPreload: "intent",
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

export function AppRouter() {
  const { ready, principal } = useFocusAgent();
  const isChineseBrowser =
    typeof navigator !== "undefined" && navigator.language.toLowerCase().startsWith("zh");

  if (!ready) {
    return (
      <div className="fa-route-state">
        <div className="fa-route-state-card">
          {isChineseBrowser ? "正在准备 Focus Agent 会话..." : "Preparing Focus Agent session..."}
        </div>
      </div>
    );
  }

  return <RouterProvider router={router} context={{ isAuthenticated: Boolean(principal) }} />;
}
