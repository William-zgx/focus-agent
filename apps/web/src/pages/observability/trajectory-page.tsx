import {
  FocusAgentRequestError,
  type FocusAgentTrajectoryListRequest,
  type FocusAgentTrajectoryStatsRow,
  type FocusAgentTrajectoryStep,
  type FocusAgentTrajectoryTurnDetail,
  type FocusAgentTrajectoryTurnSummary,
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
import { TrajectoryActionPanel } from "@/features/trajectory-observability/trajectory-action-panel";
import { TrajectoryOverviewDashboard } from "@/features/trajectory-observability/trajectory-overview-dashboard";
import { TrajectoryWorkbenchHeader } from "@/features/trajectory-observability/trajectory-workbench-header";
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
type EvidenceMode = "timeline" | "zero_step" | "missing_detail";
type ReviewSummary = {
  headline: string;
  lead: string;
  status: string;
  createdAt: string;
  evidenceLabel: string;
  stats: Array<{
    id: string;
    labelZh: string;
    labelEn: string;
    value: string;
  }>;
};
type ActionRailSection = {
  id: string;
  titleZh: string;
  titleEn: string;
  captionZh: string;
  captionEn: string;
  count?: string;
};
type ActionRailSections = ActionRailSection[];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function getSearchParams(search?: unknown) {
  if (search instanceof URLSearchParams) {
    return new URLSearchParams(search);
  }
  if (typeof search === "string") {
    return new URLSearchParams(search);
  }
  if (isRecord(search)) {
    const params = new URLSearchParams();
    Object.entries(search).forEach(([key, rawValue]) => {
      if (rawValue === undefined || rawValue === null) return;
      if (Array.isArray(rawValue)) {
        rawValue.forEach((item) => {
          if (item === undefined || item === null) return;
          params.append(key, String(item));
        });
        return;
      }
      params.set(key, String(rawValue));
    });
    return params;
  }
  if (typeof window === "undefined") {
    return new URLSearchParams();
  }
  return new URLSearchParams(window.location.search);
}

function readSearchParam(key: string, search?: unknown) {
  return getSearchParams(search).get(key) ?? "";
}

function readInitialSearchParam(key: string, search?: unknown) {
  return readSearchParam(key, search);
}

function readSearchFlag(key: string, fallback = false, search?: unknown) {
  const value = readSearchParam(key, search);
  if (!value) return fallback;
  return value === "1" || value === "true";
}

function readSearchStatus(search?: unknown): StatusMode {
  const value = readSearchParam("status", search);
  if (value === "all" || value === "failed" || value === "succeeded")
    return value;
  return "all";
}

function readSearchSort(search?: unknown): SortMode {
  const value = readSearchParam("sort", search);
  if (value === "newest" || value === "latency" || value === "tool_calls")
    return value;
  return "newest";
}

function readSearchState(search?: unknown) {
  return {
    statusFilter: readSearchStatus(search),
    toolFilter: readSearchParam("tool", search),
    threadFilter: readSearchParam("thread", search),
    requestFilter: readSearchParam("request", search),
    traceFilter: readSearchParam("trace", search),
    modelFilter: readSearchParam("model", search),
    minLatency: readSearchParam("minLatency", search),
    fallbackOnly: readSearchFlag("fallbackOnly", false, search),
    hasErrorOnly: readSearchFlag("hasErrorOnly", false, search),
    sortMode: readSearchSort(search),
    selectedTurnId: readSearchParam("turn", search),
  };
}

function shouldExpandFiltersFromSearch(search?: unknown) {
  const state = readSearchState(search);
  return (
    Boolean(state.toolFilter) ||
    Boolean(state.threadFilter) ||
    Boolean(state.requestFilter) ||
    Boolean(state.traceFilter) ||
    Boolean(state.modelFilter) ||
    Boolean(state.minLatency) ||
    state.fallbackOnly ||
    state.hasErrorOnly ||
    state.statusFilter !== "all" ||
    state.sortMode !== "newest"
  );
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

function formatDateTime(
  value?: string | null,
  locale: "zh-CN" | "en-US" = "en-US",
) {
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
  const text = String(value || "")
    .replace(/\s+/g, " ")
    .trim();
  if (!text) return "—";
  if (text.length <= 54) return text;
  return `${text.slice(0, 54)}…`;
}

function compactDetailQuestion(value?: string | null) {
  const text = String(value || "")
    .replace(/\s+/g, " ")
    .trim();
  if (!text) return "—";
  if (text.length <= 160) return text;
  return `${text.slice(0, 160)}…`;
}

function extractStructuredSummary(value?: string | null) {
  const text = String(value || "").trim();
  if (!text) return "";
  const matches = [
    ...text.matchAll(/reasoning_content['"]?\s*:\s*['"]([^'"]+)['"]/g),
  ]
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
  const text = String(value || "")
    .replace(/\s+/g, " ")
    .trim();
  if (!text) return "—";
  if (text.length <= 140) return text;
  return `${text.slice(0, 140)}…`;
}

function compactSnippet(value?: string | null, max = 88) {
  const text = String(value || "")
    .replace(/\s+/g, " ")
    .trim();
  if (!text) return "";
  if (text.length <= max) return text;
  return `${text.slice(0, max)}…`;
}

function stringifyMetadataValue(value: unknown) {
  if (value === undefined || value === null) return "";
  if (typeof value === "string") return value.trim();
  if (typeof value === "number" || typeof value === "boolean")
    return String(value);
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

function findMetadataAcrossSources(
  sources: unknown[],
  aliases: readonly string[],
) {
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

const BRANCH_ROLE_LABELS: Record<string, { zh: string; en: string }> = {
  main: { zh: "主线", en: "Main" },
  explore_alternatives: { zh: "备选方案", en: "Alternative path" },
  deep_dive: { zh: "深入分析", en: "Deep dive" },
  execute: { zh: "执行", en: "Execution" },
  verify: { zh: "验证", en: "Verification" },
  writeup: { zh: "整理", en: "Writeup" },
};

const SCENE_LABELS: Record<string, { zh: string; en: string }> = {
  long_dialog_research: { zh: "长对话研究", en: "Long dialog research" },
  technical_deep_dive: { zh: "技术深挖", en: "Technical deep dive" },
};

function humanizeKey(value?: string | null) {
  const text = String(value || "").trim();
  if (!text) return "—";
  return text.replace(/[_-]+/g, " ");
}

function labelFromMap(
  value: string | null | undefined,
  map: Record<string, { zh: string; en: string }>,
  isChineseUi: boolean,
) {
  const normalized = String(value || "").trim();
  if (!normalized) return "—";
  const mapped = map[normalized];
  if (mapped) {
    return isChineseUi ? mapped.zh : mapped.en;
  }
  return humanizeKey(normalized);
}

function formatBranchRoleLabel(
  value: string | null | undefined,
  isChineseUi: boolean,
) {
  return labelFromMap(value, BRANCH_ROLE_LABELS, isChineseUi);
}

function formatSceneLabel(
  value: string | null | undefined,
  isChineseUi: boolean,
) {
  return labelFromMap(value, SCENE_LABELS, isChineseUi);
}

function getDominantTool(trajectory: FocusAgentTrajectoryStep[]) {
  const counts = new Map<string, number>();
  trajectory.forEach((step) => {
    counts.set(step.tool, (counts.get(step.tool) ?? 0) + 1);
  });
  return (
    [...counts.entries()].sort((left, right) => right[1] - left[1])[0]?.[0] ??
    "—"
  );
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

function topStatsRows(
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

function ratio(numerator?: number, denominator?: number) {
  if (
    typeof numerator !== "number" ||
    typeof denominator !== "number" ||
    denominator <= 0
  )
    return undefined;
  return numerator / denominator;
}

function findStepRuntimeSignal(
  step: FocusAgentTrajectoryStep,
  aliases: readonly string[],
) {
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

function buildTurnSummary(
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

function buildCorrelationSignals(
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

function findCorrelationSignalValue(signals: CorrelationSignal[], id: string) {
  return signals.find((signal) => signal.id === id)?.value ?? "";
}

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

  const orderedItems = useMemo(() => {
    const items = [...(listData?.items ?? [])];
    if (sortMode === "latency") {
      items.sort(
        (left, right) => (right.latency_ms ?? 0) - (left.latency_ms ?? 0),
      );
      return items;
    }
    if (sortMode === "tool_calls") {
      items.sort(
        (left, right) => (right.tool_calls ?? 0) - (left.tool_calls ?? 0),
      );
      return items;
    }
    return items;
  }, [listData?.items, sortMode]);
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
  const actionRailSections = useMemo<ActionRailSections>(
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

  const [
    anchorsSection,
    pivotsSection,
    toolsSection,
    quickSection,
    actionsSection,
  ] = actionRailSections;

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
            <div className="fa-trajectory-workbench-panel-head">
              <div className="fa-trajectory-workbench-panel-copy">
                <p>{isChineseUi ? "先选样本" : "Sample queue"}</p>
                <h2>{isChineseUi ? "高密度样本队列" : "High-density sample queue"}</h2>
                <span>
                  {isChineseUi
                    ? "把筛选和空态都收在左栏里，尽量提高同屏可见的样本数。"
                    : "Keep filters and list-state handling inside the left rail to maximize visible samples."}
                </span>
              </div>
              <strong>{isListLoading ? "…" : formatMetric(matchCount, 0)}</strong>
            </div>

            <div className="fa-trajectory-workbench-explorer-bar">
              <div className="fa-observability-presets">
                <button
                  className="fa-observability-preset"
                  onClick={() => applyPreset("failures")}
                  type="button"
                >
                  {isChineseUi ? "最近失败" : "Failures"}
                </button>
                <button
                  className="fa-observability-preset"
                  onClick={() => applyPreset("fallback")}
                  type="button"
                >
                  {isChineseUi ? "Fallback" : "Fallback"}
                </button>
                <button
                  className="fa-observability-preset"
                  onClick={() => applyPreset("latency")}
                  type="button"
                >
                  {isChineseUi ? "高延迟" : "Latency"}
                </button>
                <button
                  className="fa-observability-preset"
                  onClick={() => applyPreset("all")}
                  type="button"
                >
                  {isChineseUi ? "全部" : "All"}
                </button>
              </div>

              <div className="fa-observability-active-filters">
                {filterChips.length ? (
                  filterChips.map((chip) => (
                    <button
                      key={chip.id}
                      className="fa-observability-filter-chip"
                      onClick={chip.clear}
                      type="button"
                    >
                      <span>{isChineseUi ? chip.labelZh : chip.labelEn}</span>
                      <strong>×</strong>
                    </button>
                  ))
                ) : (
                  <span className="fa-observability-filter-chip is-empty">
                    {isChineseUi
                      ? "当前没有附加过滤器"
                      : "No extra filters active"}
                  </span>
                )}
              </div>

              <div className="fa-observability-filter-drawer">
                <button
                  aria-expanded={filtersExpanded}
                  className="fa-observability-filter-toggle"
                  onClick={() => setFiltersExpanded((current) => !current)}
                  type="button"
                >
                  {filtersExpanded
                    ? isChineseUi
                      ? "收起高级筛选"
                      : "Hide advanced filters"
                    : isChineseUi
                      ? "展开高级筛选"
                      : "Show advanced filters"}
                </button>
                {filtersExpanded ? (
                  <div className="fa-observability-filter-shell">
                    <div className="fa-observability-filters is-compact">
                      <label className="fa-observability-filter">
                        <span>{isChineseUi ? "状态" : "Status"}</span>
                        <select
                          value={statusFilter}
                          onChange={(event) =>
                            setStatusFilter(event.target.value as StatusMode)
                          }
                        >
                          <option value="failed">
                            {isChineseUi ? "失败" : "Failed"}
                          </option>
                          <option value="all">
                            {isChineseUi ? "全部" : "All"}
                          </option>
                          <option value="succeeded">
                            {isChineseUi ? "成功" : "Succeeded"}
                          </option>
                        </select>
                      </label>
                      <label className="fa-observability-filter">
                        <span>{isChineseUi ? "工具" : "Tool"}</span>
                        <input
                          value={toolFilter}
                          onChange={(event) => setToolFilter(event.target.value)}
                          placeholder="web_search"
                        />
                      </label>
                      <label className="fa-observability-filter">
                        <span>{isChineseUi ? "线程" : "Thread"}</span>
                        <input
                          value={threadFilter}
                          onChange={(event) => setThreadFilter(event.target.value)}
                          placeholder="thread-…"
                        />
                      </label>
                      <label className="fa-observability-filter">
                        <span>{isChineseUi ? "Request" : "Request"}</span>
                        <input
                          value={requestFilter}
                          onChange={(event) => setRequestFilter(event.target.value)}
                          placeholder="req-…"
                        />
                      </label>
                      <label className="fa-observability-filter">
                        <span>{isChineseUi ? "Trace" : "Trace"}</span>
                        <input
                          value={traceFilter}
                          onChange={(event) => setTraceFilter(event.target.value)}
                          placeholder="trace-…"
                        />
                      </label>
                      <label className="fa-observability-filter">
                        <span>{isChineseUi ? "模型" : "Model"}</span>
                        <input
                          value={modelFilter}
                          onChange={(event) => setModelFilter(event.target.value)}
                          placeholder="openai:gpt-4.1-mini"
                        />
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
                        <select
                          value={sortMode}
                          onChange={(event) =>
                            setSortMode(event.target.value as SortMode)
                          }
                        >
                          <option value="newest">
                            {isChineseUi ? "最近" : "Newest"}
                          </option>
                          <option value="latency">
                            {isChineseUi ? "延迟" : "Latency"}
                          </option>
                          <option value="tool_calls">
                            {isChineseUi ? "工具数" : "Tool calls"}
                          </option>
                        </select>
                      </label>
                      <label className="fa-observability-toggle">
                        <input
                          checked={fallbackOnly}
                          onChange={(event) =>
                            setFallbackOnly(event.target.checked)
                          }
                          type="checkbox"
                        />
                        <span>
                          {isChineseUi ? "仅看 fallback" : "Fallback only"}
                        </span>
                      </label>
                      <label className="fa-observability-toggle">
                        <input
                          checked={hasErrorOnly}
                          onChange={(event) =>
                            setHasErrorOnly(event.target.checked)
                          }
                          type="checkbox"
                        />
                        <span>{isChineseUi ? "仅看错误" : "Errors only"}</span>
                      </label>
                    </div>

                    <div className="fa-observability-command-bar">
                      {hasInvalidLatency ? (
                        <span className="fa-observability-filter-hint is-warning">
                          {isChineseUi
                            ? "最小延迟需要是非负数字。"
                            : "Min latency must be a non-negative number."}
                        </span>
                      ) : null}
                      <button
                        className="fa-chat-toolbar-button"
                        onClick={resetFilters}
                        type="button"
                      >
                        {isChineseUi ? "恢复默认" : "Reset"}
                      </button>
                    </div>
                  </div>
                ) : null}
              </div>
            </div>

            <div className="fa-trajectory-workbench-batch-toolbar">
              <div>
                <span>{isChineseUi ? "批量治理选择" : "Batch governance selection"}</span>
                <strong>
                  {isChineseUi
                    ? `${selectedBatchTurnIds.length} 条已勾选`
                    : `${selectedBatchTurnIds.length} selected`}
                </strong>
              </div>
              <div className="fa-observability-command-bar">
                <button
                  className="fa-chat-toolbar-button"
                  disabled={!orderedItems.length}
                  onClick={selectVisibleBatch}
                  type="button"
                >
                  {isChineseUi ? "勾选当前页" : "Select visible"}
                </button>
                <button
                  className="fa-chat-toolbar-button"
                  disabled={!orderedItems.some((item) => item.status !== "succeeded" || item.error)}
                  onClick={selectVisibleFailuresBatch}
                  type="button"
                >
                  {isChineseUi ? "仅勾选失败" : "Select failures"}
                </button>
                <button
                  className="fa-chat-toolbar-button"
                  disabled={!selectedBatchTurnIds.length}
                  onClick={clearBatchSelection}
                  type="button"
                >
                  {isChineseUi ? "清空" : "Clear"}
                </button>
              </div>
            </div>

            <div className="fa-trajectory-workbench-sample-list">
              {orderedItems.map((item) => (
                <div
                  key={item.id}
                  className={`fa-trajectory-workbench-sample-row ${selectedBatchIdSet.has(item.id) ? "is-batch-selected" : ""}`.trim()}
                >
                  <label className="fa-trajectory-workbench-batch-checkbox">
                    <input
                      checked={selectedBatchIdSet.has(item.id)}
                      onChange={() => toggleBatchSelection(item.id)}
                      type="checkbox"
                    />
                    <span>{isChineseUi ? "批量" : "Batch"}</span>
                  </label>
                  <button
                    className={`fa-trajectory-workbench-sample-card ${selectedTurnId === item.id ? "is-selected" : ""}`.trim()}
                    onClick={() => setSelectedTurnId(item.id)}
                    type="button"
                  >
                  <div className="fa-trajectory-workbench-sample-top">
                    <span
                      className={`fa-observability-pill is-${statusTone(item.status)}`}
                    >
                      {item.status}
                    </span>
                    <span>{formatDateTime(item.created_at, locale)}</span>
                  </div>
                  <strong>
                    {compactQuestion(item.user_message || item.task_brief || item.id)}
                  </strong>
                  <p className="fa-trajectory-workbench-sample-summary">
                    {buildTurnSummary(item, isChineseUi)}
                  </p>
                  <div className="fa-trajectory-workbench-sample-anchors">
                    <span>{`Req ${compactId(item.request_id)}`}</span>
                    <span>{`Trace ${compactId(item.trace_id)}`}</span>
                  </div>
                  <div className="fa-trajectory-workbench-sample-anchors">
                    <span>{compactId(item.thread_id)}</span>
                    <span>{item.selected_model || "—"}</span>
                  </div>
                  <div className="fa-trajectory-workbench-sample-metrics">
                    <span>{formatDuration(item.latency_ms)}</span>
                    <span>{`${item.tool_calls} ${isChineseUi ? "工具" : "tools"}`}</span>
                    <span>{`${item.fallback_uses} fallback`}</span>
                  </div>
                  </button>
                </div>
              ))}

              {!isListLoading && !orderedItems.length ? (
                <div className="fa-observability-empty">
                  <p>
                    {isChineseUi
                      ? "当前筛选下没有匹配的复盘样本。"
                      : "No trajectory turns match the current filters."}
                  </p>
                  <div className="fa-observability-command-bar">
                    <button
                      className="fa-chat-toolbar-button"
                      onClick={() => applyPreset("all")}
                      type="button"
                    >
                      {isChineseUi ? "查看全部样本" : "View all turns"}
                    </button>
                    <button
                      className="fa-chat-toolbar-button"
                      onClick={resetFilters}
                      type="button"
                    >
                      {isChineseUi ? "清空过滤器" : "Clear filters"}
                    </button>
                  </div>
                </div>
              ) : null}

              {listError ? (
                <div
                  className={`fa-inline-notice ${listError instanceof FocusAgentRequestError && listError.status === 503 ? "is-warning" : "is-danger"}`.trim()}
                >
                  {listErrorMessage}
                </div>
              ) : null}
            </div>
          </aside>

          <section
            className="fa-trajectory-workbench-column is-canvas"
            ref={detailPanelRef}
          >
            {!selectedTurnId ? (
              <div className="fa-observability-empty">
                {isChineseUi
                  ? "先从左侧样本队列里选一条 case。"
                  : "Pick a case from the sample queue first."}
              </div>
            ) : isDetailLoading ? (
              <div className="fa-inline-notice">
                {isChineseUi ? "正在加载 turn 详情..." : "Loading turn detail..."}
              </div>
            ) : selected ? (
              <>
                {reviewSummary ? (
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
                        <div
                          key={item.id}
                          className="fa-trajectory-workbench-summary-metric"
                        >
                          <span>{isChineseUi ? item.labelZh : item.labelEn}</span>
                          <strong>{item.value}</strong>
                        </div>
                      ))}
                    </div>
                  </article>
                ) : null}

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
                    <div className="fa-inline-notice is-danger">
                      {selected.error}
                    </div>
                  ) : null}

                  {evidenceMode === "timeline" ? (
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
                            <div className="fa-observability-step-index">
                              {index + 1}
                            </div>
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
                                  <span className="fa-observability-pill is-danger">
                                    error
                                  </span>
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
                                    <span>{`Request · ${compactId(runtimeRequest)}`}</span>
                                  ) : null}
                                  {runtimeTrace ? (
                                    <span>{`Trace · ${compactId(runtimeTrace)}`}</span>
                                  ) : null}
                                </div>
                              ) : null}
                              <p className="fa-observability-step-preview">
                                {stepObservationPreview(
                                  step.observation || step.error || "—",
                                )}
                              </p>
                              <details className="fa-observability-raw-toggle">
                                <summary>
                                  {isChineseUi
                                    ? "查看完整观察"
                                    : "View full observation"}
                                </summary>
                                <pre>{step.observation || step.error || "—"}</pre>
                              </details>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ) : evidenceMode === "zero_step" ? (
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
                                {
                                  answer: selected.answer,
                                  error: selected.error,
                                },
                                null,
                                2,
                              )}
                            </pre>
                          </details>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="fa-observability-empty">
                      {isChineseUi
                        ? "当前样本的详情暂时不可用。"
                        : "This turn detail is temporarily unavailable."}
                    </div>
                  )}
                </article>

                <div className="fa-trajectory-workbench-story-grid">
                  <article className="fa-trajectory-workbench-story-card">
                    <div className="fa-trajectory-workbench-section-head">
                      <div>
                        <p>{isChineseUi ? "输入叙事" : "Input narrative"}</p>
                        <h3>
                          {isChineseUi ? "用户是怎么把问题带进来的" : "How the user brought the task in"}
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
                      <summary>
                        {isChineseUi ? "查看原始输入" : "View raw input"}
                      </summary>
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
                      <div className="fa-inline-notice is-danger">
                        {selected.error}
                      </div>
                    ) : null}
                    <details className="fa-observability-raw-toggle">
                      <summary>
                        {isChineseUi ? "查看原始结果" : "View raw payload"}
                      </summary>
                      <pre>
                        {JSON.stringify(
                          {
                            answer: selected.answer,
                            error: selected.error,
                          },
                          null,
                          2,
                        )}
                      </pre>
                    </details>
                  </article>
                </div>

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
                      <div
                        key={item.id}
                        className="fa-observability-meta-item"
                      >
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
                        <summary>
                          {isChineseUi ? "查看 metrics" : "View metrics"}
                        </summary>
                        <pre>{JSON.stringify(selected.metrics, null, 2)}</pre>
                      </details>
                    ) : null}
                  </div>
                </article>
              </>
            ) : (
              <div className="fa-observability-empty">
                {isChineseUi
                  ? "当前样本不存在或详情尚未可用。"
                  : "This trajectory turn is unavailable."}
              </div>
            )}
          </section>

          <aside className="fa-trajectory-workbench-column is-rail">
            {selected ? (
              <div className="fa-trajectory-workbench-rail">
                <section className="fa-trajectory-workbench-rail-section">
                  <div className="fa-trajectory-workbench-section-head">
                    <div>
                      <p>{isChineseUi ? anchorsSection.titleZh : anchorsSection.titleEn}</p>
                      <h3>
                        {isChineseUi
                          ? "交接和 deep link 用到的锚点"
                          : "Anchors for handoff and deep links"}
                      </h3>
                      <span>{isChineseUi ? anchorsSection.captionZh : anchorsSection.captionEn}</span>
                    </div>
                    {anchorsSection.count ? <strong>{anchorsSection.count}</strong> : null}
                  </div>
                  <div className="fa-observability-correlation-list">
                    {correlationSignals.map((signal) => (
                      <div
                        key={signal.id}
                        className="fa-observability-correlation-item"
                      >
                        <div>
                          <span>{isChineseUi ? signal.labelZh : signal.labelEn}</span>
                          <strong className={signal.tone === "accent" ? "is-accent" : ""}>
                            {signal.value}
                          </strong>
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
                        ? "当前样本还没有显式 request / trace / span 字段，页面会继续从 metadata 里自动探测。"
                        : "This turn does not expose explicit request/trace/span fields yet, so the page keeps probing metadata."}
                    </div>
                  ) : null}
                </section>

                <section className="fa-trajectory-workbench-rail-section">
                  <div className="fa-trajectory-workbench-section-head">
                    <div>
                      <p>{isChineseUi ? pivotsSection.titleZh : pivotsSection.titleEn}</p>
                      <h3>
                        {isChineseUi ? "Pivot 动作与范围信号" : "Pivot actions and scope signals"}
                      </h3>
                      <span>{isChineseUi ? pivotsSection.captionZh : pivotsSection.captionEn}</span>
                    </div>
                  </div>
                  <div className="fa-observability-pivot-grid">
                    {pivotActions.map((action) => (
                      <button
                        key={`rail-${action.id}`}
                        className={`fa-observability-pivot-button ${action.disabled ? "is-disabled" : ""}`.trim()}
                        disabled={action.disabled}
                        onClick={action.action}
                        type="button"
                      >
                        <strong>{action.label}</strong>
                        <span>{compactSnippet(action.caption, 72) || "—"}</span>
                      </button>
                    ))}
                  </div>
                  <div className="fa-observability-status-strip">
                    <div>
                      <span>{isChineseUi ? "失败数" : "Failed turns"}</span>
                      <strong>
                        {isStatsLoading
                          ? "…"
                          : formatMetric(statsOverview?.non_succeeded_count, 0)}
                      </strong>
                    </div>
                    <div>
                      <span>{isChineseUi ? "Fallback 总数" : "Fallback uses"}</span>
                      <strong>
                        {isStatsLoading
                          ? "…"
                          : formatMetric(statsOverview?.total_fallback_uses, 0)}
                      </strong>
                    </div>
                    <div>
                      <span>{isChineseUi ? "Cache Hits" : "Cache hits"}</span>
                      <strong>
                        {isStatsLoading
                          ? "…"
                          : formatMetric(statsOverview?.total_cache_hits, 0)}
                      </strong>
                    </div>
                  </div>
                </section>

                <section className="fa-trajectory-workbench-rail-section">
                  <div className="fa-trajectory-workbench-section-head">
                    <div>
                      <p>{isChineseUi ? toolsSection.titleZh : toolsSection.titleEn}</p>
                      <h3>{isChineseUi ? "热点工具" : "Hot tools"}</h3>
                      <span>{isChineseUi ? toolsSection.captionZh : toolsSection.captionEn}</span>
                    </div>
                    {toolsSection.count ? <strong>{toolsSection.count}</strong> : null}
                  </div>
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
                                ? `${formatMetric(tool.turn_count, 0)} 条样本`
                                : `${formatMetric(tool.turn_count, 0)} turns`}
                            </span>
                          </div>
                          <span>{formatDuration(tool.avg_duration_ms)}</span>
                        </button>
                      ))}
                    </div>
                  ) : (
                    <div className="fa-observability-empty is-compact">
                      {isChineseUi
                        ? "暂无工具分布数据。"
                        : "Tool distribution is not available yet."}
                    </div>
                  )}
                </section>

                <section className="fa-trajectory-workbench-rail-section">
                  <div className="fa-trajectory-workbench-section-head">
                    <div>
                      <p>{isChineseUi ? quickSection.titleZh : quickSection.titleEn}</p>
                      <h3>{isChineseUi ? "快捷动作" : "Quick actions"}</h3>
                      <span>{isChineseUi ? quickSection.captionZh : quickSection.captionEn}</span>
                    </div>
                  </div>
                  <div className="fa-observability-command-bar">
                    <button
                      className="fa-chat-toolbar-button"
                      onClick={handleCopyLink}
                      type="button"
                    >
                      {isChineseUi ? "复制链接" : "Copy link"}
                    </button>
                    {commandSnippet ? (
                      <button
                        className="fa-chat-toolbar-button"
                        onClick={handleCopyCommand}
                        type="button"
                      >
                        {isChineseUi ? "复制 CLI 命令" : "Copy CLI command"}
                      </button>
                    ) : null}
                    <button
                      className="fa-chat-toolbar-button"
                      onClick={downloadSelectedRecord}
                      type="button"
                    >
                      {isChineseUi ? "下载 JSON" : "Download JSON"}
                    </button>
                  </div>
                </section>

                <section className="fa-trajectory-workbench-rail-section is-action-panel">
                  <div className="fa-trajectory-workbench-section-head">
                    <div>
                      <p>{isChineseUi ? actionsSection.titleZh : actionsSection.titleEn}</p>
                      <h3>{isChineseUi ? "复盘动作" : "Replay actions"}</h3>
                      <span>{isChineseUi ? actionsSection.captionZh : actionsSection.captionEn}</span>
                    </div>
                  </div>
                  <TrajectoryActionPanel
                    batchItems={selectedBatchItems}
                    isChineseUi={isChineseUi}
                    onClearBatchSelection={clearBatchSelection}
                    selected={selected}
                  />
                </section>
              </div>
            ) : (
              <div className="fa-observability-empty">
                {isChineseUi
                  ? "选择样本后，这里会常驻显示关联锚点、热点工具和 Replay 动作。"
                  : "Select a turn to keep the anchors, hotspots, and replay actions resident in this rail."}
              </div>
            )}
          </aside>
        </section>
      )}
    </div>
  );
}
