import type {
	FocusAgentContextMemoryEvidence,
	FocusAgentFeedbackTrendResponse,
	FocusAgentSkillCatalogItem,
	FocusAgentSkillSelectionEvent,
} from "@focus-agent/web-sdk";

import { EmptyState, PanelHeader } from "./agent-role-console-sections";
import { errorMessage } from "./agent-role-console-utils";

type OperationsPanelsProps = {
	contextEvidence: FocusAgentContextMemoryEvidence[];
	contextEvidenceError: Error | null;
	feedbackTrend: FocusAgentFeedbackTrendResponse | undefined;
	feedbackTrendError: Error | null;
	isChineseUi: boolean;
	skillCatalogItems: FocusAgentSkillCatalogItem[];
	skillSelections: FocusAgentSkillSelectionEvent[];
	skillSelectionsError: Error | null;
};

export function OperationsGovernancePanels({
	contextEvidence,
	contextEvidenceError,
	feedbackTrend,
	feedbackTrendError,
	isChineseUi,
	skillCatalogItems,
	skillSelections,
	skillSelectionsError,
}: OperationsPanelsProps) {
	return (
		<section className="fa-agent-role-grid">
			<div className="fa-observability-list-panel fa-agent-role-panel fa-agent-role-ops-panel">
				<PanelHeader
					eyebrow={isChineseUi ? "Context / Memory" : "Context / Memory"}
					meta={`${contextEvidence.length} records`}
					title={isChineseUi ? "Why this context?" : "Why this context?"}
				/>
				<InlinePanelError
					error={contextEvidenceError}
					isChineseUi={isChineseUi}
				/>
				{contextEvidence.length ? (
					<div className="fa-agent-role-ops-list">
						{contextEvidence.slice(0, 5).map((item) => (
							<article
								className="fa-agent-role-ops-card"
								key={item.evidence_id}
							>
								<div>
									<strong>
										{item.turn_id ?? item.thread_id ?? item.evidence_id}
									</strong>
									<span>
										{item.token_counting_backend ?? "tokenizer pending"}
									</span>
								</div>
								<p>{item.compaction_summary ?? "No compaction summary."}</p>
								<div className="fa-agent-role-ops-chips">
									<span>{item.selected_memories.length} memories</span>
									<span>{item.artifact_refs.length} artifacts</span>
									{item.estimated ? <span>estimated</span> : <span>exact</span>}
									{item.risk_flags.map((risk) => (
										<span key={risk}>{risk}</span>
									))}
								</div>
							</article>
						))}
					</div>
				) : (
					<EmptyState>
						{isChineseUi
							? "暂无 context memory evidence。"
							: "No context memory evidence yet."}
					</EmptyState>
				)}
			</div>

			<div className="fa-observability-detail-panel fa-agent-role-panel fa-agent-role-ops-panel">
				<PanelHeader
					eyebrow={isChineseUi ? "Skill Ops" : "Skill Ops"}
					meta={`${skillCatalogItems.length} skills`}
					title={isChineseUi ? "技能命中运营" : "Skill selection operations"}
				/>
				<InlinePanelError
					error={skillSelectionsError}
					isChineseUi={isChineseUi}
				/>
				<div className="fa-agent-role-ops-list">
					{skillSelections.slice(0, 5).map((selection) => (
						<article
							className="fa-agent-role-ops-card"
							key={selection.selection_id}
						>
							<div>
								<strong>{selection.selection_source}</strong>
								<span>{Math.round(selection.confidence * 100)}%</span>
							</div>
							<p>{selection.rationale ?? "No rationale recorded."}</p>
							<div className="fa-agent-role-ops-chips">
								{selection.activated_skills.map((skillId) => (
									<span key={skillId}>{skillId}</span>
								))}
								{selection.user_override ? (
									<span>{selection.user_override}</span>
								) : null}
								{selection.feedback ? <span>{selection.feedback}</span> : null}
							</div>
						</article>
					))}
					{!skillSelections.length ? (
						<EmptyState>
							{isChineseUi
								? "暂无 skill selection event。"
								: "No skill selection events yet."}
						</EmptyState>
					) : null}
				</div>
			</div>

			<div className="fa-observability-detail-panel fa-agent-role-panel fa-agent-role-ops-panel">
				<PanelHeader
					eyebrow={isChineseUi ? "Feedback Trend" : "Feedback Trend"}
					meta={feedbackTrend?.generated_at ?? "planned API"}
					title={isChineseUi ? "长期反馈闭环" : "Long-running feedback loop"}
				/>
				<InlinePanelError
					error={feedbackTrendError}
					isChineseUi={isChineseUi}
				/>
				<div className="fa-agent-role-ops-metrics">
					<Metric
						label="negative"
						value={feedbackTrend?.negative_feedback_count}
					/>
					<Metric
						label="drift"
						value={feedbackTrend?.context_high_drift_count}
					/>
					<Metric
						label="capture"
						value={feedbackTrend?.notes_tasks_capture_count}
					/>
					<Metric
						label="apply rate"
						value={formatRate(feedbackTrend?.merge_review_apply_success_rate)}
					/>
					<Metric
						label="skill override"
						value={formatRate(feedbackTrend?.skill_override_rate)}
					/>
					<Metric
						label="conflict"
						value={formatRate(feedbackTrend?.merge_review_conflict_rate)}
					/>
				</div>
			</div>
		</section>
	);
}

function InlinePanelError({
	error,
	isChineseUi,
}: {
	error: Error | null;
	isChineseUi: boolean;
}) {
	if (!error) return null;
	return (
		<div className="fa-inline-notice is-warning">
			{errorMessage(
				error,
				isChineseUi
					? "计划 API 尚未返回。"
					: "Planned API is not returning yet.",
			)}
		</div>
	);
}

function Metric({
	label,
	value,
}: {
	label: string;
	value: number | string | null | undefined;
}) {
	return (
		<div>
			<span>{label}</span>
			<strong>{value ?? "-"}</strong>
		</div>
	);
}

function formatRate(value: number | null | undefined) {
	if (typeof value !== "number") return undefined;
	return `${Math.round(value * 100)}%`;
}
