import {
	Outlet,
	RouterProvider,
	createRootRoute,
	createRoute,
	createRouter,
	useNavigate,
	useSearch,
	useRouterState,
} from "@tanstack/react-router";
import {
	Capacitor,
	type PluginListenerHandle,
	registerPlugin,
} from "@capacitor/core";
import { Suspense, type ReactNode, lazy, useEffect, useMemo } from "react";

import { ShellUiProvider } from "@/app/shell/shell-ui-context";
import { AppShell } from "@/app/shell/app-shell";
import { androidAppUrlToInternalRoute } from "@/android-local-runtime/helpers";
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
import { HomePage } from "@/pages/home/home-page";
import { NotFoundPage } from "@/pages/not-found/not-found-page";
import { normalizeAuthReturnTo } from "@/pages/auth/return-to";
import { appEnv } from "@/shared/config/env";
import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";
import { Surface } from "@/shared/ui/primitives";

interface CapacitorAppPlugin {
	addListener(
		eventName: "appUrlOpen",
		listener: (event: { url: string }) => void,
	): Promise<PluginListenerHandle>;
	getLaunchUrl(): Promise<{ url?: string }>;
}

const capacitorApp = registerPlugin<CapacitorAppPlugin>("App");

function RouteStateCard({ children }: { children: ReactNode }) {
	return (
		<Surface className="fa-route-state-card" tone="panel">
			{children}
		</Surface>
	);
}

export function localRuntimeLegacyRouteTarget(
	useLocalRuntime: boolean,
	pathname: string,
): "/" | "/admin/config" | null {
	if (!useLocalRuntime) return null;
	if (
		pathname === "/auth" ||
		pathname.startsWith("/auth/") ||
		pathname === "/account" ||
		pathname.startsWith("/account/")
	) {
		return "/";
	}
	if (
		pathname === "/admin/users" ||
		pathname.startsWith("/admin/users/") ||
		pathname === "/admin/audit-events"
	) {
		return "/admin/config";
	}
	return null;
}

export function shouldRedirectToSignIn(
	useLocalRuntime: boolean,
	isAuthRoute: boolean,
	ready: boolean,
	hasPrincipal: boolean,
): boolean {
	return !useLocalRuntime && !isAuthRoute && ready && !hasPrincipal;
}

function useAuthRedirect() {
	const navigate = useNavigate();
	const { principal, ready } = useFocusAgent();
	const pathname = useRouterState({
		select: (state) => state.location.pathname,
	});
	const search = useRouterState({
		select: (state) => state.location.searchStr,
	});
	const isAuthRoute = pathname === "/auth" || pathname.startsWith("/auth/");
	const localRuntimeRedirectTarget = localRuntimeLegacyRouteTarget(
		appEnv.useLocalRuntime,
		pathname,
	);
	const returnTo = isAuthRoute
		? "/"
		: normalizeAuthReturnTo(`${pathname}${search}`);

	useEffect(() => {
		if (localRuntimeRedirectTarget) {
			void navigate({
				to: localRuntimeRedirectTarget,
				replace: true,
			});
			return;
		}
		if (
			!shouldRedirectToSignIn(
				appEnv.useLocalRuntime,
				isAuthRoute,
				ready,
				Boolean(principal),
			)
		) {
			return;
		}
		void navigate({
			to: "/auth/login",
			search: { return_to: returnTo },
			replace: true,
		});
	}, [
		isAuthRoute,
		localRuntimeRedirectTarget,
		navigate,
		principal,
		ready,
		returnTo,
	]);

	return {
		hasPrincipal: Boolean(principal),
		isAuthRoute,
		localRuntimeRedirectTarget,
		ready,
	};
}

// The only auth gate: non-auth routes render only once the session is ready
// and a principal exists; auth routes always render.
function AuthGate({
	children,
}: {
	children: (isAuthRoute: boolean) => ReactNode;
}) {
	const { hasPrincipal, isAuthRoute, localRuntimeRedirectTarget, ready } =
		useAuthRedirect();
	const isChineseBrowser = navigator?.language.toLowerCase().startsWith("zh");

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

	if (localRuntimeRedirectTarget) {
		return (
			<div className="fa-route-state">
				<RouteStateCard>
					{isChineseBrowser
						? "正在打开设备本机工作区..."
						: "Opening the device-local workspace..."}
				</RouteStateCard>
			</div>
		);
	}

	if (!isAuthRoute && !hasPrincipal) {
		return (
			<div className="fa-route-state">
				<RouteStateCard>
					{appEnv.useLocalRuntime
						? isChineseBrowser
							? "无法建立设备本机会话。"
							: "Unable to establish the device-local session."
						: isChineseBrowser
							? "正在跳转到登录页..."
							: "Redirecting to sign in..."}
				</RouteStateCard>
			</div>
		);
	}

	return <>{children(isAuthRoute)}</>;
}

function RootLayout() {
	return (
		<AuthGate>
			{(isAuthRoute) =>
				isAuthRoute ? (
					<Outlet />
				) : (
					<AppShell>
						<Outlet />
					</AppShell>
				)
			}
		</AuthGate>
	);
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
		if (appEnv.useLocalRuntime) {
			void navigate({
				to: "/",
				replace: true,
			});
			return;
		}
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
	component: () => <HomePage />,
});

