import type { FocusAgentBranchActionProposal } from "@focus-agent/web-sdk";

import {
	branchActionStatusText,
	branchActionTitle,
} from "./message-list-helpers";
import { normalizeText } from "./message-transcript";

export function BranchActionCard({
	action,
	isChineseUi,
	isReadOnly,
	onExecute,
	onDismiss,
	errorMessage,
	isBusy,
}: {
	action: FocusAgentBranchActionProposal;
	isChineseUi: boolean;
	isReadOnly: boolean;
	errorMessage?: string;
	isBusy?: boolean;
	onExecute?: (action: FocusAgentBranchActionProposal) => void;
	onDismiss?: (action: FocusAgentBranchActionProposal) => void;
}) {
	const pending = action.status === "pending";
	const disabled = isReadOnly || Boolean(isBusy);
	const branchName =
		normalizeText(action.suggested_branch_name) ||
		(isChineseUi ? "新分支" : "New branch");
	const failureMessage =
		normalizeText(errorMessage) || normalizeText(action.error);
	const isAiSuggested =
		action.source === "branch_decision" || Boolean(action.source_decision_id);
	const confidence =
		typeof action.confidence === "number"
			? `${Math.round(action.confidence * 100)}%`
			: "";
	return (
		<div className="fa-message-row is-assistant assistant">
			<div className="fa-message-stack">
				<div className="fa-message-head">
					<div className="fa-message-role fa-message-meta">
						{isChineseUi ? "分支操作" : "Branch action"}
					</div>
				</div>
				<div
					className={`fa-message-bubble is-assistant fa-branch-action-card is-${action.status}`}
				>
					<div className="fa-branch-action-card-header">
						<div>
							<div className="fa-branch-action-card-title">
								{branchActionTitle(action, isChineseUi)}
							</div>
							<div className="fa-branch-action-card-meta">
								{branchActionStatusText(action, isChineseUi)}
							</div>
						</div>
						<div className="fa-branch-action-card-badge-stack">
							{isAiSuggested ? (
								<span className="fa-branch-action-card-badge is-ai">
									{isChineseUi ? "AI 建议" : "AI"}
									{confidence ? ` · ${confidence}` : ""}
								</span>
							) : null}
							<span className="fa-branch-action-card-badge">
								{action.branch_role}
							</span>
						</div>
					</div>
					<div className="fa-branch-action-card-body">
						<div>
							<span>{isChineseUi ? "目标" : "Target"}</span>
							<strong>{branchName}</strong>
						</div>
						<div>
							<span>{isChineseUi ? "父分支" : "Parent"}</span>
							<code>{action.target_parent_thread_id}</code>
						</div>
						{failureMessage ? (
							<div className="is-danger">
								<span>{isChineseUi ? "错误" : "Error"}</span>
								<strong>{failureMessage}</strong>
							</div>
						) : null}
						{action.source_decision_id ? (
							<div>
								<span>{isChineseUi ? "依据" : "Evidence"}</span>
								<a href={`#branch-decision-${action.source_decision_id}`}>
									{isChineseUi ? "查看 AI 决策" : "View decision"}
								</a>
							</div>
						) : null}
					</div>
					{pending ? (
						<div className="fa-branch-action-card-actions">
							<button
								className="fa-chat-toolbar-button is-primary"
								disabled={disabled}
								onClick={() => onExecute?.(action)}
								type="button"
							>
								{isBusy
									? isChineseUi
										? "处理中..."
										: "Working..."
									: isChineseUi
										? "确认切换"
										: "Confirm"}
							</button>
							<button
								className="fa-chat-toolbar-button"
								disabled={disabled}
								onClick={() => onDismiss?.(action)}
								type="button"
							>
								{isChineseUi ? "取消" : "Dismiss"}
							</button>
						</div>
					) : null}
				</div>
			</div>
		</div>
	);
}
