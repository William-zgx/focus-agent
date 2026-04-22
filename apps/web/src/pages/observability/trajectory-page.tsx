import {
  FocusAgentRequestError,
  type FocusAgentTrajectoryListRequest,
  type FocusAgentTrajectoryStatsRow,
  type FocusAgentTrajectoryStep,
  type FocusAgentTrajectoryTurnDetail,
  type FocusAgentTrajectoryTurnSummary,
} from "@focus-agent/web-sdk";
import { Link, useRouterState } from "@tanstack/react-router";
import { startTransition, useDeferredValue, useEffect, useMemo, useRef, useState } from "react";

import { useShellUi } from "@/app/shell/shell-ui-context";
import { TrajectoryActionPanel } from "@/features/trajectory-observability/trajectory-action-panel";
import { useObservabilityOverview } from "@/features/trajectory-observability/use-observability-overview";
import { useTrajectoryDetail } from "@/features/trajectory-observability/use-trajectory-detail";
import { useTrajectoryList } from "@/features/trajectory-observability/use-trajectory-list";

type SortMode = "newest" | "latency" | "tool_calls";
type StatusMode = "all" | "failed" | "succeeded";
type PresetMode = "failures" | "fallback" | "latency" | "all";
type FilterChip = {
  id: string;
  labelZh: string;
  labelEn: string;
  clear: () => void;
};
type CorrelationSignal = {
  id: string;
  labelZh: string;
  labelEn: string;
  value: string;
  tone?: "neutral" | "accent";
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function readInitialSearchParam(key: string) {
  if (typeof window === "undefined") return "";
  return new URLSearchParams(window.location.search).get(key) ?? "";
}

function readInitialFlag(key: string, fallback = false) {
  const value = readInitialSearchParam(key);
  if (!value) return fallback;
  return value === "1" || value === "true";
}

function readInitialStatus(): StatusMode {
  const value = readInitialSearchParam("status");
  if (value === "all" || value === "failed" || value === "succeeded") return value;
  return "all";
}

function readInitialSort(): SortMode {
  const value = readInitialSearchParam("sort");
  if (value === "newest" || value === "latency" || value === "tool_calls") return value;
  return "newest";
}

function parseNonNegativeNumber(value: string) {
  const text = value.trim();
  if (!text) return undefined;
  const parsed = Number(text);
  if (!Number.isFinite(parsed) || parsed < 0) return undefined;
  return parsed;
}

function describeTrajectoryError(error: unknown, isChineseUi: boolean) {
  if (error instanceof FocusAgentRequestError) {
    if (error.status === 503) {
      return isChineseUi
        ? "当前环境还没有启用 Trajectory observability 后端。请先配置 Postgres trajectory 存储，或在支持该能力的环境里打开复盘台。"
        : "Trajectory observability is not available in this environment yet. Configure the Postgres-backed trajectory store, or open this page in an environment where observability is enabled.";
    }
    if (error.status === 401 || error.status === 403) {
      return isChineseUi
        ? "当前账号没有访问复盘台数据的权限。请先确认登录状态和 Bearer Token。"
        : "Your current account cannot access trajectory data. Check the active login session and bearer token first.";
    }
    return isChineseUi
      ? `复盘台数据请求失败（${error.status} ${error.statusText}）。`
      : `Trajectory request failed (${error.status} ${error.statusText}).`;
  }
  return isChineseUi
    ? "复盘台数据加载失败，请稍后重试。"
    : "Failed to load trajectory data. Please retry in a moment.";
}

function formatDateTime(value?: string | null, locale: "zh-CN" | "en-US" = "en-US") {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat(locale, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parsed);
}

function formatMetric(value: number | undefined, digits = 0) {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  return Intl.NumberFormat(undefined, {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  }).format(value);
}

function formatPercent(value: number | undefined) {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  return `${Math.round(value * 100)}%`;
}

function formatDuration(value?: number | null) {
  if (typeof value !== "number" || Number.isNaN(value)) return "—";
  if (value >= 1000) {
    return `${formatMetric(value / 1000, 2)}s`;
  }
  return `${formatMetric(value, 0)}ms`;
}

function compactId(value?: string | null) {
  const text = String(value || "").trim();
  if (!text) return "—";
  if (text.length <= 18) return text;
  return `${text.slice(0, 8)}…${text.slice(-6)}`;
}

function compactQuestion(value?: string | null) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (!text) return "—";
  if (text.length <= 54) return text;
  return `${text.slice(0, 54)}…`;
}

function compactDetailQuestion(value?: string | null) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (!text) return "—";
  if (text.length <= 160) return text;
  return `${text.slice(0, 160)}…`;
}

function extractStructuredSummary(value?: string | null) {
  const text = String(value || "").trim();
  if (!text) return "";
  const matches = [...text.matchAll(/reasoning_content['"]?\s*:\s*['"]([^'"]+)['"]/g)]
    .map((item) => item[1]?.trim() || "")
    .filter(Boolean);
  if (matches.length) {
    const deduped = [...new Set(matches)];
    const joined = deduped.join("");
    return joined.length > 260 ? `${joined.slice(0, 260)}…` : joined;
  }
  return text.length > 260 ? `${text.slice(0, 260)}…` : text;
}

function stepObservationPreview(value?: string | null) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (!text) return "—";
  if (text.length <= 140) return text;
  return `${text.slice(0, 140)}…`;
}

function compactSnippet(value?: string | null, max = 88) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (!text) return "";
  if (text.length <= max) return text;
  return `${text.slice(0, max)}…`;
}

function stringifyMetadataValue(value: unknown) {
  if (value === undefined || value === null) return "";
  if (typeof value === "string") return value.trim();
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    const text = JSON.stringify(value);
    if (!text) return "";
    return text.length > 120 ? `${text.slice(0, 120)}…` : text;
  } catch {
    return "";
  }
}

function findNestedMetadataValue(
  source: unknown,
  aliases: readonly string[],
  options?: { depth?: number; seen?: WeakSet<object> },
): string {
  const depth = options?.depth ?? 0;
  if (depth > 4) return "";
  if (Array.isArray(source)) {
    for (const item of source) {
      const match = findNestedMetadataValue(item, aliases, {
        depth: depth + 1,
        seen: options?.seen,
      });
      if (match) return match;
    }
    return "";
  }
  if (!isRecord(source)) return "";
  const seen = options?.seen ?? new WeakSet<object>();
  if (seen.has(source)) return "";
  seen.add(source);

  for (const alias of aliases) {
    if (alias in source) {
      const match = stringifyMetadataValue(source[alias]);
      if (match) return match;
    }
  }

  for (const value of Object.values(source)) {
    const match = findNestedMetadataValue(value, aliases, {
      depth: depth + 1,
      seen,
    });
    if (match) return match;
  }
  return "";
}

function findMetadataAcrossSources(sources: unknown[], aliases: readonly string[]) {
  for (const source of sources) {
    const match = findNestedMetadataValue(source, aliases);
    if (match) return match;
  }
  return "";
}

function normalizeStatusFilter(value: StatusMode): string[] | undefined {
  if (value === "all") return undefined;
  return [value];
}

function statusTone(status?: string | null) {
  if (status === "failed") return "danger";
  if (status === "succeeded") return "success";
  return "neutral";
}

function severityClass(step: FocusAgentTrajectoryStep) {
  if (step.error) return "is-danger";
  if (step.fallback_used) return "is-warning";
  if (step.cache_hit) return "is-success";
  return "";
}

function humanizeKey(value?: string | null) {
  const text = String(value || "").trim();
  if (!text) return "—";
  return text.replace(/[_-]+/g, " ");
}

function getDominantTool(trajectory: FocusAgentTrajectoryStep[]) {
  const counts = new Map<string, number>();
  trajectory.forEach((step) => {
    counts.set(step.tool, (counts.get(step.tool) ?? 0) + 1);
  });
  return [...counts.entries()].sort((left, right) => right[1] - left[1])[0]?.[0] ?? "—";
}

function getLongestStep(trajectory: FocusAgentTrajectoryStep[]) {
  if (!trajectory.length) return null;
  return trajectory.reduce((current, next) =>
    (next.duration_ms ?? 0) > (current.duration_ms ?? 0) ? next : current,
  );
}

