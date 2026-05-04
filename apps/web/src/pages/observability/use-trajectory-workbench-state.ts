import type { FocusAgentTrajectoryListRequest } from "@focus-agent/web-sdk";
import { useDeferredValue, useEffect, useMemo, useState } from "react";

import {
  type PresetMode,
  type SortMode,
  type StatusMode,
  buildFilterChips,
  normalizeStatusFilter,
  parseNonNegativeNumber,
  readInitialSearchParam,
  readSearchFlag,
  readSearchParam,
  readSearchSort,
  readSearchState,
  readSearchStatus,
  shouldExpandFiltersFromSearch,
} from "@/features/trajectory-observability/trajectory-utils";

export function useTrajectoryWorkbenchState(routerSearch: string) {
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

  function resetPresetFilters() {
    setStatusFilter("all");
    setFallbackOnly(false);
    setHasErrorOnly(false);
    setMinLatency("");
    setSortMode("newest");
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
    resetPresetFilters();
  }

  function resetFilters() {
    setToolFilter("");
    setThreadFilter("");
    setRequestFilter("");
    setTraceFilter("");
    setModelFilter("");
    resetPresetFilters();
  }

  function focusFilter(
    value: string,
    apply: (normalizedValue: string) => void,
  ) {
    const normalized = value.trim();
    if (!normalized) return;
    apply(normalized);
    setFiltersExpanded(true);
  }

  return {
    deferredFilters,
    fallbackOnly,
    filterChips,
    filters,
    filtersExpanded,
    hasErrorOnly,
    hasInvalidLatency,
    minLatency,
    modelFilter,
    requestFilter,
    selectedTurnId,
    sortMode,
    statusFilter,
    threadFilter,
    toolFilter,
    traceFilter,
    setFallbackOnly,
    setFiltersExpanded,
    setHasErrorOnly,
    setMinLatency,
    setModelFilter,
    setRequestFilter,
    setSelectedTurnId,
    setSortMode,
    setStatusFilter,
    setThreadFilter,
    setToolFilter,
    setTraceFilter,
    actions: {
      applyPreset,
      focusModel: (value: string) => focusFilter(value, setModelFilter),
      focusRequest: (value: string) => focusFilter(value, setRequestFilter),
      focusThread: (value: string) => focusFilter(value, setThreadFilter),
      focusTrace: (value: string) => focusFilter(value, setTraceFilter),
      resetFilters,
    },
  };
}
