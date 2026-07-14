export const AGENT_TEAM_TAB_IDS = [
	"mission",
	"tasks",
	"approvals",
	"evidence",
] as const;

export type AgentTeamTabId = (typeof AGENT_TEAM_TAB_IDS)[number];

export function agentTeamTabFromPathname(pathname: string): AgentTeamTabId {
	if (pathname.endsWith("/tasks")) return "tasks";
	if (pathname.endsWith("/approvals")) return "approvals";
	if (pathname.endsWith("/evidence")) return "evidence";
	return "mission";
}
