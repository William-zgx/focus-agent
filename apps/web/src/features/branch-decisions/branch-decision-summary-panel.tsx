import type {
	FocusAgentBranchDecisionEvent,
	FocusAgentBranchDecisionSummary,
} from "@focus-agent/web-sdk";
import { useState } from "react";

import { Badge, Button, Surface } from "@/shared/ui/primitives";

import { useBranchDecisionActions } from "./use-branch-decisions";

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
	const { dismiss, promote } = useBranchDecisionActions({
		rootThreadId,
		threadId,
	});

	if (
		!decision ||
		decision.status === "skipped" ||
		decision.recommendation_target === "continue_current"
	) {
		return null;
	}

	const actionable = Boolean(summary?.actionable && !isReadOnly);
	const busy = promote.isPending || dismiss.isPending;
	return (
		<Surface
			className="fa-branch-decision-summary"
			id={`branch-decision-${decision.decision_id}`}
			tone="section"
		>
			<div className="fa-branch-decision-summary-main">
				<div className="fa-branch-decision-summary-copy">
					<div className="fa-branch-decision-summary-kicker">
						<Badge tone="info">
							{isChineseUi ? "AI 建议" : "AI suggestion"}
						</Badge>
						<span>{decisionStatusLabel(decision, isChineseUi)}</span>
						<span>{Math.round(decision.score * 100)}%</span>
					</div>
					<div className="fa-branch-decision-summary-title">
						{decisionActionLabel(decision, isChineseUi)}
					</div>
					<div className="fa-branch-decision-summary-text">
						{decision.rationale}
					</div>
				</div>
				<div className="fa-branch-decision-summary-actions">
					<Button
						disabled={busy}
						onClick={() => setDrawerOpen((value) => !value)}
						size="sm"
						variant="ghost"
					>
						{drawerOpen
							? isChineseUi
								? "收起依据"
								: "Hide evidence"
							: isChineseUi
								? "查看依据"
								: "Evidence"}
					</Button>
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
			{drawerOpen ? (
				<BranchDecisionDrawer decision={decision} isChineseUi={isChineseUi} />
			) : null}
			{promote.error || dismiss.error ? (
				<div className="fa-branch-decision-error">
					{isChineseUi ? "更新 AI 决策失败。" : "Failed to update AI decision."}
				</div>
			) : null}
		</Surface>
	);
}

function BranchDecisionDrawer({
	decision,
	isChineseUi,
}: {
	decision: FocusAgentBranchDecisionEvent;
	isChineseUi: boolean;
}) {
	return (
		<div className="fa-branch-decision-drawer">
			<div className="fa-branch-decision-drawer-grid">
				<div>
					<span>{isChineseUi ? "模式" : "Mode"}</span>
					<strong>{decision.mode}</strong>
				</div>
				<div>
					<span>{isChineseUi ? "阈值" : "Threshold"}</span>
					<strong>{Math.round(decision.threshold * 100)}%</strong>
				</div>
				<div>
					<span>{isChineseUi ? "动作" : "Action"}</span>
					<strong>{decision.action}</strong>
				</div>
			</div>
			<div className="fa-branch-decision-signals">
				{decision.signals.map((signal) => (
					<div className="fa-branch-decision-signal" key={signal.name}>
						<div>
							<strong>{signal.name}</strong>
							<span>{Math.round(signal.score * 100)}%</span>
						</div>
						<p>{signal.rationale}</p>
					</div>
				))}
			</div>
		</div>
	);
}

function decisionActionLabel(
	decision: FocusAgentBranchDecisionEvent,
	isChineseUi: boolean,
) {
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
	const labels: Record<string, string> = isChineseUi
		? {
				blocked: "已阻断",
				dismissed: "已忽略",
				error: "错误",
				promoted: "已生成确认项",
				shadowed: "影子评估",
				suggested: "待确认",
			}
		: {
				blocked: "Blocked",
				dismissed: "Dismissed",
				error: "Error",
				promoted: "Promoted",
				shadowed: "Shadow",
				suggested: "Suggested",
			};
	return labels[decision.status] ?? decision.status;
}
