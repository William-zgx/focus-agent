import { Link } from "@tanstack/react-router";

import { useShellUi } from "@/app/shell/shell-ui-context";
import { tooltipProps } from "@/shared/ui/tooltip";

import {
	errorMessage,
	isUnsupportedLocalRuntimeError,
	localRuntimeAgentTeamUnavailableMessage,
	statusLabel,
	titleFromGoal,
} from "./agent-team-workbench-utils";
import { EmptyList } from "./agent-team-workbench-shared";
import { useAgentTeamSessions } from "./use-agent-team";

export function RecentSessionsPanel({
	rootThreadId,
}: {
	rootThreadId: string;
}) {
	const { isChineseUi } = useShellUi();
	const recentSessions = useAgentTeamSessions({
		limit: 5,
		root_thread_id: rootThreadId.trim() || undefined,
	});
	const sessions = recentSessions.data?.items ?? [];

	return (
		<section className="fa-agent-team-panel fa-agent-team-recent-panel">
			<div className="fa-agent-team-panel-header">
				<div>
					<span>{isChineseUi ? "最近" : "Recent"}</span>
					<strong>{isChineseUi ? "最近 Mission" : "Recent missions"}</strong>
				</div>
			</div>
			{recentSessions.isLoading ? (
				<EmptyList>
					{isChineseUi
						? "正在加载最近 Mission..."
						: "Loading recent missions..."}
				</EmptyList>
			) : recentSessions.error ? (
				<div className="fa-inline-notice is-danger">
					{isUnsupportedLocalRuntimeError(recentSessions.error)
						? localRuntimeAgentTeamUnavailableMessage(isChineseUi)
						: errorMessage(
								recentSessions.error,
								isChineseUi
									? "最近 Mission 加载失败。"
									: "Failed to load recent missions.",
							)}
				</div>
			) : sessions.length ? (
				<div className="fa-agent-team-recent-list">
					{sessions.map((session) => (
						<Link
							className="fa-agent-team-recent-item"
							key={session.session_id}
							params={{ sessionId: session.session_id }}
							to="/agent-team/$sessionId"
							{...tooltipProps(session.goal)}
						>
							<span>{statusLabel(session.status, isChineseUi)}</span>
							<strong>
								{session.title
									? titleFromGoal(session.title)
									: session.session_id}
							</strong>
						</Link>
					))}
				</div>
			) : (
				<EmptyList>
					{rootThreadId.trim()
						? isChineseUi
							? "当前来源对话还没有 Mission。"
							: "No mission exists for this source conversation yet."
						: isChineseUi
							? "还没有 Mission。创建后会出现在这里。"
							: "No mission yet. New missions will appear here."}
				</EmptyList>
			)}
		</section>
	);
}
