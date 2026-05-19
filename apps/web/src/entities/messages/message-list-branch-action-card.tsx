import type {
	FocusAgentBranchActionProposal,
	FocusAgentBranchDecisionEvent,
} from "@focus-agent/web-sdk";
import { useEffect, useState } from "react";

import {
	branchDecisionAuditOnlyText,
	branchDecisionDiagnosticText,
	branchDecisionSemanticDiagnosticEntries,
	shouldShowBranchDecisionDiagnostic,
} from "@/shared/branch-decision-diagnostics";

import {
	branchActionStatusText,
	branchActionTitle,
} from "./message-list-helpers";
import { normalizeText } from "./message-transcript";

function scorePercent(score: number) {
	return `${Math.round(score * 100)}%`;
}

function branchActionFocusMetric({
	action,
	isChineseUi,
	sourceDecision,
}: {
	action: FocusAgentBranchActionProposal;
	isChineseUi: boolean;
	sourceDecision?: FocusAgentBranchDecisionEvent | null;
}) {
	const semanticEntries = sourceDecision
		? branchDecisionSemanticDiagnosticEntries(sourceDecision)
		: [];
	const relatedness = semanticEntries.find(
		(entry) => entry.key === "semantic_relatedness",
	)?.value;
	if (relatedness) {
		return {
			kind: "relevance",
			label: isChineseUi ? "Focus Score" : "Focus Score",
			shortLabel: `Focus Score ${relatedness}`,
			value: relatedness,
		};
	}
	if (typeof action.confidence === "number") {
		const value = scorePercent(action.confidence);
		return {
			kind: "routing",
			label: isChineseUi ? "路由置信度" : "Routing confidence",
			shortLabel: isChineseUi ? `路由置信度 ${value}` : `Routing ${value}`,
			value,
		};
	}
	return null;
}

export function BranchActionCard({
	action,
	isChineseUi,
	isReadOnly,
	onExecute,
	onContinueCurrent,
	onDismiss,
	sourceDecision,
	errorMessage,
	isBusy,
}: {
	action: FocusAgentBranchActionProposal;
	isChineseUi: boolean;
	isReadOnly: boolean;
	errorMessage?: string;
	isBusy?: boolean;
	sourceDecision?: FocusAgentBranchDecisionEvent | null;
	onExecute?: (action: FocusAgentBranchActionProposal) => void;
	onContinueCurrent?: (action: FocusAgentBranchActionProposal) => void;
	onDismiss?: (action: FocusAgentBranchActionProposal) => void;
}) {
	const pending = action.status === "pending";
	const [isExpanded, setIsExpanded] = useState(pending);
	const disabled = isReadOnly || Boolean(isBusy);
	const branchName =
		normalizeText(action.suggested_branch_name) ||
		(isChineseUi ? "新分支" : "New branch");
	const failureMessage =
		normalizeText(errorMessage) || normalizeText(action.error);
	const isAiSuggested =
		action.source === "branch_decision" || Boolean(action.source_decision_id);
	const routingConfidence =
		typeof action.confidence === "number" ? scorePercent(action.confidence) : "";
	const focusMetric = branchActionFocusMetric({
		action,
		isChineseUi,
		sourceDecision,
	});
	const sourceDecisionStatus = action.source_decision_status ?? null;
	const sourceDecisionDiagnostic = branchDecisionDiagnosticText(action);
	const showSourceDecisionDiagnostic =
		(!sourceDecisionStatus ||
			shouldShowBranchDecisionDiagnostic(sourceDecisionStatus)) &&
		Boolean(sourceDecisionDiagnostic);
	const auditOnly = action.recommendation_user_visible === false;
	const toggleLabel = isExpanded
		? isChineseUi
			? "收起详情"
			: "Hide details"
		: isChineseUi
			? "展开详情"
			: "Show details";
	const executeLabel = isBusy
		? isChineseUi
			? "处理中..."
			: "Working..."
		: isChineseUi
			? "确认切换"
			: "Confirm route";
	const continueLabel = isChineseUi
		? "继续当前分支"
		: "Stay in current branch";
	const executeBranchAction = () => {
		setIsExpanded(false);
		onExecute?.(action);
	};
	const continueCurrentBranch = () => {
		setIsExpanded(false);
		(onContinueCurrent ?? onDismiss)?.(action);
	};

	useEffect(() => {
		setIsExpanded(pending);
	}, [pending]);

	return (
		<div className="fa-message-row is-assistant assistant">
			<div className="fa-message-stack">
				<div className="fa-message-head">
					<div className="fa-message-role fa-message-meta">
						{isChineseUi ? "分支操作" : "Branch action"}
					</div>
				</div>
				<details
					className={`fa-message-bubble is-assistant fa-branch-action-card is-${action.status}`}
					onToggle={(event) =>
						setIsExpanded((event.currentTarget as HTMLDetailsElement).open)
					}
					open={isExpanded}
				>
					<summary className="fa-branch-action-card-header">
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
									{focusMetric ? ` · ${focusMetric.shortLabel}` : ""}
								</span>
							) : null}
							<span className="fa-branch-action-card-badge">
								{action.branch_role}
							</span>
						</div>
						<span className="fa-branch-action-card-toggle">{toggleLabel}</span>
					</summary>
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
						{focusMetric ? (
							<div>
								<span>{focusMetric.label}</span>
								<strong>{focusMetric.value}</strong>
							</div>
						) : null}
						{routingConfidence &&
						(!focusMetric || focusMetric.kind !== "routing") ? (
							<div>
								<span>{isChineseUi ? "路由置信度" : "Routing confidence"}</span>
								<strong>{routingConfidence}</strong>
							</div>
						) : null}
						{showSourceDecisionDiagnostic ? (
							<div className="fa-branch-action-card-diagnostic">
								<span>{isChineseUi ? "诊断" : "Diagnostic"}</span>
								<strong>{sourceDecisionDiagnostic}</strong>
							</div>
						) : null}
						{auditOnly ? (
							<div className="fa-branch-action-card-audit-note">
								{branchDecisionAuditOnlyText(isChineseUi)}
							</div>
						) : null}
					</div>
					{pending ? (
						<div className="fa-branch-action-card-actions">
							<button
								className="fa-chat-toolbar-button is-primary"
								disabled={disabled}
								onClick={executeBranchAction}
								type="button"
							>
								{executeLabel}
							</button>
							<button
								className="fa-chat-toolbar-button"
								disabled={disabled}
								onClick={continueCurrentBranch}
								type="button"
							>
								{continueLabel}
							</button>
						</div>
					) : null}
				</details>
			</div>
		</div>
	);
}
