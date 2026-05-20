import type {
	FocusAgentBranchDecisionEvent,
	FocusAgentBranchDecisionSummary,
} from "@focus-agent/web-sdk";
import { useState } from "react";

import {
	branchDecisionAuditOnlyText,
	branchDecisionDiagnosticText,
	branchDecisionSemanticDiagnosticEntries,
	branchHandoffRunStatus,
	isBranchHandoffDecision,
	shouldShowBranchDecisionDiagnostic,
} from "@/shared/branch-decision-diagnostics";
import { Badge, Button } from "@/shared/ui/primitives";

import {
	useBranchDecisionActions,
	useBranchDecisionConfig,
} from "./use-branch-decisions";

type BranchDecisionSummaryPanelProps = {
	isChineseUi: boolean;
	isReadOnly: boolean;
	rootThreadId?: string;
	summary?: FocusAgentBranchDecisionSummary | null;
	threadId: string;
};

export function BranchDecisionSummaryPanel({
	isChineseUi,
	isReadOnly,
	rootThreadId,
	summary,
	threadId,
}: BranchDecisionSummaryPanelProps) {
	const [drawerOpen, setDrawerOpen] = useState(false);
	const decision = summary?.latest_decision ?? null;
	const { data: config } = useBranchDecisionConfig();
	const { dismiss, promote } = useBranchDecisionActions({
		rootThreadId,
		threadId,
	});
	const configDiagnostic = branchDecisionDiagnosticText({
		diagnostic: config?.diagnostic ?? config?.recommendation_diagnostics,
	});
	const rawDiagnostic = decision
		? branchDecisionDiagnosticText(decision) || configDiagnostic
		: "";
	const semanticDiagnosticEntries = decision
		? branchDecisionSemanticDiagnosticEntries(decision)
		: [];
	const recommendationUserVisible =
		decision?.recommendation_user_visible ??
		config?.recommendation_user_visible;
	const auditOnly = recommendationUserVisible === false;
	const isBranchHandoff = decision ? isBranchHandoffDecision(decision) : false;
	const showAuditNote = auditOnly && !isBranchHandoff;
	const diagnostic = isBranchHandoff ? "" : rawDiagnostic;

	if (
		!decision ||
		((decision.status === "skipped" ||
			decision.recommendation_target === "continue_current") &&
			!isBranchHandoff &&
			!diagnostic &&
			semanticDiagnosticEntries.length === 0 &&
			!auditOnly)
	) {
		return null;
	}

	const actionable = Boolean(
		summary?.actionable && !isReadOnly && !showAuditNote && !isBranchHandoff,
	);
	const busy = promote.isPending || dismiss.isPending;
	const detailId = `branch-decision-${decision.decision_id}-details`;
	const showDiagnostic =
		shouldShowBranchDecisionDiagnostic(decision.status) ||
		auditOnly ||
		isBranchHandoff ||
		semanticDiagnosticEntries.length > 0;
	const focusMetric = branchDecisionFocusMetric({
		decision,
		isChineseUi,
		semanticDiagnosticEntries,
	});
	const badgeLabel = isChineseUi ? "轻量 AI 建议" : "Focus Score";
	const scoreLabel = focusMetric.value;
	const summarySegments = [badgeLabel, focusMetric.value];
	const summaryLabel = summarySegments.join(" · ");
	return (
		<section
			className="fa-branch-decision-summary"
			id={`branch-decision-${decision.decision_id}`}
		>
			<fieldset
				className={`fa-branch-decision-summary-popover ${
					drawerOpen ? "is-open" : ""
				}`}
				onBlur={(event) => {
					if (!event.currentTarget.contains(event.relatedTarget)) {
						setDrawerOpen(false);
					}
				}}
				onMouseLeave={() => setDrawerOpen(false)}
			>
				<legend className="sr-only">
					{isChineseUi ? "Focus Score 路由详情" : "Focus Score routing details"}
				</legend>
				<Button
					aria-controls={detailId}
					aria-expanded={drawerOpen}
					aria-label={
						isChineseUi
							? `${summaryLabel}。悬停或点击查看诊断详情。`
							: `${summaryLabel}. Hover or click for diagnostic details.`
					}
					className="fa-branch-decision-summary-trigger"
					data-handoff={isBranchHandoff ? "true" : undefined}
					disabled={busy}
					onClick={() => setDrawerOpen((value) => !value)}
					size="sm"
					variant="ghost"
				>
					<span className="fa-branch-decision-summary-kicker">
						<Badge tone="info">{badgeLabel}</Badge>
						{scoreLabel ? <span>{scoreLabel}</span> : null}
					</span>
					{showAuditNote ? (
						<span className="fa-branch-decision-audit-note">
							{branchDecisionAuditOnlyText(isChineseUi)}
						</span>
					) : null}
				</Button>
				<div
					aria-label={
						isChineseUi ? "Focus Score 路由详情" : "Focus Score routing details"
					}
					className="fa-branch-decision-summary-details"
					id={detailId}
					role="dialog"
				>
					<BranchDecisionDrawer
						decision={decision}
						detailNote={branchDecisionDetailNote({
							auditOnly,
							decision,
							isBranchHandoff,
							isChineseUi,
							showDiagnostic,
						})}
						isChineseUi={isChineseUi}
						isBranchHandoff={isBranchHandoff}
						semanticDiagnosticEntries={semanticDiagnosticEntries}
					/>
					<div className="fa-branch-decision-summary-actions">
						{actionable ? (
							<Button
								disabled={busy}
								onClick={() => promote.mutate(decision)}
								size="sm"
								variant="primary"
							>
								{isChineseUi ? "确认分支去向" : "Confirm routing"}
							</Button>
						) : null}
						{actionable ? (
							<Button
								disabled={busy}
								onClick={() =>
									dismiss.mutate({
										decision,
										request: { reason: "dismissed_from_thread_summary" },
									})
								}
								size="sm"
								variant="secondary"
							>
								{isChineseUi ? "忽略" : "Dismiss"}
							</Button>
						) : null}
					</div>
				</div>
			</fieldset>
			{promote.error || dismiss.error ? (
				<div className="fa-branch-decision-error">
					{isChineseUi ? "更新 AI 决策失败。" : "Failed to update AI decision."}
				</div>
			) : null}
		</section>
	);
}

