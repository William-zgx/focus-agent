import { useEffect, useState } from "react";

import type {
	AdminNavTarget,
	AgentTeamNavTarget,
	ChatNavTarget,
} from "@/app/shell/app-shell-config";
import type { ShellRouteState } from "@/app/shell/hooks/use-shell-route-state";

type AgentWorkbenchModule =
	| "diagnostics"
	| "governance"
	| "productivity"
	| "team";

export function useShellNavTargets({
	conversationId,
	isAdminRoute,
	isAgentGovernanceRoute,
	isAgentTeamRoute,
	isChatRoute,
	isObservabilityRoute,
	isProductivityRoute,
	pathname,
	rootThreadSearch,
	sessionId,
	threadId,
	userId,
}: Pick<
	ShellRouteState,
	| "conversationId"
	| "isAdminRoute"
	| "isAgentGovernanceRoute"
	| "isAgentTeamRoute"
	| "isChatRoute"
	| "isObservabilityRoute"
	| "isProductivityRoute"
	| "pathname"
	| "rootThreadSearch"
	| "sessionId"
	| "threadId"
	| "userId"
>) {
	const [lastChatTarget, setLastChatTarget] = useState<ChatNavTarget | null>(
		null,
	);
	const [lastAgentTeamTarget, setLastAgentTeamTarget] =
		useState<AgentTeamNavTarget | null>(null);
	const [lastAdminTarget, setLastAdminTarget] = useState<AdminNavTarget | null>(
		null,
	);

	useEffect(() => {
		if (!conversationId || !threadId) return;
		setLastChatTarget((current) =>
			current?.conversationId === conversationId &&
			current.threadId === threadId
				? current
				: { conversationId, threadId },
		);
	}, [conversationId, threadId]);

	useEffect(() => {
		if (!isAgentTeamRoute) return;
		const nextTarget: AgentTeamNavTarget = {
			rootThreadId: rootThreadSearch || undefined,
			sessionId: sessionId || undefined,
		};
		setLastAgentTeamTarget((current) =>
			current &&
			current.rootThreadId === nextTarget.rootThreadId &&
			current.sessionId === nextTarget.sessionId
				? current
				: nextTarget,
		);
	}, [isAgentTeamRoute, rootThreadSearch, sessionId]);

	useEffect(() => {
		if (!isAdminRoute) return;
		const nextTarget: AdminNavTarget = pathname.includes("/admin/audit-events")
			? { page: "audit" }
			: userId
				? { page: "user", userId }
				: { page: "users" };
		setLastAdminTarget((current) => {
			if (!current || current.page !== nextTarget.page) return nextTarget;
			if (current.page === "user" && nextTarget.page === "user") {
				return current.userId === nextTarget.userId ? current : nextTarget;
			}
			return current;
		});
	}, [isAdminRoute, pathname, userId]);

	const activeAgentWorkbenchModule: AgentWorkbenchModule = isAgentTeamRoute
		? "team"
		: isAgentGovernanceRoute
			? "governance"
			: isObservabilityRoute
				? "diagnostics"
				: isProductivityRoute
					? "productivity"
					: "team";
	const chatNavTarget =
		conversationId && threadId ? { conversationId, threadId } : lastChatTarget;
	const agentTeamRootThreadId =
		isChatRoute && conversationId
			? conversationId
			: lastAgentTeamTarget?.rootThreadId ||
				lastChatTarget?.conversationId ||
				"";
	const adminNavTarget = lastAdminTarget ?? { page: "users" as const };

	return {
		activeAgentWorkbenchModule,
		adminNavTarget,
		agentTeamRootThreadId,
		chatNavTarget,
		lastAgentTeamTarget,
	};
}
