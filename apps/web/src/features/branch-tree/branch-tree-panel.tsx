import { useNavigate, useRouterState } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState } from "react";

import { useBranchTree } from "@/features/branch-tree/use-branch-tree";
import {
  ArchivedBranchesSection,
  ArchivedConversationsSection,
} from "@/features/branch-tree/branch-tree-archived-sections";
import { BranchNodeDetailOverlay } from "@/features/branch-tree/branch-tree-detail-overlay";
import { BranchTreeGraphCanvas } from "@/features/branch-tree/branch-tree-graph-canvas";
import { BranchTreeGraphToolbar } from "@/features/branch-tree/branch-tree-graph-toolbar";
import { useBranchTreeArchivedSections } from "@/features/branch-tree/branch-tree-archived-state";
import {
  type BranchGraphNode,
  buildGraph,
  findNode,
} from "@/features/branch-tree/branch-tree-helpers";
import { useBranchDetailOverlayState } from "@/features/branch-tree/use-branch-detail-overlay-state";
import { useBranchTreeActions } from "@/features/branch-tree/use-branch-tree-actions";
import { useBranchTreeViewport } from "@/features/branch-tree/use-branch-tree-viewport";
import { useConversationActions } from "@/features/conversations/use-conversation-actions";
import { useConversations } from "@/features/conversations/use-conversations";

