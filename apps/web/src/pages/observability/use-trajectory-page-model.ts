import type {
	FocusAgentObservabilityOverviewResponse,
	FocusAgentTrajectoryListResponse,
	FocusAgentTrajectoryTurnDetail,
} from "@focus-agent/web-sdk";
import { useMemo } from "react";

import { buildTrajectoryOverviewViewModel } from "@/features/trajectory-observability/trajectory-overview-view-model";
import { buildTrajectoryReviewViewModel } from "@/features/trajectory-observability/trajectory-review-view-model";
import {
	type FilterChip,
	type SortMode,
	buildCorrelationSignals,
	buildSelectedSignals,
	compactId,
	describeTrajectoryError,
	findCorrelationSignalValue,
	formatMetric,
	orderTrajectoryItems,
} from "@/features/trajectory-observability/trajectory-utils";

type UseTrajectoryPageModelArgs = {
	filterChips: FilterChip[];
	isChineseUi: boolean;
	isListLoading: boolean;
	isOverviewRoute: boolean;
	isStatsLoading: boolean;
	listData?: FocusAgentTrajectoryListResponse;
	listError: unknown;
	locale: "zh-CN" | "en-US";
	overviewData?: FocusAgentObservabilityOverviewResponse;
	selected: FocusAgentTrajectoryTurnDetail | null;
	selectedTurnId: string;
	sortMode: SortMode;
	statsError: unknown;
};

export function useTrajectoryPageModel({
	filterChips,
	isChineseUi,
	isListLoading,
	isOverviewRoute,
	isStatsLoading,
	listData,
	listError,
	locale,
	overviewData,
	selected,
	selectedTurnId,
	sortMode,
	statsError,
}: UseTrajectoryPageModelArgs) {
	const orderedItems = useMemo(
		() => orderTrajectoryItems(listData?.items, sortMode),
		[listData?.items, sortMode],
	);
	const commandSnippet = selectedTurnId
		? `focus-agent-trajectory show ${selectedTurnId}`
		: "";
	const matchCount = listData?.count ?? orderedItems.length;
	const trajectoryRuntimeMessage = overviewData?.trajectory_error ?? "";
	const overviewViewModel = useMemo(
		() =>
			buildTrajectoryOverviewViewModel({
				isChineseUi,
				isListLoading,
				isStatsLoading,
				matchCount,
				runtimeReadiness: overviewData?.runtime,
				stats: overviewData?.stats,
				trajectoryRuntimeMessage,
			}),
		[
			isChineseUi,
			isListLoading,
			isStatsLoading,
			matchCount,
			overviewData?.runtime,
			overviewData?.stats,
			trajectoryRuntimeMessage,
		],
	);
	const selectedSignals = useMemo(
		() => buildSelectedSignals(selected),
		[selected],
	);
	const correlationSignals = useMemo(
		() => buildCorrelationSignals(selected),
		[selected],
	);
	const selectedRequestSignal = findCorrelationSignalValue(
		correlationSignals,
		"request",
	);
	const selectedTraceSignal = findCorrelationSignalValue(
		correlationSignals,
		"trace",
	);
	const selectedThreadSignal = findCorrelationSignalValue(
		correlationSignals,
		"thread",
	);
	const selectedModel = selected?.selected_model?.trim() || "";
	const listErrorMessage = useMemo(
		() => (listError ? describeTrajectoryError(listError, isChineseUi) : ""),
		[isChineseUi, listError],
	);
	const statsErrorMessage = useMemo(
		() => (statsError ? describeTrajectoryError(statsError, isChineseUi) : ""),
		[isChineseUi, statsError],
	);
	const reviewViewModel = useMemo(
		() =>
			buildTrajectoryReviewViewModel({
				correlationSignals,
				isChineseUi,
				locale,
				selected,
				selectedRequestSignal,
				selectedSignals,
				selectedTraceSignal,
				statsOverview: overviewViewModel.statsOverview,
			}),
		[
			correlationSignals,
			isChineseUi,
			locale,
			overviewViewModel.statsOverview,
			selected,
			selectedRequestSignal,
			selectedSignals,
			selectedTraceSignal,
		],
	);
	const activeTurnLabel = isOverviewRoute
		? filterChips.length
			? isChineseUi
				? `当前范围 ${formatMetric(matchCount, 0)} 条样本 · ${filterChips.length} 个筛选生效`
				: `${formatMetric(matchCount, 0)} turns in scope · ${filterChips.length} active filters`
			: isChineseUi
				? `当前范围 ${formatMetric(matchCount, 0)} 条样本`
				: `${formatMetric(matchCount, 0)} turns in the current scope`
		: selected
			? isChineseUi
				? `当前聚焦 ${compactId(selected.id)}`
				: `Focused on ${compactId(selected.id)}`
			: isChineseUi
				? "等待选择样本"
				: "Waiting for a selected turn";

	return {
		activeTurnLabel,
		commandSnippet,
		correlationCoverage: reviewViewModel.correlationCoverage,
		correlationSignals,
		evidenceMode: reviewViewModel.evidenceMode,
		hottestTools: overviewViewModel.hottestTools,
		listErrorMessage,
		matchCount,
		orderedItems,
		overviewModelItems: overviewViewModel.byModel,
		overviewSceneItems: overviewViewModel.byScene,
		overviewSummaryMetrics: overviewViewModel.summaryMetrics,
		overviewToolItems: overviewViewModel.toolItems,
		resultSummary: reviewViewModel.resultSummary,
		reviewSummary: reviewViewModel.reviewSummary,
		runtimeLabel: overviewViewModel.runtimeLabel,
		selectedModel,
		selectedRequestSignal,
		selectedSignals,
		selectedThreadSignal,
		selectedTraceSignal,
		statsErrorMessage,
		statsOverview: overviewViewModel.statsOverview,
		supplementalContext: reviewViewModel.supplementalContext,
		trajectoryRuntimeMessage,
	};
}
