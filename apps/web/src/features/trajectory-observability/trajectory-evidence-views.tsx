import type { FocusAgentTrajectoryTurnDetail } from "@focus-agent/web-sdk";

import {
	compactSnippet,
	findStepRuntimeOutcome,
	findStepRuntimeSignal,
	formatDuration,
	formatMetric,
	outcomeTone,
	readOutcomeText,
	severityClass,
	stepObservationPreview,
} from "./trajectory-utils";

function TimelineEvidenceRow({
	index,
	isChineseUi,
	selectedStep,
}: {
	index: number;
	isChineseUi: boolean;
	selectedStep: FocusAgentTrajectoryTurnDetail["trajectory"][number];
}) {
	const runtimeProvider = findStepRuntimeSignal(selectedStep, [
		"provider",
		"backend",
	]);
	const runtimeModel = findStepRuntimeSignal(selectedStep, [
		"model",
		"selected_model",
	]);
	const runtimeRequest = findStepRuntimeSignal(selectedStep, [
		"request_id",
		"requestId",
	]);
	const runtimeTrace = findStepRuntimeSignal(selectedStep, [
		"trace_id",
		"traceId",
		"span_id",
		"spanId",
	]);
	const stepOutcome = findStepRuntimeOutcome(selectedStep);
	const outcomeStatus = readOutcomeText(stepOutcome, ["status"]);
	const outcomeErrorCategory = readOutcomeText(stepOutcome, ["error_category"]);
	const outcomeFallbackGroup = readOutcomeText(stepOutcome, ["fallback_group"]);
	const outcomeFallbackUsed = readOutcomeText(stepOutcome, ["fallback_used"]);
	const outcomeRecoveryOf = readOutcomeText(stepOutcome, [
		"recovery_of_tool_call_id",
	]);
	const outcomeAttemptIndex = readOutcomeText(stepOutcome, ["attempt_index"]);
	const outcomeMaxAttempts = readOutcomeText(stepOutcome, ["max_attempts"]);
	const outcomeAttempt =
		outcomeAttemptIndex && outcomeMaxAttempts
			? `${outcomeAttemptIndex}/${outcomeMaxAttempts}`
			: outcomeAttemptIndex;

	return (
		<div
			className={`fa-observability-step-row ${severityClass(selectedStep)}`.trim()}
		>
			<div className="fa-observability-step-index">{index + 1}</div>
			<div className="fa-observability-step-body">
				<div className="fa-observability-step-header">
					<strong>{selectedStep.tool}</strong>
					<span>{formatDuration(selectedStep.duration_ms)}</span>
				</div>
				<div className="fa-observability-step-tags">
					{selectedStep.cache_hit ? (
						<span className="fa-observability-pill is-success">cache</span>
					) : null}
					{selectedStep.fallback_used ? (
						<span className="fa-observability-pill is-warning">fallback</span>
					) : null}
					{selectedStep.error ? (
						<span className="fa-observability-pill is-danger">error</span>
					) : null}
					{selectedStep.fallback_group ? (
						<span className="fa-observability-pill is-neutral">{`group ${selectedStep.fallback_group}`}</span>
					) : null}
					{selectedStep.parallel_batch_size ? (
						<span className="fa-observability-pill is-neutral">{`parallel ${selectedStep.parallel_batch_size}`}</span>
					) : null}
					{runtimeRequest ? (
						<span className="fa-observability-pill is-neutral">request</span>
					) : null}
					{runtimeTrace ? (
						<span className="fa-observability-pill is-neutral">trace</span>
					) : null}
					{outcomeStatus ? (
						<span
							className={`fa-observability-pill is-${outcomeTone(outcomeStatus)}`}
						>{`outcome ${outcomeStatus}`}</span>
					) : null}
					{outcomeErrorCategory ? (
						<span className="fa-observability-pill is-danger">
							{outcomeErrorCategory}
						</span>
					) : null}
					{outcomeFallbackUsed === "true" && !outcomeFallbackGroup ? (
						<span className="fa-observability-pill is-warning">fallback</span>
					) : null}
					{outcomeFallbackGroup ? (
						<span className="fa-observability-pill is-warning">
							{`fallback ${outcomeFallbackGroup}`}
						</span>
					) : null}
					{outcomeRecoveryOf ? (
						<span className="fa-observability-pill is-neutral">recovered</span>
					) : null}
					{outcomeAttempt ? (
						<span className="fa-observability-pill is-neutral">
							{`attempt ${outcomeAttempt}`}
						</span>
					) : null}
				</div>
				{selectedStep.runtime ? (
					<div className="fa-observability-step-runtime">
						{runtimeProvider ? (
							<span>{`Provider · ${runtimeProvider}`}</span>
						) : null}
						{runtimeModel ? <span>{`Model · ${runtimeModel}`}</span> : null}
						{runtimeRequest ? (
							<span>{`Request · ${runtimeRequest}`}</span>
						) : null}
						{runtimeTrace ? <span>{`Trace · ${runtimeTrace}`}</span> : null}
						{outcomeRecoveryOf ? (
							<span>{`Recovered · ${outcomeRecoveryOf}`}</span>
						) : null}
					</div>
				) : null}
				<p className="fa-observability-step-preview">
					{stepObservationPreview(
						selectedStep.observation || selectedStep.error || "—",
					)}
				</p>
				<details className="fa-observability-raw-toggle">
					<summary>
						{isChineseUi ? "查看完整观察" : "View full observation"}
					</summary>
					<pre>{selectedStep.observation || selectedStep.error || "—"}</pre>
				</details>
				{stepOutcome ? (
					<details className="fa-observability-raw-toggle">
						<summary>
							{isChineseUi ? "查看 step outcome" : "View step outcome"}
						</summary>
						<pre>{JSON.stringify(stepOutcome, null, 2)}</pre>
					</details>
				) : null}
			</div>
		</div>
	);
}

export function TimelineEvidence({
	isChineseUi,
	selected,
}: {
	isChineseUi: boolean;
	selected: FocusAgentTrajectoryTurnDetail;
}) {
	return (
		<div className="fa-observability-step-timeline">
			{selected.trajectory.map((step, index) => (
				<TimelineEvidenceRow
					index={index}
					isChineseUi={isChineseUi}
					key={`${step.tool}-${index}`}
					selectedStep={step}
				/>
			))}
		</div>
	);
}

export function ZeroStepEvidence({
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
