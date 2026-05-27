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
import { Suspense, type ReactNode, lazy, useEffect, useMemo } from "react";

import { ShellUiProvider, useShellUi } from "@/app/shell/shell-ui-context";
import { AppShell } from "@/app/shell/app-shell";
import { useConversations } from "@/features/conversations/use-conversations";
import { AgentRoleConsolePage } from "@/pages/agents/agent-role-console-page";
import { AdminAuditEventsPage } from "@/pages/admin/admin-audit-events-page";
import { AdminConfigPage } from "@/pages/admin/admin-config-page";
import { AdminUserDetailPage } from "@/pages/admin/admin-user-detail-page";
import { AdminUsersPage } from "@/pages/admin/admin-users-page";
import { AccountProfilePage } from "@/pages/account/profile-page";
import { AccountSecurityPage } from "@/pages/account/security-page";
import { AccountSessionsPage } from "@/pages/account/sessions-page";
import { LoginPage } from "@/pages/auth/login-page";
import { MemoryConsolePage } from "@/pages/memory/memory-console-page";
import { RegisterPage } from "@/pages/auth/register-page";
import { TrajectoryPage } from "@/pages/observability/trajectory-page";
import { ThreadPage } from "@/pages/thread/thread-page";
import { normalizeAuthReturnTo } from "@/pages/auth/return-to";
import { appEnv } from "@/shared/config/env";
import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";
import { EmptyState, Surface, Toast } from "@/shared/ui/primitives";

function RouteStateCard({ children }: { children: ReactNode }) {
	return (
		<Surface className="fa-route-state-card" tone="panel">
			{children}
		</Surface>
	);
}

function RootLayout() {
	const navigate = useNavigate();
	const { principal, ready } = useFocusAgent();
	const pathname = useRouterState({
		select: (state) => state.location.pathname,
	});
	const search = useRouterState({
		select: (state) => state.location.searchStr,
	});
	const isAuthRoute = pathname === "/auth" || pathname.startsWith("/auth/");
	const returnTo = isAuthRoute
		? "/"
		: normalizeAuthReturnTo(`${pathname}${search}`);
	const isChineseBrowser = navigator?.language.toLowerCase().startsWith("zh");

	useEffect(() => {
		if (isAuthRoute || !ready || principal) return;
		void navigate({
			to: "/auth/login",
			search: { return_to: returnTo },
			replace: true,
		});
	}, [isAuthRoute, navigate, principal, ready, returnTo]);

	if (!isAuthRoute && !ready) {
		return (
			<div className="fa-route-state">
				<RouteStateCard>
					{isChineseBrowser
						? "正在准备 Focus Agent 会话..."
						: "Preparing Focus Agent session..."}
				</RouteStateCard>
			</div>
		);
	}

	if (!isAuthRoute && !principal) {
		return (
			<div className="fa-route-state">
				<RouteStateCard>
					{isChineseBrowser
						? "正在跳转到登录页..."
						: "Redirecting to sign in..."}
				</RouteStateCard>
			</div>
		);
	}

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
	const isChineseUi = navigator?.language.toLowerCase().startsWith("zh");

	return (
		<div className="fa-route-state">
			<EmptyState
				action={
					<Link className="fa-route-state-link" to="/">
						{isChineseUi ? "返回首页" : "Go back home"}
					</Link>
				}
				className="fa-route-state-card"
				title={isChineseUi ? "页面不存在" : "Page not found"}
			/>
		</div>
	);
}

function HomePage() {
	const navigate = useNavigate();
	const { isChineseUi } = useShellUi();
	const { data, isLoading } = useConversations();
	const conversations = data?.conversations ?? [];
	const firstActiveConversation =
		conversations.find((item) => !item.is_archived) ?? conversations[0];

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
						<EmptyState
							className="fa-chat-empty"
							title={
								isChineseUi
									? "从这里开始聊天。只要 Agent 产生分支，左侧就会显示出来。"
									: "Start chatting here. Branches appear on the left whenever the agent forks work."
							}
						/>
					</div>
				</div>
			</section>

			<section className="fa-composer-slot">
				<Toast className="fa-inline-notice" tone="info">
					{isChineseUi
						? "在这里发送第一条消息。需要探索另一条路径时，再新建分支。"
						: "Send the first message here. Create a branch only when you want to explore a separate path."}
				</Toast>
			</section>
		</div>
	);
}