function BranchDecisionDrawer({
	decision,
	detailNote,
	isChineseUi,
	isBranchHandoff,
	semanticDiagnosticEntries,
}: {
	decision: FocusAgentBranchDecisionEvent;
	detailNote: string;
	isChineseUi: boolean;
	isBranchHandoff: boolean;
	semanticDiagnosticEntries: ReturnType<
		typeof branchDecisionSemanticDiagnosticEntries
	>;
}) {
	const handoffRunStatus = branchHandoffRunStatus(decision);
	const focusMetric = branchDecisionFocusMetric({
		decision,
		isChineseUi,
		semanticDiagnosticEntries,
	});
	const routingConfidence = scorePercent(decision.score);
	return (
		<div className="fa-branch-decision-drawer">
			<div className="fa-branch-decision-drawer-grid">
				<div>
					<span>{focusMetric.label}</span>
					<strong>{focusMetric.value}</strong>
				</div>
				{focusMetric.kind !== "routing" ? (
					<div>
						<span>{isChineseUi ? "路由置信度" : "Routing confidence"}</span>
						<strong>{routingConfidence}</strong>
					</div>
				) : null}
				<div>
					<span>{isChineseUi ? "主线判断" : "Flow fit"}</span>
					<strong>{branchDecisionFitLabel(decision, isChineseUi)}</strong>
				</div>
				<div>
					<span>{isChineseUi ? "建议去向" : "Suggested routing"}</span>
					<strong>{branchDecisionRoutingLabel(decision, isChineseUi)}</strong>
				</div>
				<div>
					<span>{isChineseUi ? "当前状态" : "Current status"}</span>
					<strong>
						{isBranchHandoff
							? branchHandoffRunStatusLabel(handoffRunStatus, isChineseUi)
							: decisionStatusLabel(decision, isChineseUi)}
					</strong>
				</div>
				{detailNote ? (
					<div>
						<span>{isChineseUi ? "说明" : "Note"}</span>
						<strong>{detailNote}</strong>
					</div>
				) : null}
			</div>
		</div>
	);
}

function scorePercent(score: number) {
	return `${Math.round(score * 100)}%`;
}

function branchDecisionFocusMetric({
	decision,
	isChineseUi,
	semanticDiagnosticEntries,
}: {
	decision: FocusAgentBranchDecisionEvent;
	isChineseUi: boolean;
	semanticDiagnosticEntries: ReturnType<
		typeof branchDecisionSemanticDiagnosticEntries
	>;
}) {
	const relatedness = semanticDiagnosticEntries.find(
		(entry) => entry.key === "semantic_relatedness",
	)?.value;
	if (relatedness) {
		return {
			kind: "relevance",
			label: isChineseUi ? "当前问题关联度" : "Question relevance",
			value: relatedness,
		};
	}
	return {
		kind: "routing",
		label: isChineseUi ? "路由判断置信度" : "Routing confidence",
		value: scorePercent(decision.score),
	};
}