const threadRoute = createRoute({
	getParentRoute: () => rootRoute,
	path: "/c/$conversationId/t/$threadId",
	component: () => <ThreadPage />,
});

const reviewRoute = createRoute({
	getParentRoute: () => rootRoute,
	path: "/c/$conversationId/t/$threadId/review",
	component: () => <ThreadPage />,
});

const trajectoryRoute = createRoute({
	getParentRoute: () => rootRoute,
	path: "/observability/trajectory",
	component: () => <TrajectoryPage />,
});

const observabilityOverviewRoute = createRoute({
	getParentRoute: () => rootRoute,
	path: "/observability/overview",
	component: () => <TrajectoryPage />,
});

const agentRoleConsoleRoute = createRoute({
	getParentRoute: () => rootRoute,
	path: "/agent/roles",
	component: () => <AgentRoleConsolePage />,
});

const agentGovernanceConsoleRoute = createRoute({
	getParentRoute: () => rootRoute,
	path: "/agent/governance",
	component: () => <AgentRoleConsolePage />,
});

const agentMemoryRoute = createRoute({
	getParentRoute: () => rootRoute,
	path: "/agent/memory",
	component: () => <MemoryConsolePage />,
});

const adminUsersRoute = createRoute({
	getParentRoute: () => rootRoute,
	path: "/admin/users",
	component: () => <AdminUsersPage />,
});

const adminUserDetailRoute = createRoute({
	getParentRoute: () => rootRoute,
	path: "/admin/users/$userId",
	component: () => <AdminUserDetailPage />,
});

const adminAuditEventsRoute = createRoute({
	getParentRoute: () => rootRoute,
	path: "/admin/audit-events",
	component: () => <AdminAuditEventsPage />,
});

const adminConfigRoute = createRoute({
	getParentRoute: () => rootRoute,
	path: "/admin/config",
	component: () => <AdminConfigPage />,
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
	component: () => <AccountProfilePage />,
});

const accountSecurityRoute = createRoute({
	getParentRoute: () => rootRoute,
	path: "/account/security",
	component: () => <AccountSecurityPage />,
});

const accountSessionsRoute = createRoute({
	getParentRoute: () => rootRoute,
	path: "/account/sessions",
	component: () => <AccountSessionsPage />,
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
					component: () => lazyRoute(<LazyAgentTeamWorkbenchPage />),
				});
				const agentTeamSessionRoute = createRoute({
					getParentRoute: () => rootRoute,
					path: "/agent-team/$sessionId",
					component: () => lazyRoute(<LazyAgentTeamWorkbenchPage />),
				});
				const agentTeamTasksRoute = createRoute({
					getParentRoute: () => rootRoute,
					path: "/agent-team/$sessionId/tasks",
					component: () => lazyRoute(<LazyAgentTeamWorkbenchPage />),
				});
				const agentTeamApprovalsRoute = createRoute({
					getParentRoute: () => rootRoute,
					path: "/agent-team/$sessionId/approvals",
					component: () => lazyRoute(<LazyAgentTeamWorkbenchPage />),
				});
				const agentTeamEvidenceRoute = createRoute({
					getParentRoute: () => rootRoute,
					path: "/agent-team/$sessionId/evidence",
					component: () => lazyRoute(<LazyAgentTeamWorkbenchPage />),
				});
				return [
					agentTeamRoute,
					agentTeamSessionRoute,
					agentTeamTasksRoute,
					agentTeamApprovalsRoute,
					agentTeamEvidenceRoute,
				];
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
					component: () => lazyRoute(<LazyProductivityPage mode="notes" />),
				});
				const productivityTasksRoute = createRoute({
					getParentRoute: () => rootRoute,
					path: "/productivity/tasks",
					component: () => lazyRoute(<LazyProductivityPage mode="tasks" />),
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
	defaultPreload: "intent",
});

declare module "@tanstack/react-router" {
	interface Register {
		router: typeof router;
	}
}

export function AppRouter() {
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

	useEffect(() => {
		if (!appEnv.isAndroidTarget || !Capacitor.isNativePlatform()) return;
		let listenerHandle: PluginListenerHandle | undefined;
		let cancelled = false;
		const openInternalRoute = ({ url }: { url?: string }) => {
			const route = androidAppUrlToInternalRoute(url);
			if (route) {
				router.history.push(route);
			}
		};

		void capacitorApp
			.addListener("appUrlOpen", openInternalRoute)
			.then((handle) => {
				if (cancelled) {
					void handle.remove();
					return;
				}
				listenerHandle = handle;
				void capacitorApp
					.getLaunchUrl()
					.then(openInternalRoute)
					.catch(console.error);
			})
			.catch(console.error);

		return () => {
			cancelled = true;
			void listenerHandle?.remove();
		};
	}, []);

	return (
		<ShellUiProvider value={fallbackShellUiContext}>
			<RouterProvider router={router} />
		</ShellUiProvider>
	);
}