function AuthGate({ children }: { children: ReactNode }) {
	const navigate = useNavigate();
	const { principal, ready } = useFocusAgent();
	const pathname = useRouterState({
		select: (state) => state.location.pathname,
	});
	const search = useRouterState({
		select: (state) => state.location.searchStr,
	});
	const isAuthRoute = pathname === "/auth" || pathname.startsWith("/auth/");
	const returnTo = isAuthRoute
		? "/"
		: normalizeAuthReturnTo(`${pathname}${search}`);

	useEffect(() => {
		if (!ready && !isAuthRoute) {
			return;
		}

		if (ready && !principal && !isAuthRoute) {
			void navigate({
				to: "/auth/login",
				search: { return_to: returnTo },
				replace: true,
			});
		}
	}, [isAuthRoute, navigate, principal, ready, returnTo]);

	if (!isAuthRoute && (!ready || !principal)) {
		return (
			<div className="fa-route-state">
				<RouteStateCard>Redirecting to sign in...</RouteStateCard>
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

function lazyRoute(component: ReactNode) {
	return (
		<Suspense
			fallback={
				<div className="fa-route-state">
					<RouteStateCard>Loading...</RouteStateCard>
				</div>
			}
		>
			{component}
		</Suspense>
	);
}

function AuthIndexRedirect() {
	const navigate = useNavigate();
	const search = useSearch({ strict: false });
	const returnTo = useMemo(
		() => normalizeAuthReturnTo((search as { return_to?: unknown }).return_to),
		[search],
	);

	useEffect(() => {
		void navigate({
			to: "/auth/login",
			search: { return_to: returnTo },
			replace: true,
		});
	}, [navigate, returnTo]);

	return (
		<div className="fa-route-state">
			<RouteStateCard>正在进入登录页...</RouteStateCard>
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

const agentMemoryRoute = createRoute({
	getParentRoute: () => rootRoute,
	path: "/agent/memory",
	component: protect(<MemoryConsolePage />),
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

const adminConfigRoute = createRoute({
	getParentRoute: () => rootRoute,
	path: "/admin/config",
	component: protect(<AdminConfigPage />),
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

const observabilityRoutes = appEnv.features.observability
	? [trajectoryRoute, observabilityOverviewRoute]
	: [];

const agentGovernanceRoutes = appEnv.features.agentGovernance
	? [agentRoleConsoleRoute, agentGovernanceConsoleRoute]
	: [];

const agentMemoryRoutes = appEnv.features.agentMemory ? [agentMemoryRoute] : [];

const agentTeamRoutes =
	import.meta.env.VITE_FOCUS_AGENT_ENABLE_AGENT_WORKBENCH === "false" ||
	!appEnv.features.agentTeam
		? []
		: (() => {
				const LazyAgentTeamWorkbenchPage = lazy(() =>
					import("@/pages/agent-team/team-workbench-page").then((module) => ({
						default: module.AgentTeamWorkbenchPage,
					})),
				);
				const agentTeamRoute = createRoute({
					getParentRoute: () => rootRoute,
					path: "/agent-team",
					component: protect(lazyRoute(<LazyAgentTeamWorkbenchPage />)),
				});
				const agentTeamSessionRoute = createRoute({
					getParentRoute: () => rootRoute,
					path: "/agent-team/$sessionId",
					component: protect(lazyRoute(<LazyAgentTeamWorkbenchPage />)),
				});
				return [agentTeamRoute, agentTeamSessionRoute];
			})();

const productivityRoutes =
	import.meta.env.VITE_FOCUS_AGENT_ENABLE_PRODUCTIVITY === "false" ||
	!appEnv.features.productivity
		? []
		: (() => {
				const LazyProductivityPage = lazy(() =>
					import("@/pages/productivity/productivity-page").then((module) => ({
						default: module.ProductivityPage,
					})),
				);
				const productivityNotesRoute = createRoute({
					getParentRoute: () => rootRoute,
					path: "/productivity/notes",
					component: protect(lazyRoute(<LazyProductivityPage mode="notes" />)),
				});
				const productivityTasksRoute = createRoute({
					getParentRoute: () => rootRoute,
					path: "/productivity/tasks",
					component: protect(lazyRoute(<LazyProductivityPage mode="tasks" />)),
				});
				return [productivityNotesRoute, productivityTasksRoute];
			})();

const routeTree = rootRoute.addChildren([
	indexRoute,
	threadRoute,
	reviewRoute,
	...observabilityRoutes,
	...agentGovernanceRoutes,
	...agentMemoryRoutes,
	...agentTeamRoutes,
	...productivityRoutes,
	adminUsersRoute,
	adminUserDetailRoute,
	adminAuditEventsRoute,
	adminConfigRoute,
	authRoute,
	loginRoute,
	registerRoute,
	accountProfileRoute,
	accountSecurityRoute,
	accountSessionsRoute,
]);

const router = createRouter({
	routeTree,
	basepath: appEnv.routerBasePath,
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
	const isChineseBrowser = navigator?.language.toLowerCase().startsWith("zh");
	const pathname =
		typeof window !== "undefined" ? window.location.pathname : "";
	const appPath =
		appEnv.routerBasePath !== "/" && pathname.startsWith(appEnv.routerBasePath)
			? pathname.slice(appEnv.routerBasePath.length) || "/"
			: pathname;
	const isAuthPath = appPath === "/auth" || appPath.startsWith("/auth/");
	const fallbackShellUiContext = useMemo(
		() => ({
			languagePreference: "en" as const,
			themePreference: "system" as const,
			colorPreference: "white" as const,
			setLanguagePreference() {},
			setThemePreference() {},
			setColorPreference() {},
			shellStatus: null,
			setShellStatus() {},
			createBranch: async () => {},
			isCreatingBranch: false,
			mergeProposalGeneration: {},
			markMergeProposalPreparing() {},
			markMergeProposalReady() {},
			markMergeProposalFailed() {},
			isMergeProposalPreparing: () => false,
			getMergeProposalError: () => null,
		}),
		[],
	);

	if (!isAuthPath && !ready) {
		return (
			<div className="fa-route-state">
				<RouteStateCard>
					{isChineseBrowser
						? "正在准备 Focus Agent 会话..."
						: "Preparing Focus Agent session..."}
				</RouteStateCard>
			</div>
		);
	}

	return (
		<ShellUiProvider value={fallbackShellUiContext}>
			<RouterProvider
				router={router}
				context={{ isAuthenticated: Boolean(principal) }}
			/>
		</ShellUiProvider>
	);
}
