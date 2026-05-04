import type {
  FocusAgentTrajectoryStatsRow,
  FocusAgentTrajectoryTurnDetail,
} from "@focus-agent/web-sdk";

import {
  type CorrelationSignal,
  type EvidenceMode,
  type ReviewSummary,
  compactDetailQuestion,
  compactId,
  compactSnippet,
  extractStructuredSummary,
  formatBranchRoleLabel,
  formatDateTime,
  formatDuration,
  formatMetric,
  formatSceneLabel,
} from "@/features/trajectory-observability/trajectory-utils";

export type SupplementalContextItem = {
  id: string;
  labelZh: string;
  labelEn: string;
  value: string;
};

type SelectedSignalsForReview = {
  dominantTool: string;
  fallbackSteps: number;
};

type BuildTrajectoryReviewViewModelArgs = {
  correlationSignals: CorrelationSignal[];
  isChineseUi: boolean;
  locale: "zh-CN" | "en-US";
  selected: FocusAgentTrajectoryTurnDetail | null;
  selectedRequestSignal: string;
  selectedSignals: SelectedSignalsForReview;
  selectedTraceSignal: string;
  statsOverview?: FocusAgentTrajectoryStatsRow;
};

export type TrajectoryReviewViewModel = {
  correlationCoverage: number;
  evidenceMode: EvidenceMode;
  resultSummary: string;
  reviewSummary: ReviewSummary | null;
  supplementalContext: SupplementalContextItem[];
};

export function buildTrajectoryReviewViewModel({
  correlationSignals,
  isChineseUi,
  locale,
  selected,
  selectedRequestSignal,
  selectedSignals,
  selectedTraceSignal,
  statsOverview,
}: BuildTrajectoryReviewViewModelArgs): TrajectoryReviewViewModel {
  const resultSummary = selected
    ? extractStructuredSummary(selected.answer)
    : "";
  const evidenceMode: EvidenceMode = selected
    ? selected.trajectory.length > 0
      ? "timeline"
      : "zero_step"
    : "missing_detail";
  const selectedVsAverageLatency =
    selected &&
    typeof selected.latency_ms === "number" &&
    typeof statsOverview?.avg_latency_ms === "number" &&
    statsOverview.avg_latency_ms > 0
      ? selected.latency_ms / statsOverview.avg_latency_ms
      : undefined;
  const correlationCoverage = correlationSignals.filter((item) =>
    ["request", "trace", "span", "env", "deployment", "version"].includes(
      item.id,
    ),
  ).length;
  const reviewSummary = selected
    ? buildReviewSummary({
        evidenceMode,
        isChineseUi,
        locale,
        resultSummary,
        selected,
        selectedSignals,
        selectedVsAverageLatency,
      })
    : null;
  const supplementalContext = selected
    ? [
        {
          id: "scene",
          labelZh: "场景",
          labelEn: "Scene",
          value: formatSceneLabel(selected.scene, isChineseUi),
        },
        {
          id: "branch",
          labelZh: "分支角色",
          labelEn: "Branch role",
          value: formatBranchRoleLabel(selected.branch_role, isChineseUi),
        },
        {
          id: "model",
          labelZh: "模型",
          labelEn: "Model",
          value: selected.selected_model || "—",
        },
        {
          id: "thinking",
          labelZh: "思考模式",
          labelEn: "Thinking mode",
          value: selected.selected_thinking_mode || "—",
        },
        {
          id: "thread",
          labelZh: "线程",
          labelEn: "Thread",
          value: compactId(selected.thread_id),
        },
        {
          id: "request",
          labelZh: "Request",
          labelEn: "Request",
          value: compactId(selectedRequestSignal),
        },
        {
          id: "trace",
          labelZh: "Trace",
          labelEn: "Trace",
          value: compactId(selectedTraceSignal),
        },
        {
          id: "deployment",
          labelZh: "部署",
          labelEn: "Deployment",
          value: selected.deployment || selected.environment || "—",
        },
      ]
    : [];

  return {
    correlationCoverage,
    evidenceMode,
    resultSummary,
    reviewSummary,
    supplementalContext,
  };
}

type BuildReviewSummaryArgs = {
  evidenceMode: EvidenceMode;
  isChineseUi: boolean;
  locale: "zh-CN" | "en-US";
  resultSummary: string;
  selected: FocusAgentTrajectoryTurnDetail;
  selectedSignals: SelectedSignalsForReview;
  selectedVsAverageLatency?: number;
};

function buildReviewSummary({
  evidenceMode,
  isChineseUi,
  locale,
  resultSummary,
  selected,
  selectedSignals,
  selectedVsAverageLatency,
}: BuildReviewSummaryArgs): ReviewSummary {
  const lead = selected.error
    ? compactSnippet(selected.error, 220)
    : resultSummary ||
      compactSnippet(selected.answer, 220) ||
      (evidenceMode === "zero_step"
        ? isChineseUi
          ? "当前 turn 没有记录到 trajectory steps，需要直接从输入、输出和运行元数据判断问题。"
          : "This turn has no recorded trajectory steps. Read the input, output, and runtime metadata directly."
        : isChineseUi
          ? "先从证据区找异常步骤，再决定是否执行 replay。"
          : "Start from the evidence area, isolate the suspect step, then decide whether replay is necessary.");

  return {
    headline: compactDetailQuestion(
      selected.user_message || selected.task_brief || selected.id,
    ),
    lead,
    status: selected.status,
    createdAt: formatDateTime(selected.created_at, locale),
    evidenceLabel:
      evidenceMode === "timeline"
        ? isChineseUi
          ? `${selected.trajectory.length} 个步骤可复盘`
          : `${selected.trajectory.length} evidence steps available`
        : isChineseUi
          ? "零步骤证据视图"
          : "Zero-step evidence view",
    stats: [
      {
        id: "latency",
        labelZh: "延迟",
        labelEn: "Latency",
        value: formatDuration(selected.latency_ms),
      },
      {
        id: "dominant",
        labelZh: "主导工具",
        labelEn: "Dominant tool",
        value: selectedSignals.dominantTool,
      },
      {
        id: "fallback",
        labelZh: "Fallback 步骤",
        labelEn: "Fallback steps",
        value: formatMetric(selectedSignals.fallbackSteps, 0),
      },
      {
        id: "scope",
        labelZh: "相对均值",
        labelEn: "Vs average",
        value:
          selectedVsAverageLatency === undefined
            ? "—"
            : `${formatMetric(selectedVsAverageLatency, 1)}×`,
      },
    ],
  };
}
