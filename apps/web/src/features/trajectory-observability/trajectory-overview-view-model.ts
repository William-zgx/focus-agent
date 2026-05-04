import type {
  FocusAgentRuntimeReadiness,
  FocusAgentTrajectoryStats,
  FocusAgentTrajectoryStatsRow,
} from "@focus-agent/web-sdk";

import {
  compactSnippet,
  formatDuration,
  formatMetric,
  formatPercent,
  formatSceneLabel,
  ratio,
  topStatsRows,
  topToolRows,
} from "@/features/trajectory-observability/trajectory-utils";

export type OverviewMetric = {
  labelEn: string;
  labelZh: string;
  value: string;
};

export type OverviewListItem = {
  id: string;
  meta: string;
  title: string;
  value: string;
};

type BuildTrajectoryOverviewViewModelArgs = {
  isChineseUi: boolean;
  isListLoading: boolean;
  isStatsLoading: boolean;
  matchCount: number;
  runtimeReadiness?: FocusAgentRuntimeReadiness;
  stats?: FocusAgentTrajectoryStats;
  trajectoryRuntimeMessage?: string | null;
};

export type TrajectoryOverviewViewModel = {
  byModel: OverviewListItem[];
  byScene: OverviewListItem[];
  hottestTools: FocusAgentTrajectoryStatsRow[];
  runtimeLabel: string;
  statsOverview?: FocusAgentTrajectoryStatsRow;
  summaryMetrics: OverviewMetric[];
  toolItems: OverviewListItem[];
};

export function buildTrajectoryOverviewViewModel({
  isChineseUi,
  isListLoading,
  isStatsLoading,
  matchCount,
  runtimeReadiness,
  stats,
  trajectoryRuntimeMessage,
}: BuildTrajectoryOverviewViewModelArgs): TrajectoryOverviewViewModel {
  const statsOverview = stats?.overview;
  const hottestTools = topToolRows(stats?.by_tool);
  const hottestScenes = topStatsRows(stats?.by_scene, 4);
  const hottestModels = topStatsRows(stats?.by_model, 4);
  const failureRate =
    statsOverview && (statsOverview.turn_count ?? 0) > 0
      ? (statsOverview.non_succeeded_count ?? 0) /
        (statsOverview.turn_count ?? 0)
      : undefined;
  const toolsPerTurn =
    statsOverview && (statsOverview.turn_count ?? 0) > 0
      ? (statsOverview.total_tool_calls ?? 0) / (statsOverview.turn_count ?? 0)
      : undefined;
  const summaryMetrics = [
    {
      labelZh: "当前匹配",
      labelEn: "Matched turns",
      value: isListLoading ? "…" : formatMetric(matchCount, 0),
    },
    {
      labelZh: "失败率",
      labelEn: "Failure rate",
      value: isStatsLoading ? "…" : formatPercent(failureRate),
    },
    {
      labelZh: "平均延迟",
      labelEn: "Avg latency",
      value: isStatsLoading
        ? "…"
        : formatDuration(statsOverview?.avg_latency_ms),
    },
    {
      labelZh: "工具 / 样本",
      labelEn: "Tools / turn",
      value: isStatsLoading ? "…" : formatMetric(toolsPerTurn, 1),
    },
  ];
  const byScene = hottestScenes.map((row) => ({
    id: String(row.key ?? "scene"),
    title: formatSceneLabel(String(row.key ?? "unknown"), isChineseUi),
    meta: isChineseUi
      ? `${formatMetric(row.turn_count, 0)} 条样本 · ${formatDuration(row.avg_latency_ms)}`
      : `${formatMetric(row.turn_count, 0)} turns · ${formatDuration(row.avg_latency_ms)}`,
    value: formatPercent(ratio(row.non_succeeded_count, row.turn_count)),
  }));
  const byModel = hottestModels.map((row) => ({
    id: String(row.key ?? "model"),
    title: String(row.key ?? "unknown"),
    meta: isChineseUi
      ? `${formatMetric(row.turn_count, 0)} 条样本 · ${formatDuration(row.avg_latency_ms)}`
      : `${formatMetric(row.turn_count, 0)} turns · ${formatDuration(row.avg_latency_ms)}`,
    value: formatPercent(ratio(row.non_succeeded_count, row.turn_count)),
  }));
  const toolItems = hottestTools.map((row) => ({
    id: String(row.key ?? "tool"),
    title: String(row.key ?? "unknown"),
    meta: isChineseUi
      ? `${formatMetric(row.turn_count, 0)} 条样本 · ${formatDuration(row.avg_duration_ms)}`
      : `${formatMetric(row.turn_count, 0)} turns · ${formatDuration(row.avg_duration_ms)}`,
    value: formatPercent(ratio(row.fallback_steps, row.step_count)),
  }));
  const runtimeLabel = trajectoryRuntimeMessage
    ? compactSnippet(trajectoryRuntimeMessage, 92)
    : [
        runtimeReadiness?.status ?? (isChineseUi ? "就绪" : "Ready"),
        runtimeReadiness?.environment || runtimeReadiness?.deployment || "",
      ]
        .filter(Boolean)
        .join(" · ");

  return {
    byModel,
    byScene,
    hottestTools,
    runtimeLabel,
    statsOverview,
    summaryMetrics,
    toolItems,
  };
}
