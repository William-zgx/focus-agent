import {
  Link,
  Outlet,
  RouterProvider,
  createRootRoute,
  createRoute,
  createRouter,
  useNavigate,
} from "@tanstack/react-router";
import { type FormEvent, useEffect, useState } from "react";

import { useShellUi } from "@/app/shell/shell-ui-context";
import { AppShell } from "@/app/shell/app-shell";
import { useConversations } from "@/features/conversations/use-conversations";
import { AgentRoleConsolePage } from "@/pages/agents/agent-role-console-page";
import { TrajectoryPage } from "@/pages/observability/trajectory-page";
import { ThreadPage } from "@/pages/thread/thread-page";
import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";

function RootLayout() {
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

function AuthBootstrapPage() {
  const { isChineseUi } = useShellUi();
  const { authError, authHint, authenticateWithToken, clearStoredToken } = useFocusAgent();
  const [token, setToken] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const showsDisabledDemoTokenHint = authHint === "demo_token_disabled";

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token.trim() || submitting) return;
    setSubmitting(true);
    try {
      await authenticateWithToken(token);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fa-route-state">
      <div className="fa-route-state-card fa-auth-bootstrap-card">
        <p className="fa-route-state-title">
          {isChineseUi ? "需要提供访问令牌" : "Bearer Token Required"}
        </p>
        <p className="fa-auth-bootstrap-copy">
          {showsDisabledDemoTokenHint
            ? isChineseUi
              ? "当前部署未开启 demo token 自举。请输入已有的 Bearer Token 以继续访问内置 Web App。"
              : "This deployment does not allow demo-token bootstrap. Provide an existing bearer token to continue using the bundled Web App."
            : isChineseUi
              ? "当前会话暂时无法自动完成认证。你可以粘贴已有的 Bearer Token 继续，或稍后重试。"
              : "Automatic authentication is currently unavailable. Paste an existing bearer token to continue, or retry in a moment."}
        </p>
        {authError ? (
          <div className="fa-inline-notice is-danger">
            {isChineseUi ? `认证失败：${authError}` : `Authentication failed: ${authError}`}
          </div>
        ) : null}
        <form className="fa-auth-bootstrap-form" onSubmit={handleSubmit}>
          <label className="fa-auth-bootstrap-label" htmlFor="fa-auth-token">
            {isChineseUi ? "Bearer Token" : "Bearer Token"}
          </label>
          <textarea
            id="fa-auth-token"
            className="fa-auth-bootstrap-input"
            value={token}
            onChange={(event) => setToken(event.target.value)}
            placeholder={
              isChineseUi
                ? "粘贴已有 access token"
                : "Paste an existing access token"
            }
            rows={4}
            spellCheck={false}
            autoCapitalize="off"
            autoCorrect="off"
          />
          <div className="fa-auth-bootstrap-actions">
            <button
              className="fa-auth-bootstrap-button is-primary"
              disabled={submitting || !token.trim()}
              type="submit"
            >
              {submitting
                ? isChineseUi
                  ? "验证中..."
                  : "Verifying..."
                : isChineseUi
                  ? "使用此令牌继续"
                  : "Continue With Token"}
            </button>
            <button
              className="fa-auth-bootstrap-button"
              disabled={submitting}
              onClick={() => {
                setToken("");
                clearStoredToken();
              }}
              type="button"
            >
              {isChineseUi ? "清除本地令牌" : "Clear Saved Token"}
            </button>
          </div>
        </form>
      </div>
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
  component: HomePage,
});

const threadRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/c/$conversationId/t/$threadId",
  component: ThreadPage,
});

const reviewRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/c/$conversationId/t/$threadId/review",
  component: ThreadPage,
});

const trajectoryRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/observability/trajectory",
  component: TrajectoryPage,
});

const observabilityOverviewRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/observability/overview",
  component: TrajectoryPage,
});

const agentRoleConsoleRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/agent/roles",
  component: AgentRoleConsolePage,
});

const routeTree = rootRoute.addChildren([
  indexRoute,
  threadRoute,
  reviewRoute,
  trajectoryRoute,
  observabilityOverviewRoute,
  agentRoleConsoleRoute,
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

  if (!principal) {
    return <AuthBootstrapPage />;
  }

  return <RouterProvider router={router} context={{ isAuthenticated: true }} />;
}