function buildFilterChips(args: {
  statusFilter: StatusMode;
  toolFilter: string;
  threadFilter: string;
  requestFilter: string;
  traceFilter: string;
  modelFilter: string;
  minLatency: string;
  fallbackOnly: boolean;
  hasErrorOnly: boolean;
  sortMode: SortMode;
  clearStatus: () => void;
  clearTool: () => void;
  clearThread: () => void;
  clearRequest: () => void;
  clearTrace: () => void;
  clearModel: () => void;
  clearLatency: () => void;
  clearFallback: () => void;
  clearErrorOnly: () => void;
  clearSort: () => void;
}) {
  const chips: FilterChip[] = [];
  if (args.statusFilter !== "all") {
    chips.push({
      id: "status",
      labelZh: `状态 · ${args.statusFilter === "failed" ? "失败" : "成功"}`,
      labelEn: `Status · ${args.statusFilter === "failed" ? "Failed" : "Succeeded"}`,
      clear: args.clearStatus,
    });
  }
  if (args.toolFilter.trim()) {
    chips.push({
      id: "tool",
      labelZh: `工具 · ${args.toolFilter.trim()}`,
      labelEn: `Tool · ${args.toolFilter.trim()}`,
      clear: args.clearTool,
    });
  }
  if (args.threadFilter.trim()) {
    chips.push({
      id: "thread",
      labelZh: `线程 · ${compactId(args.threadFilter.trim())}`,
      labelEn: `Thread · ${compactId(args.threadFilter.trim())}`,
      clear: args.clearThread,
    });
  }
  if (args.requestFilter.trim()) {
    chips.push({
      id: "request",
      labelZh: `Request · ${compactId(args.requestFilter.trim())}`,
      labelEn: `Request · ${compactId(args.requestFilter.trim())}`,
      clear: args.clearRequest,
    });
  }
  if (args.traceFilter.trim()) {
    chips.push({
      id: "trace",
      labelZh: `Trace · ${compactId(args.traceFilter.trim())}`,
      labelEn: `Trace · ${compactId(args.traceFilter.trim())}`,
      clear: args.clearTrace,
    });
  }
  if (args.modelFilter.trim()) {
    chips.push({
      id: "model",
      labelZh: `模型 · ${args.modelFilter.trim()}`,
      labelEn: `Model · ${args.modelFilter.trim()}`,
      clear: args.clearModel,
    });
  }
  if (args.minLatency.trim()) {
    chips.push({
      id: "latency",
      labelZh: `延迟 ≥ ${args.minLatency.trim()}ms`,
      labelEn: `Latency ≥ ${args.minLatency.trim()}ms`,
      clear: args.clearLatency,
    });
  }
  if (args.fallbackOnly) {
    chips.push({
      id: "fallback",
      labelZh: "仅看 fallback",
      labelEn: "Fallback only",
      clear: args.clearFallback,
    });
  }
  if (args.hasErrorOnly) {
    chips.push({
      id: "error",
      labelZh: "仅看错误",
      labelEn: "Errors only",
      clear: args.clearErrorOnly,
    });
  }
  if (args.sortMode !== "newest") {
    chips.push({
      id: "sort",
      labelZh: `排序 · ${args.sortMode === "latency" ? "延迟" : "工具数"}`,
      labelEn: `Sort · ${args.sortMode === "latency" ? "Latency" : "Tool calls"}`,
      clear: args.clearSort,
    });
  }
  return chips;
}

function topToolRows(byTool: FocusAgentTrajectoryStatsRow[] | undefined) {
  return [...(byTool ?? [])]
    .sort((left, right) => (right.turn_count ?? 0) - (left.turn_count ?? 0))
    .slice(0, 4);
}

function topStatsRows(rows: FocusAgentTrajectoryStatsRow[] | undefined, limit = 4) {
  return [...(rows ?? [])]
    .sort((left, right) => {
      const leftCount = left.turn_count ?? left.step_count ?? 0;
      const rightCount = right.turn_count ?? right.step_count ?? 0;
      return rightCount - leftCount;
    })
    .slice(0, limit);
}

function ratio(numerator?: number, denominator?: number) {
  if (typeof numerator !== "number" || typeof denominator !== "number" || denominator <= 0) return undefined;
  return numerator / denominator;
}

function findStepRuntimeSignal(step: FocusAgentTrajectoryStep, aliases: readonly string[]) {
  return findNestedMetadataValue(step.runtime, aliases);
}

function buildSelectedSignals(selected: FocusAgentTrajectoryTurnDetail | null) {
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
  const errorSteps = selected.trajectory.filter((step) => Boolean(step.error)).length;
  const fallbackSteps = selected.trajectory.filter((step) => step.fallback_used).length;
  const cacheSteps = selected.trajectory.filter((step) => step.cache_hit).length;
  const parallelSteps = selected.trajectory.filter((step) => Boolean(step.parallel_batch_size)).length;
  return {
    errorSteps,
    fallbackSteps,
    cacheSteps,
    parallelSteps,
    dominantTool: getDominantTool(selected.trajectory),
    longestStep: getLongestStep(selected.trajectory),
  };
}

function buildTurnSummary(item: FocusAgentTrajectoryTurnSummary, isChineseUi: boolean) {
  const errorText = compactSnippet(item?.error);
  if (errorText) {
    return isChineseUi ? `错误 · ${errorText}` : `Error · ${errorText}`;
  }
  const summaryText = compactSnippet(extractStructuredSummary(item?.answer));
  if (summaryText) return summaryText;
  return isChineseUi
    ? `${humanizeKey(item?.scene)} · ${item?.branch_role ? humanizeKey(item.branch_role) : "未标记角色"}`
    : `${humanizeKey(item?.scene)} · ${item?.branch_role ? humanizeKey(item.branch_role) : "No branch role"}`;
}

