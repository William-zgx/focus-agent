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
	const scoreLabel = !isBranchHandoff ? scorePercent(decision.score) : null;
	const summarySegments = isBranchHandoff
		? [
				decisionKickerLabel(decision, isChineseUi),
				decisionStatusLabel(decision, isChineseUi),
				decisionActionLabel(decision, isChineseUi),
			]
		: ["Focus Score", scoreLabel];
	const summaryLabel = summarySegments.join(" · ");
	return (
		<section
			className="fa-branch-decision-summary"
			id={`branch-decision-${decision.decision_id}`}
		>
			<div
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
						<Badge tone="info">
							{isBranchHandoff
								? decisionKickerLabel(decision, isChineseUi)
								: "Focus Score"}
						</Badge>
						{isBranchHandoff ? (
							<span>{decisionStatusLabel(decision, isChineseUi)}</span>
						) : null}
						{scoreLabel ? <span>{scoreLabel}</span> : null}
					</span>
					{isBranchHandoff ? (
						<strong className="fa-branch-decision-summary-title">
							{decisionActionLabel(decision, isChineseUi)}
						</strong>
					) : null}
					{showAuditNote ? (
						<span className="fa-branch-decision-audit-note">
							{branchDecisionAuditOnlyText(isChineseUi)}
						</span>
					) : null}
				</Button>
				<div
					aria-label={
						isChineseUi ? "AI 建议诊断详情" : "AI suggestion diagnostic details"
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
					/>
					<div className="fa-branch-decision-summary-actions">
						{actionable ? (
							<Button
								disabled={busy}
								onClick={() => promote.mutate(decision)}
								size="sm"
								variant="primary"
							>
								{isChineseUi ? "生成分支确认项" : "Promote"}
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
			</div>
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
}: {
	decision: FocusAgentBranchDecisionEvent;
	detailNote: string;
	isChineseUi: boolean;
	isBranchHandoff: boolean;
}) {
	const handoffRunStatus = branchHandoffRunStatus(decision);
	return (
		<div className="fa-branch-decision-drawer">
			<div className="fa-branch-decision-drawer-grid">
				<div>
					<span>{isChineseUi ? "结论" : "Conclusion"}</span>
					<strong>{decisionActionLabel(decision, isChineseUi)}</strong>
				</div>
				{!isBranchHandoff ? (
					<div>
						<span>Focus Score</span>
						<strong>{scorePercent(decision.score)}</strong>
					</div>
				) : null}
				<div>
					<span>{isChineseUi ? "状态" : "Status"}</span>
					<strong>{decisionStatusLabel(decision, isChineseUi)}</strong>
				</div>
				<div>
					<span>{isChineseUi ? "模式" : "Mode"}</span>
					<strong>{decision.mode}</strong>
				</div>
				{isBranchHandoff ? (
					<div>
						<span>{isChineseUi ? "自动生成" : "Auto run"}</span>
						<strong>
							{branchHandoffRunStatusLabel(handoffRunStatus, isChineseUi)}
						</strong>
					</div>
				) : null}
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
		return branchHandoffDetailText(isChineseUi);
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
			? "当前条件阻止继续创建分支建议。"
			: "The current conditions block another branch recommendation.";
	}
	if (decision.status === "skipped") {
		return isChineseUi
			? "本轮不需要创建新的分支操作。"
			: "No new branch action is needed for this turn.";
	}
	if (decision.status === "error" || showDiagnostic) {
		return isChineseUi
			? "建议诊断已记录，当前展示关键结论。"
			: "Diagnostics were recorded; this view shows the key conclusion.";
	}
	return "";
}

function branchHandoffRunStatusLabel(status: string, isChineseUi: boolean) {
	if (status === "interrupted") {
		return isChineseUi ? "自动生成已中断" : "Auto generation interrupted";
	}
	if (status === "error") {
		return isChineseUi ? "自动生成失败" : "Auto generation failed";
	}
	if (status === "success") {
		return isChineseUi ? "自动生成已完成" : "Auto generation completed";
	}
	if (status === "running") {
		return isChineseUi ? "自动生成中" : "Auto generation running";
	}
	return isChineseUi ? "已接收" : "Received";
}

function branchHandoffDetailText(isChineseUi: boolean) {
	return isChineseUi
		? "新分支已接收带入问题，继续在当前分支处理"
		: "The new branch received the carried question; continue in the current branch";
}

function decisionKickerLabel(
	decision: FocusAgentBranchDecisionEvent,
	isChineseUi: boolean,
) {
	if (isBranchHandoffDecision(decision)) {
		return isChineseUi ? "轻量 AI 建议" : "Light AI suggestion";
	}
	return isChineseUi ? "AI 建议" : "AI suggestion";
}

function decisionActionLabel(
	decision: FocusAgentBranchDecisionEvent,
	isChineseUi: boolean,
) {
	if (isBranchHandoffDecision(decision)) {
		return isChineseUi
			? "继续在当前新分支处理带入问题"
			: "Continue the carried question in this new branch";
	}
	if (decision.action === "split") {
		return isChineseUi
			? "建议创建一个低风险新分支"
			: "Suggest creating a low-risk branch";
	}
	if (decision.action === "fork_child_branch") {
		return isChineseUi ? "建议创建子分支" : "Suggest creating a child branch";
	}
	if (decision.action === "fork_sibling_branch") {
		return isChineseUi ? "建议切换到同级分支" : "Suggest a sibling branch";
	}
	if (decision.action === "merge_candidate") {
		return isChineseUi
			? "这个分支可能已适合回收结论"
			: "This branch may be ready to merge back";
	}
	if (decision.action === "continue_current") {
		return isChineseUi ? "建议继续当前线程" : "Suggest continuing this thread";
	}
	return isChineseUi
		? "这个线程可能已适合收束结论"
		: "This thread may be ready to conclude";
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
