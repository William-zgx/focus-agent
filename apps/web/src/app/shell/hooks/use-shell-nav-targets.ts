import { useEffect, useState } from "react";

import type {
	AgentTeamNavTarget,
	ChatNavTarget,
} from "@/app/shell/app-shell-config";
import type { ShellRouteState } from "@/app/shell/hooks/use-shell-route-state";

type AgentWorkbenchModule =
	| "diagnostics"
	| "governance"
	| "memory"
	| "productivity"
	| "team";

export function useShellNavTargets({
	conversationId,
	isAgentGovernanceRoute,
	isAgentMemoryRoute,
	isAgentTeamRoute,
	isChatRoute,
	isObservabilityRoute,
	isProductivityRoute,
	rootThreadSearch,
	sessionId,
	threadId,
}: Pick<
	ShellRouteState,
	| "conversationId"
	| "isAgentGovernanceRoute"
	| "isAgentMemoryRoute"
	| "isAgentTeamRoute"
	| "isChatRoute"
	| "isObservabilityRoute"
	| "isProductivityRoute"
	| "rootThreadSearch"
	| "sessionId"
	| "threadId"
>) {
	const [lastChatTarget, setLastChatTarget] = useState<ChatNavTarget | null>(
		null,
	);
	const [lastAgentTeamTarget, setLastAgentTeamTarget] =
		useState<AgentTeamNavTarget | null>(null);

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

	const activeAgentWorkbenchModule: AgentWorkbenchModule = isAgentTeamRoute
		? "team"
		: isAgentMemoryRoute
			? "memory"
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

	return {
		activeAgentWorkbenchModule,
		agentTeamRootThreadId,
		chatNavTarget,
		lastAgentTeamTarget,
	};
}
