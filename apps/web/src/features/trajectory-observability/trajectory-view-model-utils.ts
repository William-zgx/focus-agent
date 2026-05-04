import type {
	FocusAgentTrajectoryStatsRow,
	FocusAgentTrajectoryStep,
	FocusAgentTrajectoryTurnDetail,
	FocusAgentTrajectoryTurnSummary,
} from "@focus-agent/web-sdk";

import {
	compactSnippet,
	extractStructuredSummary,
	formatBranchRoleLabel,
	formatSceneLabel,
} from "./trajectory-formatters";
import { findMetadataAcrossSources } from "./trajectory-metadata";
import type { CorrelationSignal, SortMode } from "./trajectory-types";

export function getDominantTool(trajectory: FocusAgentTrajectoryStep[]) {
	const counts = new Map<string, number>();
	trajectory.forEach((step) => {
		counts.set(step.tool, (counts.get(step.tool) ?? 0) + 1);
	});
	return (
		[...counts.entries()].sort((left, right) => right[1] - left[1])[0]?.[0] ??
		"—"
	);
}

export function getLongestStep(trajectory: FocusAgentTrajectoryStep[]) {
	if (!trajectory.length) return null;
	return trajectory.reduce((current, next) =>
		(next.duration_ms ?? 0) > (current.duration_ms ?? 0) ? next : current,
	);
}

export function topToolRows(
	byTool: FocusAgentTrajectoryStatsRow[] | undefined,
) {
	return [...(byTool ?? [])]
		.sort((left, right) => (right.turn_count ?? 0) - (left.turn_count ?? 0))
		.slice(0, 4);
}

export function topStatsRows(
	rows: FocusAgentTrajectoryStatsRow[] | undefined,
	limit = 4,
) {
	return [...(rows ?? [])]
		.sort((left, right) => {
			const leftCount = left.turn_count ?? left.step_count ?? 0;
			const rightCount = right.turn_count ?? right.step_count ?? 0;
			return rightCount - leftCount;
		})
		.slice(0, limit);
}

export function ratio(numerator?: number, denominator?: number) {
	if (
		typeof numerator !== "number" ||
		typeof denominator !== "number" ||
		denominator <= 0
	) {
		return undefined;
	}
	return numerator / denominator;
}

export function buildSelectedSignals(
	selected: FocusAgentTrajectoryTurnDetail | null,
) {
	if (!selected) {
		return {
			errorSteps: 0,
			fallbackSteps: 0,
			cacheSteps: 0,
			parallelSteps: 0,
			dominantTool: "—",
			longestStep: null as FocusAgentTrajectoryStep | null,
		};
	}
	const errorSteps = selected.trajectory.filter((step) =>
		Boolean(step.error),
	).length;
	const fallbackSteps = selected.trajectory.filter(
		(step) => step.fallback_used,
	).length;
	const cacheSteps = selected.trajectory.filter(
		(step) => step.cache_hit,
	).length;
	const parallelSteps = selected.trajectory.filter((step) =>
		Boolean(step.parallel_batch_size),
	).length;
	return {
		errorSteps,
		fallbackSteps,
		cacheSteps,
		parallelSteps,
		dominantTool: getDominantTool(selected.trajectory),
		longestStep: getLongestStep(selected.trajectory),
	};
}

export function buildTurnSummary(
	item: FocusAgentTrajectoryTurnSummary,
	isChineseUi: boolean,
) {
	const errorText = compactSnippet(item?.error);
	if (errorText) {
		return isChineseUi ? `错误 · ${errorText}` : `Error · ${errorText}`;
	}
	const summaryText = compactSnippet(extractStructuredSummary(item?.answer));
	if (summaryText) return summaryText;
	return isChineseUi
		? `${formatSceneLabel(item?.scene, true)} · ${item?.branch_role ? formatBranchRoleLabel(item.branch_role, true) : "未标记角色"}`
		: `${formatSceneLabel(item?.scene, false)} · ${item?.branch_role ? formatBranchRoleLabel(item.branch_role, false) : "No branch role"}`;
}

