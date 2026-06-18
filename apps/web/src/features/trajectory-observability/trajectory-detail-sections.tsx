import type { FocusAgentTrajectoryTurnDetail } from "@focus-agent/web-sdk";

import {
	TimelineEvidence,
	ZeroStepEvidence,
} from "./trajectory-evidence-views";
import { TrajectoryEmptyState } from "./trajectory-states";
import type { EvidenceMode, ReviewSummary } from "./trajectory-utils";
import {
	compactDetailQuestion,
	compactSnippet,
	findTaskOutcome,
	findToolOutcomes,
	formatBranchRoleLabel,
	formatSceneLabel,
	outcomeTone,
	readOutcomeText,
	statusTone,
} from "./trajectory-utils";

export type SupplementalContextItem = {
	id: string;
	labelZh: string;
	labelEn: string;
	value: string;
};

export type SelectedSignals = {
	parallelSteps: number;
};

export function ReviewSummaryCard({
	isChineseUi,
	reviewSummary,
}: {
	isChineseUi: boolean;
	reviewSummary: ReviewSummary;
}) {
	return (
		<article className="fa-trajectory-workbench-summary-card">
			<div className="fa-trajectory-workbench-summary-top">
				<div className="fa-trajectory-workbench-summary-copy">
					<p>{isChineseUi ? "结论摘要" : "Review summary"}</p>
					<h2>{reviewSummary.headline}</h2>
					<span>{reviewSummary.lead}</span>
				</div>
				<div className="fa-trajectory-workbench-summary-side">
					<span
						className={`fa-observability-pill is-${statusTone(reviewSummary.status)}`}
					>
						{reviewSummary.status}
					</span>
					<span>{reviewSummary.createdAt}</span>
					<strong>{reviewSummary.evidenceLabel}</strong>
				</div>
			</div>
			<div className="fa-trajectory-workbench-summary-grid">
				{reviewSummary.stats.map((item) => (
					<div key={item.id} className="fa-trajectory-workbench-summary-metric">
						<span>{isChineseUi ? item.labelZh : item.labelEn}</span>
						<strong>{item.value}</strong>
					</div>
				))}
			</div>
		</article>
	);
}

export function TaskOutcomeCard({
	isChineseUi,
	selected,
}: {
	isChineseUi: boolean;
	selected: FocusAgentTrajectoryTurnDetail;
}) {
	const taskOutcome = findTaskOutcome(selected);
	const toolOutcomes = findToolOutcomes(selected);
	if (!taskOutcome && toolOutcomes.length === 0) return null;

	const status = readOutcomeText(taskOutcome, ["status"]) || "unrecorded";
	const rows = [
		{
			id: "policy",
			labelZh: "策略",
			labelEn: "Policy",
			value: readOutcomeText(taskOutcome, ["policy"]),
		},
		{
			id: "answer_basis",
			labelZh: "回答依据",
			labelEn: "Answer basis",
			value: readOutcomeText(taskOutcome, ["answer_basis"]),
		},
		{
			id: "repair_action_taken",
			labelZh: "修复动作",
			labelEn: "Repair action",
			value: readOutcomeText(taskOutcome, ["repair_action_taken"]),
		},
		{
			id: "degradation_reason",
			labelZh: "降级原因",
			labelEn: "Degradation reason",
			value: readOutcomeText(taskOutcome, ["degradation_reason"]),
		},
		{
			id: "evidence_count",
			labelZh: "证据数",
			labelEn: "Evidence count",
			value: readOutcomeText(taskOutcome, ["evidence_count"]),
		},
		{
			id: "tool_outcomes",
			labelZh: "工具 Outcome",
			labelEn: "Tool outcomes",
			value: toolOutcomes.length ? String(toolOutcomes.length) : "",
		},
	];

	return (
		<article className="fa-trajectory-workbench-context-panel">
			<div className="fa-trajectory-workbench-section-head">
				<div>
					<p>{isChineseUi ? "运行 Outcome" : "Runtime outcome"}</p>
					<h3>Task Outcome</h3>
				</div>
				<span className={`fa-observability-pill is-${outcomeTone(status)}`}>
					{status}
				</span>
			</div>
			<div className="fa-trajectory-workbench-context-grid">
				{rows.map((item) => (
					<div key={item.id} className="fa-observability-meta-item">
						<span>{isChineseUi ? item.labelZh : item.labelEn}</span>
						<strong>{item.value || "—"}</strong>
					</div>
				))}
			</div>
			<div className="fa-trajectory-workbench-raw-stack">
				{taskOutcome ? (
					<details className="fa-observability-raw-toggle">
						<summary>
							{isChineseUi ? "查看 Task Outcome" : "View Task Outcome"}
						</summary>
						<pre>{JSON.stringify(taskOutcome, null, 2)}</pre>
					</details>
				) : null}
				{toolOutcomes.length ? (
					<details className="fa-observability-raw-toggle">
						<summary>
							{isChineseUi ? "查看 Tool Outcomes" : "View Tool Outcomes"}
						</summary>
						<pre>{JSON.stringify(toolOutcomes, null, 2)}</pre>
					</details>
				) : null}
			</div>
		</article>
	);
}

