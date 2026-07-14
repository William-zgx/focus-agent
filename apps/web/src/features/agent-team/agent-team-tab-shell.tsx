import { Link } from "@tanstack/react-router";
import { type ComponentType, lazy, Suspense } from "react";

import type { AgentTeamTabId } from "./agent-team-tab-types";

const LazyAgentTeamMissionTab = lazy(() =>
	import("./agent-team-workbench").then((module) => ({
		default: module.AgentTeamWorkbench,
	})),
);
const LazyAgentTeamTasksTab = lazy(() =>
	import("./agent-team-tasks-tab").then((module) => ({
		default: module.AgentTeamTasksTab,
	})),
);
const LazyAgentTeamApprovalsTab = lazy(() =>
	import("./agent-team-approvals-tab").then((module) => ({
		default: module.AgentTeamApprovalsTab,
	})),
);
const LazyAgentTeamEvidenceTab = lazy(() =>
	import("./agent-team-evidence-tab").then((module) => ({
		default: module.AgentTeamEvidenceTab,
	})),
);

type AgentTeamSessionTabProps = {
	sessionId: string | null;
};

type AgentTeamTabDefinition = {
	id: AgentTeamTabId;
	labelEn: string;
	labelZh: string;
	Component: ComponentType<AgentTeamSessionTabProps>;
};

const AGENT_TEAM_TABS: AgentTeamTabDefinition[] = [
	{
		id: "mission",
		labelEn: "Mission",
		labelZh: "任务总览",
		Component: LazyAgentTeamMissionTab,
	},
	{
		id: "tasks",
		labelEn: "Tasks",
		labelZh: "任务",
		Component: LazyAgentTeamTasksTab,
	},
	{
		id: "approvals",
		labelEn: "Approvals",
		labelZh: "审批",
		Component: LazyAgentTeamApprovalsTab,
	},
	{
		id: "evidence",
		labelEn: "Evidence",
		labelZh: "证据",
		Component: LazyAgentTeamEvidenceTab,
	},
];

export function AgentTeamTabShell({
	activeTab,
	isChineseUi,
	sessionId,
}: {
	activeTab: AgentTeamTabId;
	isChineseUi: boolean;
	sessionId: string | null;
}) {
	const activeDefinition =
		AGENT_TEAM_TABS.find((tab) => tab.id === activeTab) ?? AGENT_TEAM_TABS[0];
	const ActiveTab = activeDefinition.Component;

	return (
		<div className="fa-agent-team-tab-shell">
			{sessionId ? (
				<nav
					aria-label={isChineseUi ? "Agent Team 页面" : "Agent Team pages"}
					className="fa-agent-team-route-tabs"
				>
					{AGENT_TEAM_TABS.map((tab) => {
						const label = isChineseUi ? tab.labelZh : tab.labelEn;
						return (
							<AgentTeamTabLink
								activeTab={activeTab}
								key={tab.id}
								label={label}
								sessionId={sessionId}
								tab={tab.id}
							/>
						);
					})}
				</nav>
			) : null}
			<Suspense
				fallback={
					<div className="fa-route-state">
						<p>
							{isChineseUi ? "正在加载 Agent Team..." : "Loading Agent Team..."}
						</p>
					</div>
				}
			>
				<ActiveTab sessionId={sessionId} />
			</Suspense>
		</div>
	);
}

function AgentTeamTabLink({
	activeTab,
	label,
	sessionId,
	tab,
}: {
	activeTab: AgentTeamTabId;
	label: string;
	sessionId: string;
	tab: AgentTeamTabId;
}) {
	const className = `fa-agent-team-route-tab ${
		tab === activeTab ? "is-active" : ""
	}`.trim();
	const content = label;

	if (tab === "mission") {
		return (
			<Link
				aria-current={tab === activeTab ? "page" : undefined}
				className={className}
				params={{ sessionId }}
				to="/agent-team/$sessionId"
			>
				{content}
			</Link>
		);
	}

	if (tab === "tasks") {
		return (
			<Link
				aria-current={tab === activeTab ? "page" : undefined}
				className={className}
				params={{ sessionId }}
				to="/agent-team/$sessionId/tasks"
			>
				{content}
			</Link>
		);
	}

	if (tab === "approvals") {
		return (
			<Link
				aria-current={tab === activeTab ? "page" : undefined}
				className={className}
				params={{ sessionId }}
				to="/agent-team/$sessionId/approvals"
			>
				{content}
			</Link>
		);
	}

	return (
		<Link
			aria-current={tab === activeTab ? "page" : undefined}
			className={className}
			params={{ sessionId }}
			to="/agent-team/$sessionId/evidence"
		>
			{content}
		</Link>
	);
}
