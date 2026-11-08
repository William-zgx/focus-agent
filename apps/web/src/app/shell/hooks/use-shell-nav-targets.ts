import { useEffect, useState } from "react";

import type { ChatNavTarget } from "@/app/shell/app-shell-config";
import type { ShellRouteState } from "@/app/shell/hooks/use-shell-route-state";

type AgentWorkbenchModule =
	"diagnostics" | "governance" | "memory" | "productivity";

export function useShellNavTargets({
	conversationId,
	isAgentGovernanceRoute,
	isAgentMemoryRoute,
	isObservabilityRoute,
	isProductivityRoute,
	threadId,
}: Pick<
	ShellRouteState,
	| "conversationId"
	| "isAgentGovernanceRoute"
	| "isAgentMemoryRoute"
	| "isObservabilityRoute"
	| "isProductivityRoute"
	| "threadId"
>) {
	const [lastChatTarget, setLastChatTarget] = useState<ChatNavTarget | null>(
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

	const activeAgentWorkbenchModule: AgentWorkbenchModule = isAgentMemoryRoute
		? "memory"
		: isAgentGovernanceRoute
			? "governance"
			: isObservabilityRoute
				? "diagnostics"
				: isProductivityRoute
					? "productivity"
					: "diagnostics";
	const chatNavTarget =
		conversationId && threadId ? { conversationId, threadId } : lastChatTarget;

	return {
		activeAgentWorkbenchModule,
		chatNavTarget,
	};
}