function branchDecisionDetailNote({
	auditOnly,
	decision,
	isBranchHandoff,
	isChineseUi,
	showDiagnostic,
}: {
	auditOnly: boolean;
	decision: FocusAgentBranchDecisionEvent;
	isBranchHandoff: boolean;
	isChineseUi: boolean;
	showDiagnostic: boolean;
}) {
	if (isBranchHandoff) {
		return "";
	}
	if (auditOnly) {
		return branchDecisionAuditOnlyText(isChineseUi);
	}
	if (decision.status === "suggested") {
		return isChineseUi
			? "已生成可确认的分支建议。"
			: "A branch recommendation is ready to confirm.";
	}
	if (decision.status === "blocked") {
		return isChineseUi
			? "当前已有待处理的分支去向，暂不重复提示。"
			: "A routing decision is already pending.";
	}
	if (decision.status === "skipped") {
		return isChineseUi
			? "当前问题仍可留在当前分支。"
			: "The current question can stay in this branch.";
	}
	if (decision.status === "error" || showDiagnostic) {
		return isChineseUi
			? "已记录路由判断，当前只展示关键结论。"
			: "Routing diagnostics were recorded; this view shows the key conclusion.";
	}
	return "";
}

function branchHandoffRunStatusLabel(status: string, isChineseUi: boolean) {
	if (status === "interrupted") {
		return isChineseUi
			? "自动生成已中断"
			: "Automatic generation was interrupted";
	}
	if (status === "error") {
		return isChineseUi ? "切换后回复失败" : "Reply after routing failed";
	}
	if (status === "success") {
		return isChineseUi ? "已切到更匹配的分支" : "Routed to a better-fit branch";
	}
	if (status === "running") {
		return isChineseUi
			? "正在切到更匹配的分支"
			: "Routing to a better-fit branch";
	}
	return isChineseUi
		? "已接收，等待继续处理"
		: "Received and ready to continue";
}

function branchDecisionFitLabel(
	decision: FocusAgentBranchDecisionEvent,
	isChineseUi: boolean,
) {
	if (isBranchHandoffDecision(decision)) {
		return isChineseUi
			? "新分支已接收带入问题，继续在当前分支处理"
			: "The new branch received the carried question; continue here";
	}
	if (
		decision.action === "split" ||
		decision.action === "fork_child_branch" ||
		decision.action === "fork_sibling_branch"
	) {
		return isChineseUi
			? "当前问题和这个节点主线的贴合度较低"
			: "The current question has low fit with this node's flow";
	}
	if (decision.action === "merge_candidate") {
		return isChineseUi
			? "这个分支的结论已经比较完整"
			: "This branch looks ready to fold back";
	}
	if (decision.action === "continue_current") {
		return isChineseUi
			? "当前问题仍贴合这个节点主线"
			: "The current question still fits this node's flow";
	}
	return isChineseUi
		? "当前节点已经接近可收束状态"
		: "This node is close to a conclusion";
}

function branchDecisionRoutingLabel(
	decision: FocusAgentBranchDecisionEvent,
	isChineseUi: boolean,
) {
	if (isBranchHandoffDecision(decision)) {
		return isChineseUi
			? "继续在当前新分支处理带入问题"
			: "Continue the carried question in this new branch";
	}
	if (decision.action === "split") {
		return isChineseUi ? "另开一个低风险分支" : "Open a low-risk branch";
	}
	if (decision.action === "fork_child_branch") {
		return isChineseUi ? "切到子分支处理" : "Route to a child branch";
	}
	if (decision.action === "fork_sibling_branch") {
		return isChineseUi ? "切到同级分支处理" : "Route to a sibling branch";
	}
	if (decision.action === "merge_candidate") {
		return isChineseUi ? "回收分支结论" : "Merge branch findings";
	}
	if (decision.action === "continue_current") {
		return isChineseUi ? "继续留在当前分支" : "Stay in the current branch";
	}
	return isChineseUi ? "整理并收束当前结论" : "Conclude this thread";
}

function decisionStatusLabel(
	decision: FocusAgentBranchDecisionEvent,
	isChineseUi: boolean,
) {
	if (isBranchHandoffDecision(decision)) {
		return isChineseUi ? "已接收" : "Received";
	}
	const labels: Record<string, string> = isChineseUi
		? {
				blocked: "已阻断",
				dismissed: "已忽略",
				error: "错误",
				promoted: "已生成确认项",
				shadowed: "影子评估",
				skipped: "已跳过",
				suggested: "待确认",
			}
		: {
				blocked: "Blocked",
				dismissed: "Dismissed",
				error: "Error",
				promoted: "Promoted",
				shadowed: "Shadow",
				skipped: "Skipped",
				suggested: "Suggested",
			};
	return labels[decision.status] ?? decision.status;
}
