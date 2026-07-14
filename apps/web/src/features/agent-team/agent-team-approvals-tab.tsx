import { useShellUi } from "@/app/shell/shell-ui-context";

import { AgentTeamSessionState } from "./agent-team-session-state";
import {
	errorMessage,
	normalizeSessionView,
} from "./agent-team-workbench-utils";
import {
	useAgentTeamSession,
	useAgentTeamToolApprovals,
	useDecideAgentTeamToolApproval,
} from "./use-agent-team";

export function AgentTeamApprovalsTab({
	sessionId,
}: {
	sessionId: string | null;
}) {
	const { isChineseUi } = useShellUi();
	const sessionQuery = useAgentTeamSession(sessionId);
	const approvalsQuery = useAgentTeamToolApprovals(sessionId);
	const decideToolApproval = useDecideAgentTeamToolApproval(sessionId);
	const state = (
		<AgentTeamSessionState
			data={sessionQuery.data}
			error={sessionQuery.error}
			isChineseUi={isChineseUi}
			isLoading={sessionQuery.isLoading}
		/>
	);
	const view = normalizeSessionView(sessionQuery.data);

	if (!sessionId || sessionQuery.isLoading || sessionQuery.error || !view) {
		return state;
	}

	const approvals =
		approvalsQuery.data?.items ?? view.pending_tool_approvals ?? [];

	return (
		<div className="fa-agent-team-layout fa-agent-team-tab-content">
			<section className="fa-agent-team-tool-approvals">
				<div>
					<span>{isChineseUi ? "待审批工具" : "Pending tools"}</span>
					<strong>
						{isChineseUi
							? `${approvals.length} 个请求`
							: `${approvals.length} request${approvals.length === 1 ? "" : "s"}`}
					</strong>
				</div>
				{approvalsQuery.error ? (
					<div className="fa-inline-notice is-warning">
						{errorMessage(
							approvalsQuery.error,
							isChineseUi ? "审批列表暂不可用。" : "Approvals are unavailable.",
						)}
					</div>
				) : null}
				{approvals.length ? (
					<div className="fa-agent-team-tool-approval-list">
						{approvals.map((approval) => {
							const busy =
								decideToolApproval.isPending &&
								decideToolApproval.variables?.requestId === approval.request_id;
							return (
								<article
									className="fa-agent-team-tool-approval"
									key={approval.request_id}
								>
									<div>
										<span>{approval.risk_level || "low"}</span>
										<strong>{approval.tool_name || approval.request_id}</strong>
										<code>{approval.request_id}</code>
									</div>
									<div className="fa-agent-team-tool-approval-actions">
										<button
											disabled={busy}
											onClick={() =>
												decideToolApproval.mutate({
													requestId: approval.request_id,
													approved: true,
												})
											}
											type="button"
										>
											{busy
												? isChineseUi
													? "提交中"
													: "Saving"
												: isChineseUi
													? "批准"
													: "Approve"}
										</button>
										<button
											className="is-danger"
											disabled={busy}
											onClick={() =>
												decideToolApproval.mutate({
													requestId: approval.request_id,
													approved: false,
												})
											}
											type="button"
										>
											{isChineseUi ? "拒绝" : "Reject"}
										</button>
									</div>
								</article>
							);
						})}
					</div>
				) : (
					<p className="fa-agent-team-empty">
						{isChineseUi
							? "当前没有需要人工确认的工具请求。"
							: "There are no tool requests awaiting review."}
					</p>
				)}
				{decideToolApproval.error ? (
					<div className="fa-inline-notice is-danger">
						{errorMessage(
							decideToolApproval.error,
							isChineseUi ? "工具审批提交失败。" : "Failed to submit approval.",
						)}
					</div>
				) : null}
			</section>
		</div>
	);
}
