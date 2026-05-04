import type { FocusAgentTrajectoryTurnDetail } from "@focus-agent/web-sdk";

import { TrajectoryEmptyState } from "./trajectory-states";
import type { EvidenceMode, ReviewSummary } from "./trajectory-utils";
import {
	compactDetailQuestion,
	compactSnippet,
	findStepRuntimeSignal,
	formatBranchRoleLabel,
	formatDuration,
	formatMetric,
	formatSceneLabel,
	severityClass,
	statusTone,
	stepObservationPreview,
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

function TimelineEvidence({
	isChineseUi,
	selected,
}: {
	isChineseUi: boolean;
	selected: FocusAgentTrajectoryTurnDetail;
}) {
	return (
		<div className="fa-observability-step-timeline">
			{selected.trajectory.map((step, index) => {
				const runtimeProvider = findStepRuntimeSignal(step, [
					"provider",
					"backend",
				]);
				const runtimeModel = findStepRuntimeSignal(step, [
					"model",
					"selected_model",
				]);
				const runtimeRequest = findStepRuntimeSignal(step, [
					"request_id",
					"requestId",
				]);
				const runtimeTrace = findStepRuntimeSignal(step, [
					"trace_id",
					"traceId",
					"span_id",
					"spanId",
				]);

				return (
					<div
						key={`${step.tool}-${index}`}
						className={`fa-observability-step-row ${severityClass(step)}`.trim()}
					>
						<div className="fa-observability-step-index">{index + 1}</div>
						<div className="fa-observability-step-body">
							<div className="fa-observability-step-header">
								<strong>{step.tool}</strong>
								<span>{formatDuration(step.duration_ms)}</span>
							</div>
							<div className="fa-observability-step-tags">
								{step.cache_hit ? (
									<span className="fa-observability-pill is-success">
										cache
									</span>
								) : null}
								{step.fallback_used ? (
									<span className="fa-observability-pill is-warning">
										fallback
									</span>
								) : null}
								{step.error ? (
									<span className="fa-observability-pill is-danger">error</span>
								) : null}
								{step.fallback_group ? (
									<span className="fa-observability-pill is-neutral">{`group ${step.fallback_group}`}</span>
								) : null}
								{step.parallel_batch_size ? (
									<span className="fa-observability-pill is-neutral">{`parallel ${step.parallel_batch_size}`}</span>
								) : null}
								{runtimeRequest ? (
									<span className="fa-observability-pill is-neutral">
										request
									</span>
								) : null}
								{runtimeTrace ? (
									<span className="fa-observability-pill is-neutral">
										trace
									</span>
								) : null}
							</div>
							{step.runtime ? (
								<div className="fa-observability-step-runtime">
									{runtimeProvider ? (
										<span>{`Provider · ${runtimeProvider}`}</span>
									) : null}
									{runtimeModel ? (
										<span>{`Model · ${runtimeModel}`}</span>
									) : null}
									{runtimeRequest ? (
										<span>{`Request · ${runtimeRequest}`}</span>
									) : null}
									{runtimeTrace ? (
										<span>{`Trace · ${runtimeTrace}`}</span>
									) : null}
								</div>
							) : null}
							<p className="fa-observability-step-preview">
								{stepObservationPreview(step.observation || step.error || "—")}
							</p>
							<details className="fa-observability-raw-toggle">
								<summary>
									{isChineseUi ? "查看完整观察" : "View full observation"}
								</summary>
								<pre>{step.observation || step.error || "—"}</pre>
							</details>
						</div>
					</div>
				);
			})}
		</div>
	);
}

function ZeroStepEvidence({
	correlationCoverage,
	isChineseUi,
	resultSummary,
	selected,
}: {
	correlationCoverage: number;
	isChineseUi: boolean;
	resultSummary: string;
	selected: FocusAgentTrajectoryTurnDetail;
}) {
	return (
		<div className="fa-trajectory-workbench-zero-step">
			<div className="fa-inline-notice">
				{isChineseUi
					? "这条样本没有记录到 trajectory steps，不再保留空白 timeline。改为直接展示可用证据。"
					: "This turn has no recorded trajectory steps, so the workbench switches to a compact evidence view instead of an empty timeline."}
			</div>
			<div className="fa-trajectory-workbench-zero-step-grid">
				<div className="fa-observability-detail-block">
					<h3>{isChineseUi ? "可用信号" : "Available signals"}</h3>
					<div className="fa-observability-status-strip">
						<div>
							<span>{isChineseUi ? "延迟" : "Latency"}</span>
							<strong>{formatDuration(selected.latency_ms)}</strong>
						</div>
						<div>
							<span>{isChineseUi ? "工具调用" : "Tool calls"}</span>
							<strong>{formatMetric(selected.tool_calls, 0)}</strong>
						</div>
						<div>
							<span>{isChineseUi ? "关联锚点" : "Anchors"}</span>
							<strong>{formatMetric(correlationCoverage, 0)}</strong>
						</div>
					</div>
				</div>
				<div className="fa-observability-detail-block">
					<h3>
						{selected.error
							? isChineseUi
								? "残留输出 / 错误上下文"
								: "Residual output / error context"
							: isChineseUi
								? "输出快照"
								: "Output snapshot"}
					</h3>
					<p>{resultSummary || compactSnippet(selected.answer, 360) || "—"}</p>
					<details className="fa-observability-raw-toggle">
						<summary>
							{isChineseUi ? "查看原始结果" : "View raw output"}
						</summary>
						<pre>
							{JSON.stringify(
								{ answer: selected.answer, error: selected.error },
								null,
								2,
							)}
						</pre>
					</details>
				</div>
			</div>
		</div>
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
						<summary>{isChineseUi ? "查看 plan meta" : "View plan meta"}</summary>
						<pre>{JSON.stringify(selected.plan_meta, null, 2)}</pre>
					</details>
				) : null}
				{selected.reflection ? (
					<details className="fa-observability-raw-toggle">
						<summary>{isChineseUi ? "查看 reflection" : "View reflection"}</summary>
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