export function EvidenceStage({
	correlationCoverage,
	evidenceMode,
	isChineseUi,
	resultSummary,
	selected,
	selectedSignals,
}: {
	correlationCoverage: number;
	evidenceMode: EvidenceMode;
	isChineseUi: boolean;
	resultSummary: string;
	selected: FocusAgentTrajectoryTurnDetail;
	selectedSignals: SelectedSignals;
}) {
	return (
		<article className="fa-trajectory-workbench-evidence-panel">
			<div className="fa-trajectory-workbench-section-head">
				<div>
					<p>{isChineseUi ? "证据主区" : "Evidence stage"}</p>
					<h3>
						{evidenceMode === "timeline"
							? isChineseUi
								? "按时间线读执行证据"
								: "Read the execution evidence as a timeline"
							: evidenceMode === "zero_step"
								? isChineseUi
									? "零步骤证据视图"
									: "Zero-step evidence view"
								: isChineseUi
									? "详情缺失"
									: "Missing detail"}
					</h3>
				</div>
				<span>
					{evidenceMode === "timeline"
						? isChineseUi
							? `${selected.trajectory.length} 步 · ${selectedSignals.parallelSteps} 个并行批次`
							: `${selected.trajectory.length} steps · ${selectedSignals.parallelSteps} parallel batches`
						: isChineseUi
							? "没有可展开的 timeline"
							: "No timeline is available"}
				</span>
			</div>

			{selected.error ? (
				<div className="fa-inline-notice is-danger">{selected.error}</div>
			) : null}

			{evidenceMode === "timeline" ? (
				<TimelineEvidence isChineseUi={isChineseUi} selected={selected} />
			) : evidenceMode === "zero_step" ? (
				<ZeroStepEvidence
					correlationCoverage={correlationCoverage}
					isChineseUi={isChineseUi}
					resultSummary={resultSummary}
					selected={selected}
				/>
			) : (
				<TrajectoryEmptyState isChineseUi={isChineseUi} kind="missing-detail" />
			)}
		</article>
	);
}

export function StoryGrid({
	isChineseUi,
	resultSummary,
	selected,
}: {
	isChineseUi: boolean;
	resultSummary: string;
	selected: FocusAgentTrajectoryTurnDetail;
}) {
	return (
		<div className="fa-trajectory-workbench-story-grid">
			<article className="fa-trajectory-workbench-story-card">
				<div className="fa-trajectory-workbench-section-head">
					<div>
						<p>{isChineseUi ? "输入叙事" : "Input narrative"}</p>
						<h3>
							{isChineseUi
								? "用户是怎么把问题带进来的"
								: "How the user brought the task in"}
						</h3>
					</div>
				</div>
				<p>
					{compactDetailQuestion(
						selected.user_message || selected.task_brief || "—",
					)}
				</p>
				<div className="fa-observability-inline-chip-row">
					<span className="fa-observability-pill is-neutral">
						{formatSceneLabel(selected.scene, isChineseUi)}
					</span>
					{selected.branch_role ? (
						<span className="fa-observability-pill is-neutral">
							{formatBranchRoleLabel(selected.branch_role, isChineseUi)}
						</span>
					) : null}
				</div>
				<details className="fa-observability-raw-toggle">
					<summary>{isChineseUi ? "查看原始输入" : "View raw input"}</summary>
					<pre>{selected.user_message || selected.task_brief || "—"}</pre>
				</details>
			</article>

			<article className="fa-trajectory-workbench-story-card">
				<div className="fa-trajectory-workbench-section-head">
					<div>
						<p>{isChineseUi ? "输出叙事" : "Output narrative"}</p>
						<h3>
							{selected.error
								? isChineseUi
									? "错误优先"
									: "Error-first readout"
								: isChineseUi
									? "关键输出"
									: "Key output"}
						</h3>
					</div>
				</div>
				<p>{resultSummary || compactSnippet(selected.answer, 560) || "—"}</p>
				{selected.error ? (
					<div className="fa-inline-notice is-danger">{selected.error}</div>
				) : null}
				<details className="fa-observability-raw-toggle">
					<summary>{isChineseUi ? "查看原始结果" : "View raw payload"}</summary>
					<pre>
						{JSON.stringify(
							{ answer: selected.answer, error: selected.error },
							null,
							2,
						)}
					</pre>
				</details>
			</article>
		</div>
	);
}

export function SupplementalContextPanel({
	isChineseUi,
	selected,
	supplementalContext,
}: {
	isChineseUi: boolean;
	selected: FocusAgentTrajectoryTurnDetail;
	supplementalContext: SupplementalContextItem[];
}) {
	return (
		<article className="fa-trajectory-workbench-context-panel">
			<div className="fa-trajectory-workbench-section-head">
				<div>
					<p>{isChineseUi ? "补充上下文" : "Supplemental context"}</p>
					<h3>
						{isChineseUi
							? "把运行画像和原始元数据收敛在一处"
							: "Keep the runtime profile and raw metadata together"}
					</h3>
				</div>
			</div>
			<div className="fa-trajectory-workbench-context-grid">
				{supplementalContext.map((item) => (
					<div key={item.id} className="fa-observability-meta-item">
						<span>{isChineseUi ? item.labelZh : item.labelEn}</span>
						<strong>{item.value}</strong>
					</div>
				))}
			</div>
			<div className="fa-trajectory-workbench-raw-stack">
				{selected.plan_meta ? (
					<details className="fa-observability-raw-toggle">
						<summary>
							{isChineseUi ? "查看 plan meta" : "View plan meta"}
						</summary>
						<pre>{JSON.stringify(selected.plan_meta, null, 2)}</pre>
					</details>
				) : null}
				{selected.reflection ? (
					<details className="fa-observability-raw-toggle">
						<summary>
							{isChineseUi ? "查看 reflection" : "View reflection"}
						</summary>
						<pre>{JSON.stringify(selected.reflection, null, 2)}</pre>
					</details>
				) : null}
				{selected.metrics ? (
					<details className="fa-observability-raw-toggle">
						<summary>{isChineseUi ? "查看 metrics" : "View metrics"}</summary>
						<pre>{JSON.stringify(selected.metrics, null, 2)}</pre>
					</details>
				) : null}
			</div>
		</article>
	);
}
