import { useRouterState } from "@tanstack/react-router";

import { useShellUi } from "@/app/shell/shell-ui-context";
import { AgentTeamTabShell } from "@/features/agent-team/agent-team-tab-shell";
import { agentTeamTabFromPathname } from "@/features/agent-team/agent-team-tab-types";
import { useLastRouteParam } from "@/pages/use-last-route-param";

import "@/shared/styles/modules/agent-team.css";

export function AgentTeamWorkbenchPage() {
	const sessionId = useLastRouteParam("sessionId");
	const pathname = useRouterState({
		select: (state) => state.location.pathname,
	});
	const { isChineseUi } = useShellUi();

	return (
		<AgentTeamTabShell
			activeTab={agentTeamTabFromPathname(pathname)}
			isChineseUi={isChineseUi}
			sessionId={sessionId}
		/>
	);
}