export function buildCorrelationSignals(
	selected: FocusAgentTrajectoryTurnDetail | null,
): CorrelationSignal[] {
	if (!selected) return [];

	const runtimeSources = selected.trajectory.map((step) => step.runtime);
	const metadataSources = [
		selected.plan_meta,
		selected.metrics,
		selected.reflection,
		...runtimeSources,
	];
	const requestId =
		selected.request_id ||
		findMetadataAcrossSources(metadataSources, ["request_id", "requestId"]);
	const traceId =
		selected.trace_id ||
		findMetadataAcrossSources(metadataSources, ["trace_id", "traceId"]);
	const spanId =
		selected.root_span_id ||
		findMetadataAcrossSources(metadataSources, [
			"span_id",
			"spanId",
			"root_span_id",
			"rootSpanId",
		]);
	const environment =
		selected.environment ||
		findMetadataAcrossSources(metadataSources, ["environment", "env"]);
	const deployment =
		selected.deployment ||
		findMetadataAcrossSources(metadataSources, [
			"deployment",
			"deployment_name",
		]);
	const appVersion =
		selected.app_version ||
		findMetadataAcrossSources(metadataSources, [
			"app_version",
			"appVersion",
			"version",
		]);

	return [
		{
			id: "turn",
			labelZh: "Turn ID",
			labelEn: "Turn ID",
			value: selected.id,
			tone: "accent",
		},
		{
			id: "thread",
			labelZh: "线程",
			labelEn: "Thread",
			value: selected.thread_id,
		},
		{
			id: "root",
			labelZh: "根线程",
			labelEn: "Root thread",
			value: selected.root_thread_id,
		},
		...(selected.parent_thread_id
			? [
					{
						id: "parent",
						labelZh: "父线程",
						labelEn: "Parent thread",
						value: selected.parent_thread_id,
					} satisfies CorrelationSignal,
				]
			: []),
		...(selected.branch_id
			? [
					{
						id: "branch",
						labelZh: "分支 ID",
						labelEn: "Branch ID",
						value: selected.branch_id,
					} satisfies CorrelationSignal,
				]
			: []),
		...(requestId
			? [
					{
						id: "request",
						labelZh: "Request ID",
						labelEn: "Request ID",
						value: requestId,
						tone: "accent",
					} satisfies CorrelationSignal,
				]
			: []),
		...(traceId
			? [
					{
						id: "trace",
						labelZh: "Trace ID",
						labelEn: "Trace ID",
						value: traceId,
						tone: "accent",
					} satisfies CorrelationSignal,
				]
			: []),
		...(spanId
			? [
					{
						id: "span",
						labelZh: "Span ID",
						labelEn: "Span ID",
						value: spanId,
					} satisfies CorrelationSignal,
				]
			: []),
		...(environment
			? [
					{
						id: "env",
						labelZh: "环境",
						labelEn: "Environment",
						value: environment,
					} satisfies CorrelationSignal,
				]
			: []),
		...(deployment
			? [
					{
						id: "deployment",
						labelZh: "部署",
						labelEn: "Deployment",
						value: deployment,
					} satisfies CorrelationSignal,
				]
			: []),
		...(appVersion
			? [
					{
						id: "version",
						labelZh: "版本",
						labelEn: "App version",
						value: appVersion,
					} satisfies CorrelationSignal,
				]
			: []),
	];
}

export function findCorrelationSignalValue(
	signals: CorrelationSignal[],
	id: string,
) {
	return signals.find((signal) => signal.id === id)?.value ?? "";
}

export function orderTrajectoryItems(
	items: FocusAgentTrajectoryTurnSummary[] | undefined,
	sortMode: SortMode,
) {
	const ordered = [...(items ?? [])];
	if (sortMode === "latency") {
		ordered.sort(
			(left, right) => (right.latency_ms ?? 0) - (left.latency_ms ?? 0),
		);
		return ordered;
	}
	if (sortMode === "tool_calls") {
		ordered.sort(
			(left, right) => (right.tool_calls ?? 0) - (left.tool_calls ?? 0),
		);
		return ordered;
	}
	return ordered;
}
