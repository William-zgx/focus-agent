import { FocusAgentRequestError } from "@focus-agent/web-sdk";
import { useRouterState } from "@tanstack/react-router";
import { useRef } from "react";

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
import { useObservabilityOverview } from "@/features/trajectory-observability/use-observability-overview";
import { useTrajectoryDetail } from "@/features/trajectory-observability/use-trajectory-detail";
import { useTrajectoryList } from "@/features/trajectory-observability/use-trajectory-list";
import { useTrajectoryBatchSelection } from "@/pages/observability/use-trajectory-batch-selection";
import { useTrajectoryPageActions } from "@/pages/observability/use-trajectory-page-actions";
import { useTrajectoryPageModel } from "@/pages/observability/use-trajectory-page-model";
import { useTrajectoryPageSelectionEffects } from "@/pages/observability/use-trajectory-page-selection-effects";
import { useTrajectoryWorkbenchState } from "@/pages/observability/use-trajectory-workbench-state";
import { useTrajectoryUrlSync } from "@/pages/observability/use-trajectory-url-sync";

export function TrajectoryPage() {
  const { isChineseUi } = useShellUi();
  const { isOverviewRoute, routerSearch } = useRouterState({
    select: (state) => ({
      isOverviewRoute: state.location.pathname.endsWith(
        "/observability/overview",
      ),
      routerSearch: state.location.searchStr,
    }),
  });
  const locale = isChineseUi ? "zh-CN" : "en-US";
  const detailPanelRef = useRef<HTMLElement | null>(null);
  const {
    deferredFilters,
    fallbackOnly,
    filterChips,
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
      focusModel,
      focusRequest,
      focusThread,
      focusTrace,
      resetFilters,
    },
  } = useTrajectoryWorkbenchState(routerSearch);
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
  const { data: detailData, isLoading: isDetailLoading } =
    useTrajectoryDetail(selectedTurnId);
  const selected = detailData?.item ?? null;
  const {
    activeTurnLabel,
    commandSnippet,
    correlationCoverage,
    correlationSignals,
    evidenceMode,
    hottestTools,
    listErrorMessage,
    matchCount,
    orderedItems,
    overviewModelItems,
    overviewSceneItems,
    overviewSummaryMetrics,
    overviewToolItems,
    resultSummary,
    reviewSummary,
    runtimeLabel,
    selectedModel,
    selectedRequestSignal,
    selectedSignals,
    selectedThreadSignal,
    selectedTraceSignal,
    statsErrorMessage,
    statsOverview,
    supplementalContext,
    trajectoryRuntimeMessage,
  } = useTrajectoryPageModel({
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
  });
  const {
    clearBatchSelection,
    selectVisibleBatch,
    selectVisibleFailuresBatch,
    selectedBatchIdSet,
    selectedBatchItems,
    selectedBatchTurnIds,
    toggleBatchSelection,
  } = useTrajectoryBatchSelection(orderedItems);

  useTrajectoryPageSelectionEffects({
    detailPanelRef,
    isListLoading,
    listError,
    orderedItems,
    selectedTurnId,
    setSelectedTurnId,
  });

  useTrajectoryUrlSync({
    fallbackOnly,
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
  });

  const {
    actionRailSections,
    copyText,
    downloadSelectedRecord,
    handleCopyCommand,
    handleCopyLink,
    pivotActions,
  } = useTrajectoryPageActions({
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
  });

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
