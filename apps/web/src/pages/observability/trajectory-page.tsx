import {
  FocusAgentRequestError,
  type FocusAgentTrajectoryListRequest,
} from "@focus-agent/web-sdk";
import { useRouterState } from "@tanstack/react-router";
import {
  startTransition,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { useShellUi } from "@/app/shell/shell-ui-context";
import { TrajectoryActionRail } from "@/features/trajectory-observability/trajectory-action-rail";
import { TrajectoryDetailPanel } from "@/features/trajectory-observability/trajectory-detail-panel";
import { TrajectoryFiltersPanel } from "@/features/trajectory-observability/trajectory-filters-panel";
import { TrajectoryOverviewDashboard } from "@/features/trajectory-observability/trajectory-overview-dashboard";
import { TrajectorySampleExplorer } from "@/features/trajectory-observability/trajectory-sample-explorer";
import {
  TrajectoryEmptyState,
  TrajectoryInlineError,
} from "@/features/trajectory-observability/trajectory-states";
import { TrajectoryWorkbenchHeader } from "@/features/trajectory-observability/trajectory-workbench-header";
import {
  type ActionRailSection,
  type EvidenceMode,
  type PresetMode,
  type ReviewSummary,
  type SortMode,
  type StatusMode,
  buildCorrelationSignals,
  buildFilterChips,
  buildSelectedSignals,
  compactDetailQuestion,
  compactId,
  compactSnippet,
  describeTrajectoryError,
  extractStructuredSummary,
  findCorrelationSignalValue,
  formatBranchRoleLabel,
  formatDateTime,
  formatDuration,
  formatMetric,
  formatPercent,
  formatSceneLabel,
  normalizeStatusFilter,
  orderTrajectoryItems,
  parseNonNegativeNumber,
  ratio,
  readInitialSearchParam,
  readSearchFlag,
  readSearchParam,
  readSearchSort,
  readSearchState,
  readSearchStatus,
  shouldExpandFiltersFromSearch,
  topStatsRows,
  topToolRows,
} from "@/features/trajectory-observability/trajectory-utils";
import { useObservabilityOverview } from "@/features/trajectory-observability/use-observability-overview";
import { useTrajectoryDetail } from "@/features/trajectory-observability/use-trajectory-detail";
import { useTrajectoryList } from "@/features/trajectory-observability/use-trajectory-list";

export function TrajectoryPage() {
  const { isChineseUi } = useShellUi();
  const { isOverviewRoute, routerSearch } = useRouterState({
    select: (state) => ({
      isOverviewRoute: state.location.pathname.endsWith(
        "/observability/overview",
      ),
      routerSearch: state.location.search,
    }),
  });
  const locale = isChineseUi ? "zh-CN" : "en-US";
  const detailPanelRef = useRef<HTMLElement | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusMode>(() =>
    readSearchStatus(),
  );
  const [toolFilter, setToolFilter] = useState(() => readSearchParam("tool"));
  const [threadFilter, setThreadFilter] = useState(() =>
    readSearchParam("thread"),
  );
  const [requestFilter, setRequestFilter] = useState(() =>
    readInitialSearchParam("request"),
  );
  const [traceFilter, setTraceFilter] = useState(() =>
    readInitialSearchParam("trace"),
  );
  const [modelFilter, setModelFilter] = useState(() =>
    readSearchParam("model"),
  );
  const [minLatency, setMinLatency] = useState(() =>
    readSearchParam("minLatency"),
  );
  const [fallbackOnly, setFallbackOnly] = useState(() =>
    readSearchFlag("fallbackOnly", false),
  );
  const [hasErrorOnly, setHasErrorOnly] = useState(() =>
    readSearchFlag("hasErrorOnly", false),
  );
  const [sortMode, setSortMode] = useState<SortMode>(() => readSearchSort());
  const [selectedTurnId, setSelectedTurnId] = useState(() =>
    readSearchParam("turn"),
  );
  const [selectedBatchTurnIds, setSelectedBatchTurnIds] = useState<string[]>(
    [],
  );
  const [filtersExpanded, setFiltersExpanded] = useState(() =>
    shouldExpandFiltersFromSearch(),
  );

  useEffect(() => {
    const searchState = readSearchState(routerSearch);
    const shouldExpand = shouldExpandFiltersFromSearch(routerSearch);

    setStatusFilter((current) =>
      current === searchState.statusFilter ? current : searchState.statusFilter,
    );
    setToolFilter((current) =>
      current === searchState.toolFilter ? current : searchState.toolFilter,
    );
    setThreadFilter((current) =>
      current === searchState.threadFilter
        ? current
        : searchState.threadFilter,
    );
    setRequestFilter((current) =>
      current === searchState.requestFilter
        ? current
        : searchState.requestFilter,
    );
    setTraceFilter((current) =>
      current === searchState.traceFilter ? current : searchState.traceFilter,
    );
    setModelFilter((current) =>
      current === searchState.modelFilter ? current : searchState.modelFilter,
    );
    setMinLatency((current) =>
      current === searchState.minLatency ? current : searchState.minLatency,
    );
    setFallbackOnly((current) =>
      current === searchState.fallbackOnly ? current : searchState.fallbackOnly,
    );
    setHasErrorOnly((current) =>
      current === searchState.hasErrorOnly ? current : searchState.hasErrorOnly,
    );
    setSortMode((current) =>
      current === searchState.sortMode ? current : searchState.sortMode,
    );
    setSelectedTurnId((current) =>
      current === searchState.selectedTurnId
        ? current
        : searchState.selectedTurnId,
    );
    setFiltersExpanded((current) =>
      current === shouldExpand ? current : shouldExpand,
    );
  }, [routerSearch]);

  const parsedMinLatency = useMemo(
    () => parseNonNegativeNumber(minLatency),
    [minLatency],
  );
  const hasInvalidLatency =
    minLatency.trim() !== "" && parsedMinLatency === undefined;

  const filters = useMemo<FocusAgentTrajectoryListRequest>(
    () => ({
      status: normalizeStatusFilter(statusFilter),
      tool: toolFilter.trim() ? [toolFilter.trim()] : undefined,
      thread_id: threadFilter.trim() || undefined,
      request_id: requestFilter.trim() || undefined,
      trace_id: traceFilter.trim() || undefined,
      model: modelFilter.trim() ? [modelFilter.trim()] : undefined,
      min_latency_ms: parsedMinLatency,
      fallback_used: fallbackOnly || undefined,
      has_error: hasErrorOnly || undefined,
      limit: 80,
    }),
    [
      fallbackOnly,
      hasErrorOnly,
      modelFilter,
      parsedMinLatency,
      requestFilter,
      statusFilter,
      threadFilter,
      toolFilter,
      traceFilter,
    ],
  );
  const deferredFilters = useDeferredValue(filters);
  const {
    data: listData,
    isLoading: isListLoading,
    error: listError,
  } = useTrajectoryList(deferredFilters);
  const {
    data: overviewData,
    isLoading: isStatsLoading,
    error: statsError,
  } = useObservabilityOverview({
    ...deferredFilters,
  });
  const statsData = overviewData;

  const orderedItems = useMemo(
    () => orderTrajectoryItems(listData?.items, sortMode),
    [listData?.items, sortMode],
  );
  const orderedItemIds = useMemo(
    () => new Set(orderedItems.map((item) => item.id)),
    [orderedItems],
  );
  const selectedBatchItems = useMemo(
    () => orderedItems.filter((item) => selectedBatchTurnIds.includes(item.id)),
    [orderedItems, selectedBatchTurnIds],
  );
  const selectedBatchIdSet = useMemo(
    () => new Set(selectedBatchTurnIds),
    [selectedBatchTurnIds],
  );

  useEffect(() => {
    if (!orderedItems.length) {
      if (isListLoading || listError) {
        return;
      }
      setSelectedTurnId("");
      return;
    }
    if (orderedItems.some((item) => item.id === selectedTurnId)) return;
    startTransition(() => {
      setSelectedTurnId(orderedItems[0].id);
    });
  }, [isListLoading, listError, orderedItems, selectedTurnId]);

  useEffect(() => {
    setSelectedBatchTurnIds((current) =>
      current.filter((turnId) => orderedItemIds.has(turnId)),
    );
  }, [orderedItemIds]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const url = new URL(window.location.href);
    const params = url.searchParams;
    const assign = (
      key: string,
      value: string | boolean,
      defaultValue?: string | boolean,
    ) => {
      const normalized =
        typeof value === "boolean" ? (value ? "1" : "") : value.trim();
      const normalizedDefault =
        defaultValue === undefined
          ? undefined
          : typeof defaultValue === "boolean"
            ? defaultValue
              ? "1"
              : ""
            : defaultValue.trim();
      if (!normalized || normalized === normalizedDefault) {
        params.delete(key);
        return;
      }
      params.set(key, normalized);
    };

    assign("status", statusFilter, "all");
    assign("tool", toolFilter);
    assign("thread", threadFilter);
    assign("request", requestFilter);
    assign("trace", traceFilter);
    assign("model", modelFilter);
    assign("minLatency", hasInvalidLatency ? "" : minLatency);
    assign("fallbackOnly", fallbackOnly);
    assign("hasErrorOnly", hasErrorOnly);
    assign("sort", sortMode, "newest");
    assign("turn", selectedTurnId);
    const query = params.toString();
    const nextHref = `${url.pathname}${query ? `?${query}` : ""}${url.hash}`;
    if (nextHref !== `${url.pathname}${url.search}${url.hash}`) {
      window.history.replaceState({}, "", nextHref);
    }
  }, [
    fallbackOnly,
    hasInvalidLatency,
    hasErrorOnly,
    minLatency,
    modelFilter,
    requestFilter,
    selectedTurnId,
    sortMode,
    statusFilter,
    threadFilter,
    toolFilter,
    traceFilter,
  ]);

  useEffect(() => {
    detailPanelRef.current?.scrollTo({ top: 0, behavior: "auto" });
  }, [selectedTurnId]);

  const { data: detailData, isLoading: isDetailLoading } =
    useTrajectoryDetail(selectedTurnId);
  const selected = detailData?.item ?? null;
  const commandSnippet = selectedTurnId
    ? `focus-agent-trajectory show ${selectedTurnId}`
    : "";
  const matchCount = listData?.count ?? orderedItems.length;
  const resultSummary = selected
    ? extractStructuredSummary(selected.answer)
    : "";
  const statsOverview = statsData?.stats.overview;
  const runtimeReadiness = overviewData?.runtime;
  const filterChips = useMemo(
    () =>
      buildFilterChips({
        statusFilter,
        toolFilter,
        threadFilter,
        requestFilter,
        traceFilter,
        modelFilter,
        minLatency,
        fallbackOnly,
        hasErrorOnly,
        sortMode,
        clearStatus: () => setStatusFilter("all"),
        clearTool: () => setToolFilter(""),
        clearThread: () => setThreadFilter(""),
        clearRequest: () => setRequestFilter(""),
        clearTrace: () => setTraceFilter(""),
        clearModel: () => setModelFilter(""),
        clearLatency: () => setMinLatency(""),
        clearFallback: () => setFallbackOnly(false),
        clearErrorOnly: () => setHasErrorOnly(false),
        clearSort: () => setSortMode("newest"),
      }),
    [
      fallbackOnly,
      hasErrorOnly,
      minLatency,
      modelFilter,
      requestFilter,
      sortMode,
      statusFilter,
      threadFilter,
      toolFilter,
      traceFilter,
    ],
  );
  const selectedSignals = useMemo(
    () => buildSelectedSignals(selected),
    [selected],
  );
  const hottestTools = useMemo(
    () => topToolRows(statsData?.stats.by_tool),
    [statsData?.stats.by_tool],
  );
  const hottestScenes = useMemo(
    () => topStatsRows(statsData?.stats.by_scene, 4),
    [statsData?.stats.by_scene],
  );
  const hottestModels = useMemo(
    () => topStatsRows(statsData?.stats.by_model, 4),
    [statsData?.stats.by_model],
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
  const trajectoryRuntimeMessage = overviewData?.trajectory_error ?? "";
  const failureRate =
    statsOverview && (statsOverview.turn_count ?? 0) > 0
      ? (statsOverview.non_succeeded_count ?? 0) /
        (statsOverview.turn_count ?? 0)
      : undefined;
  const toolsPerTurn =
    statsOverview && (statsOverview.turn_count ?? 0) > 0
      ? (statsOverview.total_tool_calls ?? 0) / (statsOverview.turn_count ?? 0)
      : undefined;
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
  const overviewSummaryMetrics = useMemo(
    () => [
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
    ],
    [failureRate, isListLoading, isStatsLoading, matchCount, statsOverview, toolsPerTurn],
  );
  const overviewSceneItems = useMemo(
    () =>
      hottestScenes.map((row) => ({
        id: String(row.key ?? "scene"),
        title: formatSceneLabel(String(row.key ?? "unknown"), isChineseUi),
        meta: isChineseUi
          ? `${formatMetric(row.turn_count, 0)} 条样本 · ${formatDuration(row.avg_latency_ms)}`
          : `${formatMetric(row.turn_count, 0)} turns · ${formatDuration(row.avg_latency_ms)}`,
        value: formatPercent(ratio(row.non_succeeded_count, row.turn_count)),
      })),
    [hottestScenes, isChineseUi],
  );
  const overviewModelItems = useMemo(
    () =>
      hottestModels.map((row) => ({
        id: String(row.key ?? "model"),
        title: String(row.key ?? "unknown"),
        meta: isChineseUi
          ? `${formatMetric(row.turn_count, 0)} 条样本 · ${formatDuration(row.avg_latency_ms)}`
          : `${formatMetric(row.turn_count, 0)} turns · ${formatDuration(row.avg_latency_ms)}`,
        value: formatPercent(ratio(row.non_succeeded_count, row.turn_count)),
      })),
    [hottestModels, isChineseUi],
  );
  const overviewToolItems = useMemo(
    () =>
      hottestTools.map((row) => ({
        id: String(row.key ?? "tool"),
        title: String(row.key ?? "unknown"),
        meta: isChineseUi
          ? `${formatMetric(row.turn_count, 0)} 条样本 · ${formatDuration(row.avg_duration_ms)}`
          : `${formatMetric(row.turn_count, 0)} turns · ${formatDuration(row.avg_duration_ms)}`,
        value: formatPercent(ratio(row.fallback_steps, row.step_count)),
      })),
    [hottestTools, isChineseUi],
  );
  const runtimeLabel = useMemo(() => {
    if (trajectoryRuntimeMessage) {
      return compactSnippet(trajectoryRuntimeMessage, 92);
    }
    const parts = [
      runtimeReadiness?.status ?? (isChineseUi ? "就绪" : "Ready"),
      runtimeReadiness?.environment || runtimeReadiness?.deployment || "",
    ].filter(Boolean);
    return parts.join(" · ");
  }, [isChineseUi, runtimeReadiness, trajectoryRuntimeMessage]);
  const evidenceMode: EvidenceMode = selected
    ? selected.trajectory.length > 0
      ? "timeline"
      : "zero_step"
    : "missing_detail";
  const reviewSummary = useMemo<ReviewSummary | null>(() => {
    if (!selected) return null;
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
  }, [
    evidenceMode,
    isChineseUi,
    locale,
    resultSummary,
    selected,
    selectedSignals.dominantTool,
    selectedSignals.fallbackSteps,
    selectedVsAverageLatency,
  ]);

  async function copyText(value: string) {
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      // ignore clipboard failures; the page still works without it
    }
  }

  function downloadSelectedRecord() {
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
  }

  function applyPreset(preset: PresetMode) {
    if (preset === "failures") {
      setStatusFilter("failed");
      setFallbackOnly(false);
      setHasErrorOnly(true);
      setMinLatency("500");
      setSortMode("newest");
      return;
    }
    if (preset === "fallback") {
      setStatusFilter("failed");
      setFallbackOnly(true);
      setHasErrorOnly(false);
      setMinLatency("");
      setSortMode("newest");
      return;
    }
    if (preset === "latency") {
      setStatusFilter("all");
      setFallbackOnly(false);
      setHasErrorOnly(false);
      setMinLatency("1500");
      setSortMode("latency");
      return;
    }
    setStatusFilter("all");
    setFallbackOnly(false);
    setHasErrorOnly(false);
    setMinLatency("");
    setSortMode("newest");
  }

  function resetFilters() {
    setStatusFilter("all");
    setToolFilter("");
    setThreadFilter("");
    setRequestFilter("");
    setTraceFilter("");
    setModelFilter("");
    setMinLatency("");
    setFallbackOnly(false);
    setHasErrorOnly(false);
    setSortMode("newest");
  }

  function toggleBatchSelection(turnId: string) {
    setSelectedBatchTurnIds((current) =>
      current.includes(turnId)
        ? current.filter((item) => item !== turnId)
        : [...current, turnId],
    );
  }

  function selectVisibleBatch() {
    setSelectedBatchTurnIds(orderedItems.map((item) => item.id));
  }

  function selectVisibleFailuresBatch() {
    setSelectedBatchTurnIds(
      orderedItems
        .filter((item) => item.status !== "succeeded" || item.error)
        .map((item) => item.id),
    );
  }

  function clearBatchSelection() {
    setSelectedBatchTurnIds([]);
  }

  function focusRequest(value: string) {
    const normalized = value.trim();
    if (!normalized) return;
    setRequestFilter(normalized);
    setFiltersExpanded(true);
  }

  function focusTrace(value: string) {
    const normalized = value.trim();
    if (!normalized) return;
    setTraceFilter(normalized);
    setFiltersExpanded(true);
  }

  function focusThread(value: string) {
    const normalized = value.trim();
    if (!normalized) return;
    setThreadFilter(normalized);
    setFiltersExpanded(true);
  }

  function focusModel(value: string) {
    const normalized = value.trim();
    if (!normalized) return;
    setModelFilter(normalized);
    setFiltersExpanded(true);
  }

  const pivotActions = [
    {
      id: "request",
      label: isChineseUi ? "锁定同一 Request" : "Lock same request",
      caption:
        selectedRequestSignal ||
        (isChineseUi
          ? "当前样本没有 request_id"
          : "No request_id on this turn"),
      disabled: !selectedRequestSignal,
      action: () => focusRequest(selectedRequestSignal),
    },
    {
      id: "trace",
      label: isChineseUi ? "锁定同一 Trace" : "Lock same trace",
      caption:
        selectedTraceSignal ||
        (isChineseUi ? "当前样本没有 trace_id" : "No trace_id on this turn"),
      disabled: !selectedTraceSignal,
      action: () => focusTrace(selectedTraceSignal),
    },
    {
      id: "thread",
      label: isChineseUi ? "只看同一线程" : "Same thread only",
      caption:
        selectedThreadSignal ||
        (isChineseUi
          ? "当前样本没有线程锚点"
          : "No thread anchor on this turn"),
      disabled: !selectedThreadSignal,
      action: () => focusThread(selectedThreadSignal),
    },
    {
      id: "model",
      label: isChineseUi ? "切到同一模型" : "Same model slice",
      caption:
        selectedModel ||
        (isChineseUi
          ? "当前样本没有模型信息"
          : "No model captured on this turn"),
      disabled: !selectedModel,
      action: () => focusModel(selectedModel),
    },
    {
      id: "failures",
      label: isChineseUi ? "当前范围仅看失败" : "Failures in scope",
      caption: isChineseUi
        ? "保留当前 request/trace/thread 等锚点，只切失败样本"
        : "Keep active anchors, then pivot to non-succeeded turns only",
      disabled: false,
      action: () => {
        setStatusFilter("failed");
        setHasErrorOnly(true);
        setSortMode("newest");
        setFiltersExpanded(true);
      },
    },
    {
      id: "clear",
      label: isChineseUi
        ? "清除 request/trace 锁定"
        : "Clear request/trace pivots",
      caption:
        requestFilter.trim() || traceFilter.trim()
          ? [requestFilter.trim(), traceFilter.trim()]
              .filter(Boolean)
              .map(compactId)
              .join(" · ")
          : isChineseUi
            ? "当前没有 request/trace 锁定"
            : "No request/trace pivot active",
      disabled: !requestFilter.trim() && !traceFilter.trim(),
      action: () => {
        setRequestFilter("");
        setTraceFilter("");
      },
    },
  ];

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
  const supplementalContext = useMemo(
    () =>
      selected
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
        : [],
    [
      isChineseUi,
      selected,
      selectedRequestSignal,
      selectedTraceSignal,
    ],
  );

  function handleCopyLink() {
    if (typeof window === "undefined") return;
    void copyText(window.location.href);
  }

  function handleCopyCommand() {
    void copyText(commandSnippet);
  }

  return (
    <div
      className={`fa-observability-layout ${isOverviewRoute ? "is-overview-route" : "is-workbench-route"}`.trim()}
    >
      {/* Legacy route-tab styling remains mapped through the shared header component: fa-observability-route-tabs / fa-observability-route-tab. */}
      <TrajectoryWorkbenchHeader
        activeTurnLabel={activeTurnLabel}
        commandSnippet={commandSnippet}
        isChineseUi={isChineseUi}
        isOverviewRoute={isOverviewRoute}
        onCopyCommand={handleCopyCommand}
        onCopyLink={handleCopyLink}
      />

      {statsErrorMessage ? (
        <div className="fa-inline-notice is-warning">{statsErrorMessage}</div>
      ) : null}
      {trajectoryRuntimeMessage ? (
        <div className="fa-inline-notice is-warning">
          {trajectoryRuntimeMessage}
        </div>
      ) : null}

      {isOverviewRoute ? (
        <TrajectoryOverviewDashboard
          byModel={overviewModelItems}
          byScene={overviewSceneItems}
          hottestTools={overviewToolItems}
          isChineseUi={isChineseUi}
          onSelectTool={(tool) => {
            setToolFilter((current) => (current === tool ? "" : tool));
            setFiltersExpanded(true);
          }}
          runtimeLabel={runtimeLabel}
          summaryMetrics={overviewSummaryMetrics}
          toolFilter={toolFilter}
        />
      ) : (
        <section className="fa-trajectory-workbench-shell">
          <aside className="fa-trajectory-workbench-column is-explorer">
            <TrajectorySampleExplorer
              isChineseUi={isChineseUi}
              isListLoading={isListLoading}
              items={orderedItems}
              locale={locale}
              matchCount={matchCount}
              onClearBatchSelection={clearBatchSelection}
              onSelectTurn={setSelectedTurnId}
              onSelectVisibleBatch={selectVisibleBatch}
              onSelectVisibleFailuresBatch={selectVisibleFailuresBatch}
              onToggleBatchSelection={toggleBatchSelection}
              selectedBatchIdSet={selectedBatchIdSet}
              selectedBatchTurnIds={selectedBatchTurnIds}
              selectedTurnId={selectedTurnId}
            >
              {!isListLoading && !orderedItems.length ? (
                <TrajectoryEmptyState
                  isChineseUi={isChineseUi}
                  kind="no-results"
                  onApplyAllPreset={() => applyPreset("all")}
                  onResetFilters={resetFilters}
                />
              ) : null}
              {listError ? (
                <TrajectoryInlineError
                  isWarning={
                    listError instanceof FocusAgentRequestError &&
                    listError.status === 503
                  }
                  message={listErrorMessage}
                />
              ) : null}
            </TrajectorySampleExplorer>

            <TrajectoryFiltersPanel
              fallbackOnly={fallbackOnly}
              filterChips={filterChips}
              filtersExpanded={filtersExpanded}
              hasErrorOnly={hasErrorOnly}
              hasInvalidLatency={hasInvalidLatency}
              isChineseUi={isChineseUi}
              minLatency={minLatency}
              modelFilter={modelFilter}
              onApplyPreset={applyPreset}
              onResetFilters={resetFilters}
              requestFilter={requestFilter}
              setFallbackOnly={setFallbackOnly}
              setFiltersExpanded={setFiltersExpanded}
              setHasErrorOnly={setHasErrorOnly}
              setMinLatency={setMinLatency}
              setModelFilter={setModelFilter}
              setRequestFilter={setRequestFilter}
              setSortMode={setSortMode}
              setStatusFilter={setStatusFilter}
              setThreadFilter={setThreadFilter}
              setToolFilter={setToolFilter}
              setTraceFilter={setTraceFilter}
              sortMode={sortMode}
              statusFilter={statusFilter}
              threadFilter={threadFilter}
              toolFilter={toolFilter}
              traceFilter={traceFilter}
            />
          </aside>

          <section
            className="fa-trajectory-workbench-column is-canvas"
            ref={detailPanelRef}
          >
            <TrajectoryDetailPanel
              correlationCoverage={correlationCoverage}
              evidenceMode={evidenceMode}
              isChineseUi={isChineseUi}
              isDetailLoading={isDetailLoading}
              resultSummary={resultSummary}
              reviewSummary={reviewSummary}
              selected={selected}
              selectedSignals={selectedSignals}
              selectedTurnId={selectedTurnId}
              supplementalContext={supplementalContext}
            />
          </section>

          <aside className="fa-trajectory-workbench-column is-rail">
            <TrajectoryActionRail
              actionRailSections={actionRailSections}
              batchItems={selectedBatchItems}
              commandSnippet={commandSnippet}
              correlationCoverage={correlationCoverage}
              correlationSignals={correlationSignals}
              hottestTools={hottestTools}
              isChineseUi={isChineseUi}
              isStatsLoading={isStatsLoading}
              onClearBatchSelection={clearBatchSelection}
              onCopyCommand={handleCopyCommand}
              onCopyLink={handleCopyLink}
              onCopyText={(value) => void copyText(value)}
              onDownloadSelectedRecord={downloadSelectedRecord}
              onSetToolFilter={setToolFilter}
              pivotActions={pivotActions}
              selected={selected}
              statsOverview={statsOverview}
              toolFilter={toolFilter}
            />
          </aside>
        </section>
      )}
    </div>
  );
}