export function BranchTreePanel() {
  const navigate = useNavigate();
  const params = useRouterState({
    select: (state) => {
      const routeParams = (state.matches.at(-1)?.params ?? {}) as Partial<
        Record<"conversationId" | "threadId", string>
      >;
      return {
        conversationId: String(routeParams.conversationId ?? ""),
        threadId: String(routeParams.threadId ?? ""),
      };
    },
  });
  const { data, isLoading, refetch, isFetching } = useBranchTree(params.conversationId);
  const [focusedThreadId, setFocusedThreadId] = useState<string>("");
  const graphShellRef = useRef<HTMLDivElement | null>(null);
  const { data: conversationsData } = useConversations();
  const { activateConversation } = useConversationActions();
  const archivedConversations = useMemo(
    () => (conversationsData?.conversations ?? []).filter((conversation) => conversation.is_archived),
    [conversationsData?.conversations],
  );
  const { archivedConversationsExpanded, setArchivedConversationsExpanded, archivedBranchesExpanded, setArchivedBranchesExpanded } =
    useBranchTreeArchivedSections({
      archivedConversationsCount: archivedConversations.length,
      archivedBranchesCount: data?.archived_branches?.length ?? 0,
    });
  useEffect(() => {
    if (params.threadId) {
      setFocusedThreadId(params.threadId);
    } else if (data?.root?.thread_id) {
      setFocusedThreadId(data.root.thread_id);
    } else {
      setFocusedThreadId("");
    }
  }, [params.threadId, data?.root?.thread_id]);

  const selectedContextThreadId = focusedThreadId || params.threadId || "";
  const selectedNode =
    findNode(data?.root, selectedContextThreadId) ??
    data?.root ??
    data?.archived_branches?.[0] ??
    null;
  const selectedThreadId = selectedContextThreadId || selectedNode?.thread_id || "";
  const graph = useMemo(() => buildGraph(data?.root, selectedThreadId), [data?.root, selectedThreadId]);
  const nodeIndex = useMemo(() => {
    const index = new Map<string, BranchGraphNode>();
    for (const item of graph.nodes) {
      index.set(item.node.thread_id, item);
    }
    return index;
  }, [graph.nodes]);

  const createBranchTargetThreadId = selectedThreadId || params.threadId || "";
  const createBranchTargetNode =
    findNode(data?.root, createBranchTargetThreadId) ??
    data?.archived_branches?.find((item) => item.thread_id === createBranchTargetThreadId) ??
    null;
  const isMergedCreateTarget = createBranchTargetNode?.branch_status === "merged";
  const {
    clearBranchDetailHideTimer,
    detailAnchorRef,
    detailDepth,
    detailNode,
    detailOverlayRef,
    detailStyle,
    detailThreadId,
    scheduleHideBranchDetail,
    showBranchDetail,
    updateBranchDetailPosition,
  } = useBranchDetailOverlayState({ root: data?.root });
  const previewThreadId = detailThreadId || selectedThreadId;
  const previewNode = detailNode ?? selectedNode;

  const { branchZoom, branchZoomRef, centerSelectedNode, treeCanvasRef, updateBranchZoom, viewportNudge } =
    useBranchTreeViewport({
      graphDependency: graph,
      nodeIndex,
      onDetailPositionUpdate: updateBranchDetailPosition,
      selectedThreadId,
    });
  const {
    cancelRenameBranch,
    createBranchFromTarget,
    detailActionViewModel,
    getParentBranchLabel,
    handleArchiveToggle,
    handleOpenMergeReview,
    handlePrepareProposal,
    handleRenameBranch,
    isChineseUi,
    isCreatingBranch,
    isWorking,
    renameBranchDraft,
    renameBranchTarget,
    setRenameBranchDraft,
    startRenameBranch,
  } = useBranchTreeActions({
    detailNode,
    onKeepDetailOpen: clearBranchDetailHideTimer,
    root: data?.root,
    rootThreadId: params.conversationId,
    routeThreadId: params.threadId,
    selectedThreadId,
  });
  const {
    detailCanReviewConclusion,
    detailConclusionActionLabel,
    detailConclusionActionTooltip,
    detailConclusionError,
    detailConclusionPreparing,
    detailHasPreparedConclusion,
    detailNodeStatusTone,
  } = detailActionViewModel;

  async function openThread(threadId: string) {
    await navigate({
      to: "/c/$conversationId/t/$threadId",
      params: {
        conversationId: params.conversationId,
        threadId,
      },
    });
  }

  async function openConversation(rootThreadId: string) {
    await navigate({
      to: "/c/$conversationId/t/$threadId",
      params: {
        conversationId: rootThreadId,
        threadId: rootThreadId,
      },
    });
  }

  return (
    <div className="fa-branch-panel">
      <section className="fa-tree-card">
        <BranchTreeGraphToolbar
          archivedBranchCount={data?.archived_branches?.length ?? 0}
          branchZoom={branchZoom}
          canCreateBranch={Boolean(createBranchTargetThreadId)}
          conversationId={params.conversationId}
          createBranchDisabled={isMergedCreateTarget || isCreatingBranch}
          isChineseUi={isChineseUi}
          isFetching={isFetching}
          isMergedCreateTarget={isMergedCreateTarget}
          onCenterSelectedNode={() => centerSelectedNode(branchZoomRef.current, "smooth")}
          onCreateBranch={() => void createBranchFromTarget(createBranchTargetThreadId, isMergedCreateTarget)}
          onRefresh={() => void refetch()}
          onZoomChange={(nextZoom) => updateBranchZoom(nextZoom, "smooth")}
          root={data?.root}
          selectedThreadId={selectedThreadId}
        />

        <div className="fa-tree-panel-body">
          <div className="fa-tree-summary">
            {isChineseUi
              ? "悬浮查看详情，点击切换上下文。"
              : "Hover for details; click to switch context."}
          </div>
          <div className="fa-tree-legend">
            <span className="fa-tree-legend-item is-role-main">{isChineseUi ? "主线时间轴" : "Main timeline"}</span>
            <span className="fa-tree-legend-item is-role-explore">{isChineseUi ? "探索" : "Explore"}</span>
            <span className="fa-tree-legend-item is-role-deep-dive">{isChineseUi ? "深挖" : "Deep dive"}</span>
            <span className="fa-tree-legend-item is-role-execute">{isChineseUi ? "执行" : "Execute"}</span>
            <span className="fa-tree-legend-item is-role-verify">{isChineseUi ? "验证" : "Verify"}</span>
            <span className="fa-tree-legend-item is-role-writeup">{isChineseUi ? "写作" : "Writeup"}</span>
          </div>

          <div className="fa-tree-canvas-shell">
            <BranchTreeGraphCanvas
              branchZoom={branchZoom}
              detailOverlayRef={detailOverlayRef}
              detailThreadId={detailThreadId}
              graph={graph}
              graphShellRef={graphShellRef}
              isChineseUi={isChineseUi}
              isLoading={isLoading}
              nodeIndex={nodeIndex}
              onOpenThread={(threadId) => void openThread(threadId)}
              onRequestDetail={showBranchDetail}
              onRequestHideDetail={scheduleHideBranchDetail}
              previewNode={previewNode}
              previewThreadId={previewThreadId}
              root={data?.root}
              routeThreadId={params.threadId}
              selectedThreadId={selectedThreadId}
              treeCanvasRef={treeCanvasRef}
              viewportNudge={viewportNudge}
            />
          </div>
        </div>
      </section>

      <ArchivedConversationsSection
        archivedConversations={archivedConversations}
        archivedConversationsExpanded={archivedConversationsExpanded}
        isChineseUi={isChineseUi}
        isWorking={isWorking}
        onOpenConversation={(rootThreadId) => void openConversation(rootThreadId)}
        onRestoreConversation={(rootThreadId) =>
          void activateConversation(rootThreadId)
        }
        setArchivedConversationsExpanded={setArchivedConversationsExpanded}
      />

      <ArchivedBranchesSection
        archivedBranches={data?.archived_branches ?? []}
        archivedBranchesExpanded={archivedBranchesExpanded}
        isChineseUi={isChineseUi}
        isWorking={isWorking}
        onOpenThread={(threadId) => void openThread(threadId)}
        onRestoreBranch={(node) => void handleArchiveToggle(node)}
        setArchivedBranchesExpanded={setArchivedBranchesExpanded}
      />

      <BranchNodeDetailOverlay
        detailAnchorRef={detailAnchorRef}
        detailCanReviewConclusion={detailCanReviewConclusion}
        detailConclusionActionLabel={detailConclusionActionLabel}
        detailConclusionActionTooltip={detailConclusionActionTooltip}
        detailConclusionError={detailConclusionError}
        detailConclusionPreparing={detailConclusionPreparing}
        detailDepth={detailDepth}
        detailHasPreparedConclusion={detailHasPreparedConclusion}
        detailNode={detailNode}
        detailNodeStatusTone={detailNodeStatusTone}
        detailOverlayRef={detailOverlayRef}
        detailStyle={detailStyle}
        getParentBranchLabel={getParentBranchLabel}
        isChineseUi={isChineseUi}
        isWorking={isWorking}
        onArchiveToggle={(node) => void handleArchiveToggle(node)}
        onCancelRename={cancelRenameBranch}
        onKeepOpen={clearBranchDetailHideTimer}
        onPrepareProposal={(node) => void handlePrepareProposal(node)}
        onRenameDraftChange={setRenameBranchDraft}
        onRenameSubmit={(event) => void handleRenameBranch(event)}
        onRequestHide={scheduleHideBranchDetail}
        onStartRename={startRenameBranch}
        onViewMergeReview={(node) => void handleOpenMergeReview(node)}
        renameBranchDraft={renameBranchDraft}
        renameBranchTarget={renameBranchTarget}
        routeThreadId={params.threadId}
      />
    </div>
  );
}
