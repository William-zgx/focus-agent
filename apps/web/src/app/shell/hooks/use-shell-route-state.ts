import { useRouterState } from "@tanstack/react-router";

import {
	isProductivityPath,
	resolveShellMode,
} from "@/app/shell/app-shell-config";

export function useShellRouteState() {
	const routeState = useRouterState({
		select: (state) => {
			const lastMatch = state.matches[state.matches.length - 1];
			const routeParams = (lastMatch?.params ?? {}) as Partial<
				Record<"conversationId" | "threadId" | "userId", string>
			>;

			return {
				conversationId: String(routeParams.conversationId ?? ""),
				threadId: String(routeParams.threadId ?? ""),
				isReviewRoute: state.location.pathname.endsWith("/review"),
				pathname: state.location.pathname,
				userId: String(routeParams.userId ?? ""),
			};
		},
	});
	const shellMode = resolveShellMode(routeState.pathname);
	const isChatRoute =
		routeState.pathname === "/" || routeState.pathname.startsWith("/c/");
	const isObservabilityRoute =
		routeState.pathname === "/observability/overview" ||
		routeState.pathname === "/observability/trajectory";
	const isAgentMemoryRoute = routeState.pathname === "/agent/memory";
	const isProductivityRoute = isProductivityPath(routeState.pathname);
	const isAdminRoute =
		routeState.pathname === "/admin/users" ||
		routeState.pathname.startsWith("/admin/users/") ||
		routeState.pathname === "/admin/audit-events" ||
		routeState.pathname === "/admin/config";

	return {
		...routeState,
		shellMode,
		isChatShell: shellMode === "chat",
		isAgentWorkbenchShell: shellMode === "agent-workbench",
		isAdminShell: shellMode === "admin",
		isWorkspaceShell: shellMode === "agent-workbench" || shellMode === "admin",
		isChatRoute,
		isObservabilityRoute,
		isAgentMemoryRoute,
		isProductivityRoute,
		isAdminRoute,
	};
}

export type ShellRouteState = ReturnType<typeof useShellRouteState>;
