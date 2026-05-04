import type {
  FocusAgentTrajectoryStatsRow,
  FocusAgentTrajectoryTurnDetail,
} from "@focus-agent/web-sdk";
import { useCallback, useMemo } from "react";

import {
  type ActionRailSection,
  type CorrelationSignal,
  type SortMode,
  type StatusMode,
} from "@/features/trajectory-observability/trajectory-utils";
import { buildTrajectoryPivotActions } from "@/pages/observability/trajectory-pivot-actions";

type UseTrajectoryPageActionsArgs = {
  commandSnippet: string;
  correlationSignals: CorrelationSignal[];
  focusModel: (value: string) => void;
  focusRequest: (value: string) => void;
  focusThread: (value: string) => void;
  focusTrace: (value: string) => void;
  hottestTools: FocusAgentTrajectoryStatsRow[];
  isChineseUi: boolean;
  requestFilter: string;
  selected: FocusAgentTrajectoryTurnDetail | null;
  selectedModel: string;
  selectedRequestSignal: string;
  selectedThreadSignal: string;
  selectedTraceSignal: string;
  setFiltersExpanded: (value: boolean) => void;
  setHasErrorOnly: (value: boolean) => void;
  setRequestFilter: (value: string) => void;
  setSortMode: (value: SortMode) => void;
  setStatusFilter: (value: StatusMode) => void;
  setTraceFilter: (value: string) => void;
  traceFilter: string;
};

export function useTrajectoryPageActions({
  commandSnippet,
  correlationSignals,
  focusModel,
  focusRequest,
  focusThread,
  focusTrace,
  hottestTools,
  isChineseUi,
  requestFilter,
  selected,
  selectedModel,
  selectedRequestSignal,
  selectedThreadSignal,
  selectedTraceSignal,
  setFiltersExpanded,
  setHasErrorOnly,
  setRequestFilter,
  setSortMode,
  setStatusFilter,
  setTraceFilter,
  traceFilter,
}: UseTrajectoryPageActionsArgs) {
  const copyText = useCallback(async (value: string) => {
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      // ignore clipboard failures; the page still works without it
    }
  }, []);

  const downloadSelectedRecord = useCallback(() => {
    if (!selected) return;
    const blob = new Blob([`${JSON.stringify(selected, null, 2)}\n`], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${selected.id}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }, [selected]);

  const pivotActions = useMemo(
    () =>
      buildTrajectoryPivotActions({
        focusModel,
        focusRequest,
        focusThread,
        focusTrace,
        isChineseUi,
        requestFilter,
        selectedModel,
        selectedRequestSignal,
        selectedThreadSignal,
        selectedTraceSignal,
        setFiltersExpanded,
        setHasErrorOnly,
        setRequestFilter,
        setSortMode,
        setStatusFilter,
        setTraceFilter,
        traceFilter,
      }),
    [
      focusModel,
      focusRequest,
      focusThread,
      focusTrace,
      isChineseUi,
      requestFilter,
      selectedModel,
      selectedRequestSignal,
      selectedThreadSignal,
      selectedTraceSignal,
      setFiltersExpanded,
      setHasErrorOnly,
      setRequestFilter,
      setSortMode,
      setStatusFilter,
      setTraceFilter,
      traceFilter,
    ],
  );

  const actionRailSections = useMemo<ActionRailSection[]>(
    () => [
      {
        id: "anchors",
        titleZh: "关联锚点",
        titleEn: "Correlation hooks",
        captionZh: "把 turn、request、trace 这些交接锚点收在一起。",
        captionEn:
          "Keep turn, request, and trace anchors together for handoff.",
        count: isChineseUi
          ? `${correlationSignals.length} 项`
          : `${correlationSignals.length} signals`,
      },
      {
        id: "pivots",
        titleZh: "Pivot / 范围信号",
        titleEn: "Production pivots / scope",
        captionZh: "不离开当前复盘台，直接切范围继续看样本。",
        captionEn: "Pivot the active scope without leaving the workbench.",
      },
      {
        id: "tools",
        titleZh: "热点工具",
        titleEn: "Hot tools",
        captionZh: "用工具热点回到最值得排查的切片。",
        captionEn: "Use tool hotspots to jump back into risky slices.",
        count: isChineseUi
          ? `${hottestTools.length} 个热点`
          : `${hottestTools.length} hotspots`,
      },
      {
        id: "quick",
        titleZh: "快捷动作",
        titleEn: "Quick actions",
        captionZh: "复制 deep link、命令或下载当前样本。",
        captionEn: "Copy the deep link, CLI command, or download the turn.",
      },
      {
        id: "actions",
        titleZh: "Replay / 生成评测样本",
        titleEn: "Replay / eval sample",
        captionZh: "把动作区压成常驻操作模块，不再抢占页面主视线。",
        captionEn:
          "Keep the replay panel resident, but visually lighter than the canvas.",
      },
    ],
    [correlationSignals.length, hottestTools.length, isChineseUi],
  );

  const handleCopyLink = useCallback(() => {
    if (typeof window === "undefined") return;
    void copyText(window.location.href);
  }, [copyText]);

  const handleCopyCommand = useCallback(() => {
    void copyText(commandSnippet);
  }, [commandSnippet, copyText]);

  return {
    actionRailSections,
    copyText,
    downloadSelectedRecord,
    handleCopyCommand,
    handleCopyLink,
    pivotActions,
  };
}