function buildCorrelationSignals(selected: FocusAgentTrajectoryTurnDetail | null): CorrelationSignal[] {
  if (!selected) return [];

  const runtimeSources = selected.trajectory.map((step) => step.runtime);
  const metadataSources = [selected.plan_meta, selected.metrics, selected.reflection, ...runtimeSources];
  const requestId = selected.request_id || findMetadataAcrossSources(metadataSources, ["request_id", "requestId"]);
  const traceId = selected.trace_id || findMetadataAcrossSources(metadataSources, ["trace_id", "traceId"]);
  const spanId = selected.root_span_id || findMetadataAcrossSources(metadataSources, ["span_id", "spanId", "root_span_id", "rootSpanId"]);
  const environment = selected.environment || findMetadataAcrossSources(metadataSources, ["environment", "env"]);
  const deployment = selected.deployment || findMetadataAcrossSources(metadataSources, ["deployment", "deployment_name"]);
  const appVersion = selected.app_version || findMetadataAcrossSources(metadataSources, ["app_version", "appVersion", "version"]);

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

function findCorrelationSignalValue(signals: CorrelationSignal[], id: string) {
  return signals.find((signal) => signal.id === id)?.value ?? "";
}

export function TrajectoryPage() {
  const { isChineseUi } = useShellUi();
  const isOverviewRoute = useRouterState({
    select: (state) => state.location.pathname.endsWith("/observability/overview"),
  });
  const locale = isChineseUi ? "zh-CN" : "en-US";
  const detailPanelRef = useRef<HTMLElement | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusMode>(() => readInitialStatus());
  const [toolFilter, setToolFilter] = useState(() => readInitialSearchParam("tool"));
  const [threadFilter, setThreadFilter] = useState(() => readInitialSearchParam("thread"));
  const [requestFilter, setRequestFilter] = useState(() => readInitialSearchParam("request"));
  const [traceFilter, setTraceFilter] = useState(() => readInitialSearchParam("trace"));
  const [modelFilter, setModelFilter] = useState(() => readInitialSearchParam("model"));
  const [minLatency, setMinLatency] = useState(() => readInitialSearchParam("minLatency"));
  const [fallbackOnly, setFallbackOnly] = useState(() => readInitialFlag("fallbackOnly", false));
  const [hasErrorOnly, setHasErrorOnly] = useState(() => readInitialFlag("hasErrorOnly", false));
  const [sortMode, setSortMode] = useState<SortMode>(() => readInitialSort());
  const [selectedTurnId, setSelectedTurnId] = useState(() => readInitialSearchParam("turn"));
  const [filtersExpanded, setFiltersExpanded] = useState(
    () =>
      Boolean(readInitialSearchParam("tool")) ||
      Boolean(readInitialSearchParam("thread")) ||
      Boolean(readInitialSearchParam("request")) ||
      Boolean(readInitialSearchParam("trace")) ||
      Boolean(readInitialSearchParam("model")) ||
      Boolean(readInitialSearchParam("minLatency")) ||
      readInitialFlag("fallbackOnly", false) ||
      readInitialFlag("hasErrorOnly", false) ||
      readInitialStatus() !== "all" ||
      readInitialSort() !== "newest",
  );
  const parsedMinLatency = useMemo(() => parseNonNegativeNumber(minLatency), [minLatency]);
  const hasInvalidLatency = minLatency.trim() !== "" && parsedMinLatency === undefined;

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
  const { data: listData, isLoading: isListLoading, error: listError } = useTrajectoryList(deferredFilters);
  const { data: overviewData, isLoading: isStatsLoading, error: statsError } = useObservabilityOverview({
    ...deferredFilters,
  });
  const statsData = overviewData;

  const orderedItems = useMemo(() => {
    const items = [...(listData?.items ?? [])];
    if (sortMode === "latency") {
      items.sort((left, right) => (right.latency_ms ?? 0) - (left.latency_ms ?? 0));
      return items;
    }
    if (sortMode === "tool_calls") {
      items.sort((left, right) => (right.tool_calls ?? 0) - (left.tool_calls ?? 0));
      return items;
    }
    return items;
  }, [listData?.items, sortMode]);

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
    if (typeof window === "undefined") return;
    const url = new URL(window.location.href);
    const params = url.searchParams;
    const assign = (key: string, value: string | boolean, defaultValue?: string | boolean) => {
      const normalized = typeof value === "boolean" ? (value ? "1" : "") : value.trim();
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

  const { data: detailData, isLoading: isDetailLoading } = useTrajectoryDetail(selectedTurnId);
  const selected = detailData?.item ?? null;
  const commandSnippet = selectedTurnId ? `focus-agent-trajectory show ${selectedTurnId}` : "";
  const matchCount = listData?.count ?? orderedItems.length;
  const resultSummary = selected ? extractStructuredSummary(selected.answer) : "";
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
    [fallbackOnly, hasErrorOnly, minLatency, modelFilter, requestFilter, sortMode, statusFilter, threadFilter, toolFilter, traceFilter],
  );
  const selectedSignals = useMemo(() => buildSelectedSignals(selected), [selected]);
  const hottestTools = useMemo(() => topToolRows(statsData?.stats.by_tool), [statsData?.stats.by_tool]);
  const hottestScenes = useMemo(() => topStatsRows(statsData?.stats.by_scene, 4), [statsData?.stats.by_scene]);
  const hottestBranchRoles = useMemo(
    () => topStatsRows(statsData?.stats.by_branch_role, 4),
    [statsData?.stats.by_branch_role],
  );
  const hottestModels = useMemo(() => topStatsRows(statsData?.stats.by_model, 4), [statsData?.stats.by_model]);
  const dailyTrend = useMemo(() => (statsData?.stats.by_day ?? []).slice(-7), [statsData?.stats.by_day]);
  const correlationSignals = useMemo(() => buildCorrelationSignals(selected), [selected]);
  const selectedRequestSignal = findCorrelationSignalValue(correlationSignals, "request");
  const selectedTraceSignal = findCorrelationSignalValue(correlationSignals, "trace");
  const selectedThreadSignal = findCorrelationSignalValue(correlationSignals, "thread");
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
      ? (statsOverview.non_succeeded_count ?? 0) / (statsOverview.turn_count ?? 0)
      : undefined;
  const toolsPerTurn =
    statsOverview && (statsOverview.turn_count ?? 0) > 0
      ? (statsOverview.total_tool_calls ?? 0) / (statsOverview.turn_count ?? 0)
      : undefined;
  const fallbackPerToolCall = ratio(statsOverview?.total_fallback_uses, statsOverview?.total_tool_calls);
  const cachePerToolCall = ratio(statsOverview?.total_cache_hits, statsOverview?.total_tool_calls);
  const succeededCount =
    typeof statsOverview?.succeeded_count === "number"
      ? statsOverview.succeeded_count
      : Math.max((statsOverview?.turn_count ?? 0) - (statsOverview?.non_succeeded_count ?? 0), 0);
  const selectedVsAverageLatency =
    selected && typeof selected.latency_ms === "number" && typeof statsOverview?.avg_latency_ms === "number" && statsOverview.avg_latency_ms > 0
      ? selected.latency_ms / statsOverview.avg_latency_ms
      : undefined;
  const correlationCoverage = correlationSignals.filter((item) =>
    ["request", "trace", "span", "env", "deployment", "version"].includes(item.id),
  ).length;
  const heroStats = useMemo(
    () => [
      {
        labelZh: "当前匹配",
        labelEn: "Matches",
        value: isListLoading ? "…" : formatMetric(matchCount, 0),
        captionZh: "当前筛选范围内的 turn 数量",
        captionEn: "Turns in the active filter scope",
      },
      {
        labelZh: "失败占比",
        labelEn: "Failure rate",
        value: isStatsLoading ? "…" : formatPercent(failureRate),
        captionZh: "帮助你判断问题密度",
        captionEn: "Quick read on problem density",
      },
      {
        labelZh: "平均延迟",
        labelEn: "Avg latency",
        value: isStatsLoading ? "…" : formatDuration(statsOverview?.avg_latency_ms),
        captionZh: "用来识别慢路径",
        captionEn: "A fast way to spot slow paths",
      },
      {
        labelZh: "每 turn 工具数",
        labelEn: "Tools / turn",
        value: isStatsLoading ? "…" : formatMetric(toolsPerTurn, 1),
        captionZh: "评估排障复杂度",
        captionEn: "A proxy for operational complexity",
      },
    ],
    [failureRate, formatDuration, isListLoading, isStatsLoading, matchCount, statsOverview?.avg_latency_ms, toolsPerTurn],
  );

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
    const blob = new Blob([`${JSON.stringify(selected, null, 2)}\n`], { type: "application/json" });
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
      caption: selectedRequestSignal || (isChineseUi ? "当前样本没有 request_id" : "No request_id on this turn"),
      disabled: !selectedRequestSignal,
      action: () => focusRequest(selectedRequestSignal),
    },
    {
      id: "trace",
      label: isChineseUi ? "锁定同一 Trace" : "Lock same trace",
      caption: selectedTraceSignal || (isChineseUi ? "当前样本没有 trace_id" : "No trace_id on this turn"),
      disabled: !selectedTraceSignal,
      action: () => focusTrace(selectedTraceSignal),
    },
    {
      id: "thread",
      label: isChineseUi ? "只看同一线程" : "Same thread only",
      caption: selectedThreadSignal || (isChineseUi ? "当前样本没有线程锚点" : "No thread anchor on this turn"),
      disabled: !selectedThreadSignal,
      action: () => focusThread(selectedThreadSignal),
    },
    {
      id: "model",
      label: isChineseUi ? "切到同一模型" : "Same model slice",
      caption: selectedModel || (isChineseUi ? "当前样本没有模型信息" : "No model captured on this turn"),
      disabled: !selectedModel,
      action: () => focusModel(selectedModel),
    },
    {
      id: "failures",
      label: isChineseUi ? "当前范围仅看失败" : "Failures in scope",
      caption: isChineseUi ? "保留当前 request/trace/thread 等锚点，只切失败样本" : "Keep active anchors, then pivot to non-succeeded turns only",
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
      label: isChineseUi ? "清除 request/trace 锁定" : "Clear request/trace pivots",
      caption:
        requestFilter.trim() || traceFilter.trim()
          ? [requestFilter.trim(), traceFilter.trim()].filter(Boolean).map(compactId).join(" · ")
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

  return (
    <div className="fa-observability-layout">
      <section className="fa-observability-topbar">
        <div className="fa-observability-topbar-copy">
          <p className="fa-observability-kicker">
            {isChineseUi ? "内部诊断页" : "Internal diagnostics"}
          </p>
          <h1>{isChineseUi ? "Trajectory 复盘台" : "Trajectory review console"}</h1>
          <p className="fa-observability-hero-text">
            {isOverviewRoute
              ? isChineseUi
                ? "先从运营总览看失败率、延迟和工具热点，再下钻到具体 trajectory turn。"
                : "Start from the operations pulse, then drill into the exact trajectory turn behind a failure or latency spike."
              : isChineseUi
                ? "先在左侧锁定问题样本，再在中间读执行轨迹，最后在右侧决定 replay 或沉淀样本。"
                : "Start with the failing sample on the left, inspect the execution path in the middle, and decide the replay action on the right."}
          </p>
          <p className="fa-observability-topbar-inline-note">
            {selected
              ? isChineseUi
                ? `当前聚焦 ${compactId(selected.id)} · 主分析区会在切换样本时自动回到顶部。`
                : `Focused on ${compactId(selected.id)}. The investigation pane resets to the top when you switch turns.`
              : isChineseUi
                ? "还没有聚焦样本，先从左侧列表选择一条 turn。"
                : "No active turn yet. Pick one from the list first."}
          </p>
          <nav
            aria-label={isChineseUi ? "Observability 页面" : "Observability views"}
            className="fa-observability-route-tabs"
          >
            <Link
              className={`fa-observability-route-tab ${isOverviewRoute ? "is-active" : ""}`.trim()}
              search
              to="/observability/overview"
            >
              <span>{isChineseUi ? "运营总览" : "Ops overview"}</span>
              <strong>{isChineseUi ? "趋势 / 热点" : "Trends / hotspots"}</strong>
            </Link>
            <Link
              className={`fa-observability-route-tab ${isOverviewRoute ? "" : "is-active"}`.trim()}
              search
              to="/observability/trajectory"
            >
              <span>{isChineseUi ? "复盘工作台" : "Trajectory workbench"}</span>
              <strong>{isChineseUi ? "样本 / Replay" : "Samples / replay"}</strong>
            </Link>
          </nav>
        </div>

        <div className="fa-observability-topbar-side">
          <div className="fa-observability-inline-stats">
            {heroStats.map((item) => (
              <div key={item.labelEn} className="fa-observability-inline-stat">
                <span>{isChineseUi ? item.labelZh : item.labelEn}</span>
                <strong>{item.value}</strong>
              </div>
            ))}
          </div>
          <div className="fa-observability-toolbar-actions">
            <button
              className="fa-chat-toolbar-button is-primary"
              onClick={() => copyText(window.location.href)}
              type="button"
            >
              {isChineseUi ? "复制当前链接" : "Copy link"}
            </button>
            {selected ? (
              <button className="fa-chat-toolbar-button" onClick={() => copyText(commandSnippet)} type="button">
                {isChineseUi ? "复制 CLI 查看命令" : "Copy CLI command"}
              </button>
            ) : null}
          </div>
        </div>
      </section>

      {statsErrorMessage ? <div className="fa-inline-notice is-warning">{statsErrorMessage}</div> : null}
      {trajectoryRuntimeMessage ? <div className="fa-inline-notice is-warning">{trajectoryRuntimeMessage}</div> : null}

      <section className="fa-observability-workflow-strip">
        <div className="fa-observability-workflow-card">
          <div className="fa-observability-block-heading">
            <div>
              <h3>{isChineseUi ? "在线查询上下文" : "Live query context"}</h3>
              <p>
                {isChineseUi
                  ? "把 request、trace、thread 这些锚点显式展示出来，方便值班时直接 deep link。"
                  : "Keep request, trace, and thread pivots visible so operators can deep-link and hand off quickly."}
              </p>
            </div>
            <span className="fa-observability-pill is-neutral">
              {isChineseUi ? `${filterChips.length} 个激活筛选` : `${filterChips.length} active filters`}
            </span>
          </div>
          <div className="fa-observability-workflow-grid">
            <div className="fa-observability-workflow-stat">
              <span>{isChineseUi ? "Request 锁定" : "Request pivot"}</span>
              <strong>{requestFilter.trim() ? compactId(requestFilter) : "—"}</strong>
            </div>
            <div className="fa-observability-workflow-stat">
              <span>{isChineseUi ? "Trace 锁定" : "Trace pivot"}</span>
              <strong>{traceFilter.trim() ? compactId(traceFilter) : "—"}</strong>
            </div>
            <div className="fa-observability-workflow-stat">
              <span>{isChineseUi ? "线程范围" : "Thread scope"}</span>
              <strong>{threadFilter.trim() ? compactId(threadFilter) : "—"}</strong>
            </div>
            <div className="fa-observability-workflow-stat">
              <span>{isChineseUi ? "模型范围" : "Model scope"}</span>
              <strong>{modelFilter.trim() || "—"}</strong>
            </div>
          </div>
        </div>

        <div className="fa-observability-workflow-card">
          <div className="fa-observability-block-heading">
            <div>
              <h3>{isChineseUi ? "生产排障快捷流" : "Production pivots"}</h3>
              <p>
                {isChineseUi
                  ? "从当前样本一键切到同 request、同 trace、同线程或同模型的范围，再决定是否 replay。"
                  : "Jump from the selected turn into the same request, trace, thread, or model slice before deciding whether to replay."}
              </p>
            </div>
            <span className="fa-observability-pill is-neutral">
              {selected ? (isChineseUi ? "基于当前样本" : "Driven by selected turn") : (isChineseUi ? "等待样本" : "Waiting for a turn")}
            </span>
          </div>
          <div className="fa-observability-pivot-grid">
            {pivotActions.map((action) => (
              <button
                key={action.id}
                className={`fa-observability-pivot-button ${action.disabled ? "is-disabled" : ""}`.trim()}
                disabled={action.disabled}
                onClick={action.action}
                type="button"
              >
                <strong>{action.label}</strong>
                <span>{compactSnippet(action.caption, 88) || "—"}</span>
              </button>
            ))}
          </div>
        </div>
      </section>

      <section className="fa-observability-overview-grid">
        <div className="fa-observability-overview-card">
          <div className="fa-observability-overview-heading">
            <div>
              <p>{isChineseUi ? "运营总览" : "Operations pulse"}</p>
              <h2>{isChineseUi ? "先看当前筛选范围的整体健康度" : "Read the health of the current slice first"}</h2>
            </div>
            <span className={`fa-observability-pill is-${runtimeReadiness?.ready === false ? "danger" : "success"}`}>
              {runtimeReadiness?.status ?? (isChineseUi ? "就绪" : "ready")}
            </span>
          </div>
          <div className="fa-observability-overview-metrics">
            <div className="fa-observability-overview-metric">
              <span>{isChineseUi ? "总 turn" : "Total turns"}</span>
              <strong>{isStatsLoading ? "…" : formatMetric(statsOverview?.turn_count, 0)}</strong>
            </div>
            <div className="fa-observability-overview-metric">
              <span>{isChineseUi ? "成功" : "Succeeded"}</span>
              <strong>{isStatsLoading ? "…" : formatMetric(succeededCount, 0)}</strong>
            </div>
            <div className="fa-observability-overview-metric">
              <span>{isChineseUi ? "失败" : "Non-succeeded"}</span>
              <strong>{isStatsLoading ? "…" : formatMetric(statsOverview?.non_succeeded_count, 0)}</strong>
            </div>
            <div className="fa-observability-overview-metric">
              <span>{isChineseUi ? "失败率" : "Failure rate"}</span>
              <strong>{isStatsLoading ? "…" : formatPercent(failureRate)}</strong>
            </div>
          </div>
          <div className="fa-observability-overview-strip">
            <div>
              <span>{isChineseUi ? "运行环境" : "Environment"}</span>
              <strong>{runtimeReadiness?.environment || "—"}</strong>
            </div>
            <div>
              <span>{isChineseUi ? "部署" : "Deployment"}</span>
              <strong>{runtimeReadiness?.deployment || "—"}</strong>
            </div>
            <div>
              <span>{isChineseUi ? "版本" : "Version"}</span>
              <strong>{runtimeReadiness?.app_version || "—"}</strong>
            </div>
            <div>
              <span>{isChineseUi ? "组件检查" : "Checks"}</span>
              <strong>
                {runtimeReadiness?.checks?.length
                  ? `${runtimeReadiness.checks.filter((item) => item.ready).length}/${runtimeReadiness.checks.length}`
                  : "—"}
              </strong>
            </div>
          </div>
          <div className="fa-observability-overview-strip">
            <div>
              <span>{isChineseUi ? "工具调用" : "Tool calls"}</span>
              <strong>{isStatsLoading ? "…" : formatMetric(statsOverview?.total_tool_calls, 0)}</strong>
            </div>
            <div>
              <span>{isChineseUi ? "LLM 调用" : "LLM calls"}</span>
              <strong>{isStatsLoading ? "…" : formatMetric(statsOverview?.total_llm_calls, 0)}</strong>
            </div>
            <div>
              <span>{isChineseUi ? "Fallback 密度" : "Fallback density"}</span>
              <strong>{isStatsLoading ? "…" : formatPercent(fallbackPerToolCall)}</strong>
            </div>
            <div>
              <span>{isChineseUi ? "Cache 密度" : "Cache density"}</span>
              <strong>{isStatsLoading ? "…" : formatPercent(cachePerToolCall)}</strong>
            </div>
          </div>
        </div>

        <div className="fa-observability-overview-card">
          <div className="fa-observability-overview-heading">
            <div>
              <p>{isChineseUi ? "延迟观察" : "Latency watch"}</p>
              <h2>{isChineseUi ? "把慢路径和当前样本放在一起看" : "Compare slow paths with the active turn"}</h2>
            </div>
            {selected ? (
              <span className={`fa-observability-pill is-${statusTone(selected.status)}`}>{selected.status}</span>
            ) : null}
          </div>
          <div className="fa-observability-overview-metrics">
            <div className="fa-observability-overview-metric">
              <span>{isChineseUi ? "平均延迟" : "Average latency"}</span>
              <strong>{isStatsLoading ? "…" : formatDuration(statsOverview?.avg_latency_ms)}</strong>
            </div>
            <div className="fa-observability-overview-metric">
              <span>{isChineseUi ? "最大延迟" : "Max latency"}</span>
              <strong>{isStatsLoading ? "…" : formatDuration(statsOverview?.max_latency_ms)}</strong>
            </div>
            <div className="fa-observability-overview-metric">
              <span>{isChineseUi ? "当前样本" : "Selected turn"}</span>
              <strong>{selected ? formatDuration(selected.latency_ms) : "—"}</strong>
            </div>
            <div className="fa-observability-overview-metric">
              <span>{isChineseUi ? "相对均值" : "Vs average"}</span>
              <strong>
                {selectedVsAverageLatency === undefined
                  ? "—"
                  : `${formatMetric(selectedVsAverageLatency, 1)}×`}
              </strong>
            </div>
          </div>
          <div className="fa-observability-insight-list">
            <div className="fa-observability-insight-row">
              <span>{isChineseUi ? "最长步骤" : "Longest selected step"}</span>
              <strong>
                {selectedSignals.longestStep
                  ? `${selectedSignals.longestStep.tool} · ${formatDuration(selectedSignals.longestStep.duration_ms)}`
                  : "—"}
              </strong>
            </div>
            <div className="fa-observability-insight-row">
              <span>{isChineseUi ? "并行批次" : "Parallel batches"}</span>
              <strong>{selected ? formatMetric(selectedSignals.parallelSteps, 0) : "—"}</strong>
            </div>
            <div className="fa-observability-insight-row">
              <span>{isChineseUi ? "每 turn 工具数" : "Tools per turn"}</span>
              <strong>{isStatsLoading ? "…" : formatMetric(toolsPerTurn, 1)}</strong>
            </div>
          </div>
        </div>

        <div className="fa-observability-overview-card">
          <div className="fa-observability-overview-heading">
            <div>
              <p>{isChineseUi ? "压力热点" : "Pressure map"}</p>
              <h2>{isChineseUi ? "看 branch role、scene 和 model 的集中区" : "See where roles, scenes, and models concentrate"}</h2>
            </div>
          </div>
          <div className="fa-observability-dual-list">
            <div className="fa-observability-signal-list">
              <span className="fa-observability-list-label">{isChineseUi ? "Branch role" : "Branch role"}</span>
              {hottestBranchRoles.length ? (
                hottestBranchRoles.map((row) => (
                  <div key={`branch-${row.key}`} className="fa-observability-signal-row">
                    <div>
                      <strong>{humanizeKey(String(row.key ?? "unknown"))}</strong>
                      <span>{formatPercent(ratio(row.non_succeeded_count, row.turn_count))}</span>
                    </div>
                    <div>
                      <strong>{formatMetric(row.turn_count, 0)}</strong>
                      <span>{formatDuration(row.avg_latency_ms)}</span>
                    </div>
                  </div>
                ))
              ) : (
                <div className="fa-observability-empty is-compact">
                  {isChineseUi ? "暂无 branch role 聚合数据。" : "Branch-role aggregates are not available yet."}
                </div>
              )}
            </div>
            <div className="fa-observability-signal-list">
              <span className="fa-observability-list-label">{isChineseUi ? "Scene" : "Scene"}</span>
              {hottestScenes.length ? (
                hottestScenes.map((row) => (
                  <div key={`scene-${row.key}`} className="fa-observability-signal-row">
                    <div>
                      <strong>{humanizeKey(String(row.key ?? "unknown"))}</strong>
                      <span>{formatPercent(ratio(row.non_succeeded_count, row.turn_count))}</span>
                    </div>
                    <div>
                      <strong>{formatMetric(row.turn_count, 0)}</strong>
                      <span>{formatDuration(row.avg_latency_ms)}</span>
                    </div>
                  </div>
                ))
              ) : (
                <div className="fa-observability-empty is-compact">
                  {isChineseUi ? "暂无 scene 聚合数据。" : "Scene aggregates are not available yet."}
                </div>
              )}
            </div>
            <div className="fa-observability-signal-list">
              <span className="fa-observability-list-label">{isChineseUi ? "Model" : "Model"}</span>
              {hottestModels.length ? (
                hottestModels.map((row) => (
                  <div key={`model-${row.key}`} className="fa-observability-signal-row">
                    <div>
                      <strong>{String(row.key ?? "unknown")}</strong>
                      <span>{formatPercent(ratio(row.non_succeeded_count, row.turn_count))}</span>
                    </div>
                    <div>
                      <strong>{formatMetric(row.turn_count, 0)}</strong>
                      <span>{formatDuration(row.avg_latency_ms)}</span>
                    </div>
                  </div>
                ))
              ) : (
                <div className="fa-observability-empty is-compact">
                  {isChineseUi ? "暂无 model 聚合数据。" : "Model aggregates are not available yet."}
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="fa-observability-overview-card">
          <div className="fa-observability-overview-heading">
            <div>
              <p>{isChineseUi ? "工具健康" : "Tool health"}</p>
              <h2>{isChineseUi ? "用热点工具先划出排障优先级" : "Use hot tools to prioritize investigation"}</h2>
            </div>
            {selected ? (
              <span className="fa-observability-pill is-neutral">
                {isChineseUi
                  ? `${correlationCoverage} 个关联信号`
                  : `${correlationCoverage} correlation hooks`}
              </span>
            ) : null}
          </div>
            {hottestTools.length ? (
            <div className="fa-observability-signal-list">
              {hottestTools.map((tool) => (
                <button
                  key={tool.key}
                  className={`fa-observability-signal-row is-button ${toolFilter.trim() === String(tool.key ?? "") ? "is-active" : ""}`}
                  onClick={() => setToolFilter(String(tool.key ?? ""))}
                  type="button"
                >
                  <div>
                    <strong>{tool.key}</strong>
                    <span>
                      {isChineseUi
                        ? `${formatMetric(tool.turn_count, 0)} 个 turn`
                        : `${formatMetric(tool.turn_count, 0)} turns`}
                    </span>
                  </div>
                  <div>
                    <strong>{formatDuration(tool.avg_duration_ms)}</strong>
                    <span>{formatPercent(ratio(tool.fallback_steps, tool.step_count))}</span>
                  </div>
                </button>
              ))}
            </div>
          ) : (
            <div className="fa-observability-empty is-compact">
              {isChineseUi ? "暂无工具健康聚合。" : "Tool health aggregates are not available yet."}
            </div>
          )}
          <div className="fa-observability-insight-list">
            <div className="fa-observability-insight-row">
              <span>{isChineseUi ? "最近 7 天" : "Last 7 days"}</span>
              <strong>{dailyTrend.length ? `${dailyTrend.length} buckets` : "—"}</strong>
            </div>
            {dailyTrend.length ? (
              dailyTrend.map((row) => (
                <div key={`day-${row.key}`} className="fa-observability-insight-row">
                  <span>{String(row.key ?? "—")}</span>
                  <strong>
                    {isChineseUi
                      ? `${formatMetric(row.turn_count, 0)} turn / ${formatPercent(ratio(row.non_succeeded_count, row.turn_count))}`
                      : `${formatMetric(row.turn_count, 0)} turns / ${formatPercent(ratio(row.non_succeeded_count, row.turn_count))}`}
                  </strong>
                </div>
              ))
            ) : null}
          </div>
        </div>
      </section>

      <section className="fa-observability-console is-workbench">
        <aside className="fa-observability-list-panel is-explorer">
          <div className="fa-observability-panel-header">
            <div>
              <h2>{isChineseUi ? "样本浏览器" : "Sample explorer"}</h2>
              <span>
                {isChineseUi
                  ? "像 trace explorer 一样先缩小范围，再挑一条进入主分析区。"
                  : "Narrow the scope first, then promote one turn into the main investigation area."}
              </span>
            </div>
            <strong>{isListLoading ? "…" : formatMetric(matchCount, 0)}</strong>
          </div>

          <div className="fa-observability-explorer-bar">
            <div className="fa-observability-presets">
              <button className="fa-observability-preset" onClick={() => applyPreset("failures")} type="button">
                {isChineseUi ? "最近失败" : "Failures"}
              </button>
              <button className="fa-observability-preset" onClick={() => applyPreset("fallback")} type="button">
                {isChineseUi ? "Fallback" : "Fallback"}
              </button>
              <button className="fa-observability-preset" onClick={() => applyPreset("latency")} type="button">
                {isChineseUi ? "高延迟" : "Latency"}
              </button>
              <button className="fa-observability-preset" onClick={() => applyPreset("all")} type="button">
                {isChineseUi ? "全部" : "All"}
              </button>
            </div>

            <div className="fa-observability-active-filters">
              {filterChips.length ? (
                filterChips.map((chip) => (
                  <button key={chip.id} className="fa-observability-filter-chip" onClick={chip.clear} type="button">
                    <span>{isChineseUi ? chip.labelZh : chip.labelEn}</span>
                    <strong>×</strong>
                  </button>
                ))
              ) : (
                <span className="fa-observability-filter-chip is-empty">
                  {isChineseUi ? "当前没有附加过滤器" : "No extra filters active"}
                </span>
              )}
            </div>

            <details
              className="fa-observability-filter-drawer"
              open={filtersExpanded}
              onToggle={(event) => setFiltersExpanded((event.currentTarget as HTMLDetailsElement).open)}
            >
              <summary>
                {filtersExpanded
                  ? isChineseUi
                    ? "收起高级筛选"
                    : "Hide advanced filters"
                  : isChineseUi
                    ? "展开高级筛选"
                    : "Show advanced filters"}
              </summary>
              <div className="fa-observability-filter-shell">
                <div className="fa-observability-filters is-compact">
                  <label className="fa-observability-filter">
                    <span>{isChineseUi ? "状态" : "Status"}</span>
                    <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as StatusMode)}>
                      <option value="failed">{isChineseUi ? "失败" : "Failed"}</option>
                      <option value="all">{isChineseUi ? "全部" : "All"}</option>
                      <option value="succeeded">{isChineseUi ? "成功" : "Succeeded"}</option>
                    </select>
                  </label>
                  <label className="fa-observability-filter">
                    <span>{isChineseUi ? "工具" : "Tool"}</span>
                    <input value={toolFilter} onChange={(event) => setToolFilter(event.target.value)} placeholder="web_search" />
                  </label>
                  <label className="fa-observability-filter">
                    <span>{isChineseUi ? "线程" : "Thread"}</span>
                    <input value={threadFilter} onChange={(event) => setThreadFilter(event.target.value)} placeholder="thread-…" />
                  </label>
                  <label className="fa-observability-filter">
                    <span>{isChineseUi ? "Request" : "Request"}</span>
                    <input value={requestFilter} onChange={(event) => setRequestFilter(event.target.value)} placeholder="req-…" />
                  </label>
                  <label className="fa-observability-filter">
                    <span>{isChineseUi ? "Trace" : "Trace"}</span>
                    <input value={traceFilter} onChange={(event) => setTraceFilter(event.target.value)} placeholder="trace-…" />
                  </label>
                  <label className="fa-observability-filter">
                    <span>{isChineseUi ? "模型" : "Model"}</span>
                    <input value={modelFilter} onChange={(event) => setModelFilter(event.target.value)} placeholder="openai:gpt-4.1-mini" />
                  </label>
                  <label className="fa-observability-filter">
                    <span>{isChineseUi ? "最小延迟" : "Min latency"}</span>
                    <input
                      aria-invalid={hasInvalidLatency}
                      value={minLatency}
                      onChange={(event) => setMinLatency(event.target.value)}
                      inputMode="numeric"
                      pattern="[0-9]*"
                      placeholder="500"
                    />
                  </label>
                  <label className="fa-observability-filter">
                    <span>{isChineseUi ? "排序" : "Sort"}</span>
                    <select value={sortMode} onChange={(event) => setSortMode(event.target.value as SortMode)}>
                      <option value="newest">{isChineseUi ? "最近" : "Newest"}</option>
                      <option value="latency">{isChineseUi ? "延迟" : "Latency"}</option>
                      <option value="tool_calls">{isChineseUi ? "工具数" : "Tool calls"}</option>
                    </select>
                  </label>
                  <label className="fa-observability-toggle">
                    <input checked={fallbackOnly} onChange={(event) => setFallbackOnly(event.target.checked)} type="checkbox" />
                    <span>{isChineseUi ? "仅看 fallback" : "Fallback only"}</span>
                  </label>
                  <label className="fa-observability-toggle">
                    <input checked={hasErrorOnly} onChange={(event) => setHasErrorOnly(event.target.checked)} type="checkbox" />
                    <span>{isChineseUi ? "仅看错误" : "Errors only"}</span>
                  </label>
                </div>

                <div className="fa-observability-command-bar">
                  {hasInvalidLatency ? (
                    <span className="fa-observability-filter-hint is-warning">
                      {isChineseUi ? "最小延迟需要是非负数字。" : "Min latency must be a non-negative number."}
                    </span>
                  ) : null}
                  <button className="fa-chat-toolbar-button" onClick={resetFilters} type="button">
                    {isChineseUi ? "恢复默认" : "Reset"}
                  </button>
                </div>
              </div>
            </details>
          </div>

          <div className="fa-observability-turn-list is-dense">
            {orderedItems.map((item) => (
              <button
                key={item.id}
                className={`fa-observability-turn-card ${selectedTurnId === item.id ? "is-selected" : ""}`}
                onClick={() => setSelectedTurnId(item.id)}
                type="button"
              >
                <div className="fa-observability-turn-card-top">
                  <span className={`fa-observability-pill is-${statusTone(item.status)}`}>{item.status}</span>
                  <span>{formatDateTime(item.created_at, locale)}</span>
                </div>
                <strong>{compactQuestion(item.user_message || item.task_brief || item.id)}</strong>
                <p className="fa-observability-turn-card-summary">
                  {buildTurnSummary(item, isChineseUi)}
                </p>
                <div className="fa-observability-turn-card-subline">
                  <span>{compactId(item.thread_id)}</span>
                  <span>{item.selected_model || "—"}</span>
                </div>
                <div className="fa-observability-turn-card-subline is-correlation">
                  <span>{`Req ${compactId(item.request_id)}`}</span>
                  <span>{`Trace ${compactId(item.trace_id)}`}</span>
                </div>
                <div className="fa-observability-turn-card-metrics">
                  <span>{formatDuration(item.latency_ms)}</span>
                  <span>{`${item.tool_calls} ${isChineseUi ? "工具" : "tools"}`}</span>
                  <span>{`${item.fallback_uses} fallback`}</span>
                </div>
              </button>
            ))}
            {!isListLoading && !orderedItems.length ? (
              <div className="fa-observability-empty">
                <p>
                  {isChineseUi
                    ? "当前筛选下没有匹配的 trajectory turn。"
                    : "No trajectory turns match the current filters."}
                </p>
                <div className="fa-observability-command-bar">
                  <button className="fa-chat-toolbar-button" onClick={() => applyPreset("all")} type="button">
                    {isChineseUi ? "查看全部样本" : "View all turns"}
                  </button>
                  <button className="fa-chat-toolbar-button" onClick={resetFilters} type="button">
                    {isChineseUi ? "清空过滤器" : "Clear filters"}
                  </button>
                </div>
              </div>
            ) : null}
          </div>

          {listError ? (
            <div
              className={`fa-inline-notice ${listError instanceof FocusAgentRequestError && listError.status === 503 ? "is-warning" : "is-danger"}`.trim()}
            >
              {listErrorMessage}
            </div>
          ) : null}
        </aside>

        <section className="fa-observability-detail-panel is-investigation" ref={detailPanelRef}>
          <div className="fa-observability-panel-header is-detail">
            <div>
              <h2>{isChineseUi ? "主分析区" : "Investigation"}</h2>
              <span>
                {selected
                  ? isChineseUi
                    ? `已选样本 · ${selected.id}`
                    : `Selected turn · ${selected.id}`
                  : isChineseUi
                    ? "左侧选中样本后，这里会展开完整执行轨迹。"
                    : "Select a turn on the left to expand the full execution trace here."}
              </span>
            </div>
          </div>

          {listError && !selected ? (
            <div className="fa-observability-empty">{listErrorMessage}</div>
          ) : !selectedTurnId ? (
            <div className="fa-observability-empty">
              {isChineseUi ? "先从左侧选择一条 turn。" : "Select a turn from the left to inspect it."}
            </div>
          ) : isDetailLoading ? (
            <div className="fa-inline-notice">{isChineseUi ? "正在加载 turn 详情..." : "Loading turn detail..."}</div>
          ) : selected ? (
            <>
              <div className="fa-observability-focus-card is-investigation-hero">
                <div className="fa-observability-focus-top">
                  <div>
                    <span className="fa-observability-focus-label">
                      {isChineseUi ? "当前样本" : "Current turn"}
                    </span>
                    <h3>{compactDetailQuestion(selected.user_message || selected.task_brief || selected.id)}</h3>
                  </div>
                  <div className="fa-observability-focus-meta">
                    <span className={`fa-observability-pill is-${statusTone(selected.status)}`}>{selected.status}</span>
                    <span>{formatDateTime(selected.created_at, locale)}</span>
                  </div>
                </div>
                <p className="fa-observability-focus-summary">
                  {resultSummary ||
                    (isChineseUi
                      ? "当前 answer 中没有可提取的结构化摘要，建议直接从下方 timeline 找异常步骤。"
                      : "No concise summary was found in the answer. Use the timeline below to locate the anomalous step." )}
                </p>
              </div>

              <div className="fa-observability-focus-stats">
                <div className="fa-observability-focus-stat">
                  <span>{isChineseUi ? "主导工具" : "Dominant tool"}</span>
                  <strong>{selectedSignals.dominantTool}</strong>
                </div>
                <div className="fa-observability-focus-stat">
                  <span>{isChineseUi ? "错误步骤" : "Error steps"}</span>
                  <strong>{formatMetric(selectedSignals.errorSteps, 0)}</strong>
                </div>
                <div className="fa-observability-focus-stat">
                  <span>{isChineseUi ? "Fallback 步骤" : "Fallback steps"}</span>
                  <strong>{formatMetric(selectedSignals.fallbackSteps, 0)}</strong>
                </div>
                <div className="fa-observability-focus-stat">
                  <span>{isChineseUi ? "Cache 步骤" : "Cache steps"}</span>
                  <strong>{formatMetric(selectedSignals.cacheSteps, 0)}</strong>
                </div>
                <div className="fa-observability-focus-stat">
                  <span>{isChineseUi ? "最长步骤" : "Longest step"}</span>
                  <strong>
                    {selectedSignals.longestStep
                      ? `${selectedSignals.longestStep.tool} · ${formatDuration(selectedSignals.longestStep.duration_ms)}`
                      : "—"}
                  </strong>
                </div>
              </div>

              <div className="fa-observability-detail-grid is-workbench">
                <div className="fa-observability-detail-main">
                  <div className="fa-observability-tool-board is-primary">
                    <div className="fa-observability-step-heading">
                      <div className="fa-observability-section-copy is-inline">
                        <p>{isChineseUi ? "执行轨迹" : "Execution trace"}</p>
                        <h3>{isChineseUi ? "时间线优先，先定位异常步骤" : "Lead with the timeline to locate the suspect step"}</h3>
                      </div>
                      <span>
                        {isChineseUi
                          ? `${selected.trajectory.length} 步 · ${selectedSignals.parallelSteps} 个并行批次`
                          : `${selected.trajectory.length} steps · ${selectedSignals.parallelSteps} parallel batches`}
                      </span>
                    </div>
                    <div className="fa-observability-step-timeline">
                      {selected.trajectory.map((step, index) => {
                        const runtimeProvider = findStepRuntimeSignal(step, ["provider", "backend"]);
                        const runtimeModel = findStepRuntimeSignal(step, ["model", "selected_model"]);
                        const runtimeRequest = findStepRuntimeSignal(step, ["request_id", "requestId"]);
                        const runtimeTrace = findStepRuntimeSignal(step, ["trace_id", "traceId", "span_id", "spanId"]);

                        return (
                          <div key={`${step.tool}-${index}`} className={`fa-observability-step-row ${severityClass(step)}`.trim()}>
                            <div className="fa-observability-step-index">{index + 1}</div>
                            <div className="fa-observability-step-body">
                              <div className="fa-observability-step-header">
                                <strong>{step.tool}</strong>
                                <span>{formatDuration(step.duration_ms)}</span>
                              </div>
                              <div className="fa-observability-step-tags">
                                {step.cache_hit ? <span className="fa-observability-pill is-success">cache</span> : null}
                                {step.fallback_used ? <span className="fa-observability-pill is-warning">fallback</span> : null}
                                {step.error ? <span className="fa-observability-pill is-danger">error</span> : null}
                                {step.fallback_group ? (
                                  <span className="fa-observability-pill is-neutral">{`group ${step.fallback_group}`}</span>
                                ) : null}
                                {step.parallel_batch_size ? (
                                  <span className="fa-observability-pill is-neutral">{`parallel ${step.parallel_batch_size}`}</span>
                                ) : null}
                                {runtimeRequest ? <span className="fa-observability-pill is-neutral">request</span> : null}
                                {runtimeTrace ? <span className="fa-observability-pill is-neutral">trace</span> : null}
                              </div>
                              {step.runtime ? (
                                <div className="fa-observability-step-runtime">
                                  {runtimeProvider ? (
                                    <span>
                                      {isChineseUi ? "Provider" : "Provider"} · {runtimeProvider}
                                    </span>
                                  ) : null}
                                  {runtimeModel ? (
                                    <span>
                                      {isChineseUi ? "Model" : "Model"} · {runtimeModel}
                                    </span>
                                  ) : null}
                                  {runtimeRequest ? (
                                    <span>
                                      Request · {compactId(runtimeRequest)}
                                    </span>
                                  ) : null}
                                  {runtimeTrace ? (
                                    <span>
                                      Trace · {compactId(runtimeTrace)}
                                    </span>
                                  ) : null}
                                </div>
                              ) : null}
                              <p className="fa-observability-step-preview">{stepObservationPreview(step.observation || step.error || "—")}</p>
                              <details className="fa-observability-raw-toggle">
                                <summary>{isChineseUi ? "查看完整观察" : "View full observation"}</summary>
                                <pre>{step.observation || step.error || "—"}</pre>
                              </details>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>

                  <div className="fa-observability-narrative-grid">
                    <div className="fa-observability-detail-block">
                      <h3>{isChineseUi ? "输入上下文" : "Input context"}</h3>
                      <p>{compactDetailQuestion(selected.user_message || selected.task_brief || "—")}</p>
                      <div className="fa-observability-inline-chip-row">
                        <span className="fa-observability-pill is-neutral">{humanizeKey(selected.scene)}</span>
                        {selected.branch_role ? (
                          <span className="fa-observability-pill is-neutral">{humanizeKey(selected.branch_role)}</span>
                        ) : null}
                      </div>
                    </div>

                    <div className="fa-observability-detail-block">
                      <h3>{isChineseUi ? "结果与错误" : "Outcome and error"}</h3>
                      <p>{resultSummary || selected.answer || "—"}</p>
                      {selected.error ? <div className="fa-inline-notice is-danger">{selected.error}</div> : null}
                      <details className="fa-observability-raw-toggle">
                        <summary>{isChineseUi ? "查看原始结果" : "View raw payload"}</summary>
                        <pre>{JSON.stringify({ answer: selected.answer, error: selected.error }, null, 2)}</pre>
                      </details>
                    </div>
                  </div>
                </div>

                <aside className="fa-observability-detail-side is-inspector">
                  <div className="fa-observability-detail-block">
                    <h3>{isChineseUi ? "运行画像" : "Turn profile"}</h3>
                    <div className="fa-observability-meta-grid">
                      <div className="fa-observability-meta-item">
                        <span>{isChineseUi ? "线程" : "Thread"}</span>
                        <strong>{compactId(selected.thread_id)}</strong>
                      </div>
                      <div className="fa-observability-meta-item">
                        <span>{isChineseUi ? "根线程" : "Root"}</span>
                        <strong>{compactId(selected.root_thread_id)}</strong>
                      </div>
                      <div className="fa-observability-meta-item">
                        <span>{isChineseUi ? "模型" : "Model"}</span>
                        <strong>{selected.selected_model || "—"}</strong>
                      </div>
                      <div className="fa-observability-meta-item">
                        <span>{isChineseUi ? "思考模式" : "Thinking mode"}</span>
                        <strong>{selected.selected_thinking_mode || "—"}</strong>
                      </div>
                      <div className="fa-observability-meta-item">
                        <span>{isChineseUi ? "场景" : "Scene"}</span>
                        <strong>{humanizeKey(selected.scene)}</strong>
                      </div>
                      <div className="fa-observability-meta-item">
                        <span>{isChineseUi ? "分支角色" : "Branch role"}</span>
                        <strong>{humanizeKey(selected.branch_role)}</strong>
                      </div>
                      <div className="fa-observability-meta-item">
                        <span>{isChineseUi ? "延迟" : "Latency"}</span>
                        <strong>{formatDuration(selected.latency_ms)}</strong>
                      </div>
                      <div className="fa-observability-meta-item">
                        <span>{isChineseUi ? "工具调用" : "Tool calls"}</span>
                        <strong>{formatMetric(selected.tool_calls, 0)}</strong>
                      </div>
                      <div className="fa-observability-meta-item">
                        <span>{isChineseUi ? "Cache Hits" : "Cache hits"}</span>
                        <strong>{formatMetric(selected.cache_hits, 0)}</strong>
                      </div>
                      <div className="fa-observability-meta-item">
                        <span>{isChineseUi ? "Fallback" : "Fallback"}</span>
                        <strong>{formatMetric(selected.fallback_uses, 0)}</strong>
                      </div>
                    </div>
                  </div>

                  <div className="fa-observability-detail-block">
                    <div className="fa-observability-block-heading">
                      <div>
                        <h3>{isChineseUi ? "关联锚点" : "Correlation hooks"}</h3>
                        <p>
                          {isChineseUi
                            ? "优先显示 turn/thread 主键，如果 metadata 里已有 request / trace 线索，也会一起挂出来。"
                            : "Show turn and thread anchors first, then surface request/trace clues whenever metadata already carries them."}
                        </p>
                      </div>
                      <span className="fa-observability-pill is-neutral">
                        {isChineseUi ? `${correlationSignals.length} 项` : `${correlationSignals.length} signals`}
                      </span>
                    </div>
                    <div className="fa-observability-correlation-list">
                      {correlationSignals.map((signal) => (
                        <div key={signal.id} className="fa-observability-correlation-item">
                          <div>
                            <span>{isChineseUi ? signal.labelZh : signal.labelEn}</span>
                            <strong className={signal.tone === "accent" ? "is-accent" : ""}>{signal.value}</strong>
                          </div>
                          <button
                            className="fa-chat-toolbar-button"
                            onClick={() => copyText(signal.value)}
                            type="button"
                          >
                            {isChineseUi ? "复制" : "Copy"}
                          </button>
                        </div>
                      ))}
                    </div>
                    {correlationCoverage === 0 ? (
                      <div className="fa-inline-notice">
                        {isChineseUi
                          ? "当前样本还没有显式 request / trace / span 字段，页面会继续从 plan/runtime metadata 里自动探测。"
                          : "This turn does not expose explicit request/trace/span fields yet. The page will keep probing plan/runtime metadata automatically."}
                      </div>
                    ) : null}
                  </div>

                  <div className="fa-observability-detail-block">
                    <div className="fa-observability-block-heading">
                      <div>
                        <h3>{isChineseUi ? "当前样本的 Pivot 动作" : "Selected-turn pivots"}</h3>
                        <p>
                          {isChineseUi
                            ? "这些动作直接修改左侧 explorer 的筛选条件，不会丢掉当前样本。"
                            : "These actions update the explorer filters directly without dropping the current turn."}
                        </p>
                      </div>
                    </div>
                    <div className="fa-observability-pivot-grid is-compact">
                      {pivotActions.slice(0, 4).map((action) => (
                        <button
                          key={`detail-${action.id}`}
                          className={`fa-observability-pivot-button ${action.disabled ? "is-disabled" : ""}`.trim()}
                          disabled={action.disabled}
                          onClick={action.action}
                          type="button"
                        >
                          <strong>{action.label}</strong>
                          <span>{compactSnippet(action.caption, 64) || "—"}</span>
                        </button>
                      ))}
                    </div>
                  </div>

                  <div className="fa-observability-detail-block">
                    <h3>{isChineseUi ? "范围信号" : "Scope signals"}</h3>
                    <div className="fa-observability-status-strip">
                      <div>
                        <span>{isChineseUi ? "失败数" : "Failed turns"}</span>
                        <strong>{isStatsLoading ? "…" : formatMetric(statsOverview?.non_succeeded_count, 0)}</strong>
                      </div>
                      <div>
                        <span>{isChineseUi ? "Fallback 总数" : "Fallback uses"}</span>
                        <strong>{isStatsLoading ? "…" : formatMetric(statsOverview?.total_fallback_uses, 0)}</strong>
                      </div>
                      <div>
                        <span>{isChineseUi ? "Cache Hits" : "Cache hits"}</span>
                        <strong>{isStatsLoading ? "…" : formatMetric(statsOverview?.total_cache_hits, 0)}</strong>
                      </div>
                    </div>
                  </div>

                  <div className="fa-observability-detail-block">
                    <h3>{isChineseUi ? "热点工具" : "Hot tools"}</h3>
                    {hottestTools.length ? (
                      <div className="fa-observability-tool-list">
                        {hottestTools.map((tool) => (
                          <button
                            key={tool.key}
                            className={`fa-observability-tool-row ${toolFilter.trim() === String(tool.key ?? "") ? "is-active" : ""}`}
                            onClick={() => setToolFilter(String(tool.key ?? ""))}
                            type="button"
                          >
                            <div>
                              <strong>{tool.key}</strong>
                              <span>
                                {isChineseUi
                                  ? `${formatMetric(tool.turn_count, 0)} 个 turn`
                                  : `${formatMetric(tool.turn_count, 0)} turns`}
                              </span>
                            </div>
                            <span>{formatDuration(tool.avg_duration_ms)}</span>
                          </button>
                        ))}
                      </div>
                    ) : (
                      <div className="fa-observability-empty is-compact">
                        {isChineseUi ? "暂无工具分布数据。" : "Tool distribution is not available yet."}
                      </div>
                    )}
                  </div>

                  <div className="fa-observability-detail-block">
                    <h3>{isChineseUi ? "快捷动作" : "Quick actions"}</h3>
                    <div className="fa-observability-command-bar">
                      <button className="fa-chat-toolbar-button" onClick={() => copyText(commandSnippet)} type="button">
                        {isChineseUi ? "复制 CLI 查看命令" : "Copy CLI inspect command"}
                      </button>
                      <button className="fa-chat-toolbar-button" onClick={downloadSelectedRecord} type="button">
                        {isChineseUi ? "下载 JSON" : "Download JSON"}
                      </button>
                    </div>
                  </div>

                  <TrajectoryActionPanel isChineseUi={isChineseUi} selected={selected} />
                </aside>
              </div>
            </>
          ) : (
            <div className="fa-observability-empty">
              {isChineseUi ? "当前 turn 不存在或尚未可用。" : "This trajectory turn is unavailable."}
            </div>
          )}
        </section>
      </section>
    </div>
  );
}
