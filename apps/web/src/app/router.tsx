import {
  Link,
  Outlet,
  RouterProvider,
  createRootRoute,
  createRoute,
  createRouter,
  useNavigate,
} from "@tanstack/react-router";
import { useEffect } from "react";

import { useShellUi } from "@/app/shell/shell-ui-context";
import { AppShell } from "@/app/shell/app-shell";
import { useConversations } from "@/features/conversations/use-conversations";
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

const routeTree = rootRoute.addChildren([indexRoute, threadRoute, reviewRoute]);

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
  const { ready } = useFocusAgent();
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

  return <RouterProvider router={router} context={{ isAuthenticated: true }} />;
}
