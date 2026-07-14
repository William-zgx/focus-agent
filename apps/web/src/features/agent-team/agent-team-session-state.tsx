import { Link } from "@tanstack/react-router";

import { EmptyState, Surface } from "@/shared/ui/primitives";

import {
	errorMessage,
	normalizeSessionView,
} from "./agent-team-workbench-utils";
import type { AgentTeamSession, AgentTeamSessionView } from "./types";

export function AgentTeamSessionState({
	data,
	error,
	isChineseUi,
	isLoading,
}: {
	data: AgentTeamSession | AgentTeamSessionView | undefined;
	error: Error | null;
	isChineseUi: boolean;
	isLoading: boolean;
}) {
	if (isLoading) {
		return (
			<div className="fa-route-state">
				<Surface className="fa-route-state-card" tone="panel">
					<p className="fa-route-state-title">
						{isChineseUi ? "正在加载 Agent Team..." : "Loading Agent Team..."}
					</p>
				</Surface>
			</div>
		);
	}

	if (!error && normalizeSessionView(data)) return null;
	return (
		<div className="fa-route-state">
			<EmptyState
				action={
					<Link className="fa-route-state-link" to="/agent-team">
						{isChineseUi ? "创建新的 Session" : "Create a new session"}
					</Link>
				}
				className="fa-route-state-card"
				description={errorMessage(
					error,
					isChineseUi ? "返回的数据为空。" : "The response was empty.",
				)}
				title={
					isChineseUi
						? "无法加载 Agent Team Session"
						: "Unable to load Agent Team session"
				}
			/>
		</div>
	);
}
