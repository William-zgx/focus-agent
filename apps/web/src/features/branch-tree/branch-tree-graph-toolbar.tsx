import type { BranchTreeNode } from "@focus-agent/web-sdk";

import {
  BRANCH_ZOOM_STEP,
  countNodes,
  mergedBranchForkDisabledLabel,
} from "@/features/branch-tree/branch-tree-helpers";
import {
  BRANCH_ZOOM_MAX,
  BRANCH_ZOOM_MIN,
  branchZoomLabel,
} from "@/features/branch-tree/use-branch-tree-viewport";
import { tooltipProps } from "@/shared/ui/tooltip";

type BranchTreeGraphToolbarProps = {
  archivedBranchCount: number;
  canCreateBranch: boolean;
  conversationId: string;
  createBranchDisabled: boolean;
  isChineseUi: boolean;
  isFetching: boolean;
  isMergedCreateTarget: boolean;
  onCreateBranch: () => void;
  onRefresh: () => void;
  root: BranchTreeNode | null | undefined;
};

type BranchTreeCanvasToolsProps = {
  branchZoom: number;
  isChineseUi: boolean;
  onCenterSelectedNode: () => void;
  onZoomChange: (value: number) => void;
  selectedThreadId: string;
};

export function BranchTreeGraphToolbar({
  archivedBranchCount,
  canCreateBranch,
  conversationId,
  createBranchDisabled,
  isChineseUi,
  isFetching,
  isMergedCreateTarget,
  onCreateBranch,
  onRefresh,
  root,
}: BranchTreeGraphToolbarProps) {
  const createBranchTooltip = isMergedCreateTarget
    ? mergedBranchForkDisabledLabel(isChineseUi)
    : isChineseUi
      ? "从当前选中节点创建新分支"
      : "Create a branch from the selected node";

  return (
    <div className="fa-tree-toolbar">
      <div className="fa-tree-actions">
        <button
          className="fa-toolbar-primary"
          {...tooltipProps(createBranchTooltip, {
            defaultTooltip: isChineseUi ? "从当前选中节点创建新分支" : "Create a branch from the selected node",
          })}
          disabled={!canCreateBranch || createBranchDisabled}
          onClick={onCreateBranch}
          type="button"
        >
          {isChineseUi ? "新建分支" : "New branch"}
        </button>
        <button
          className="fa-toolbar-secondary"
          {...tooltipProps(isChineseUi ? "刷新分支树" : "Refresh branches")}
          disabled={!conversationId || isFetching}
          onClick={onRefresh}
          type="button"
        >
          {isChineseUi ? "刷新分支树" : "Refresh branches"}
        </button>
        <span className="fa-tree-count-summary">
          {isChineseUi ? "进行中" : "In progress"} {countNodes(root)} ·{" "}
          {isChineseUi ? "已归档" : "Archived"} {archivedBranchCount}
        </span>
      </div>
    </div>
  );
}

export function BranchTreeCanvasTools({
  branchZoom,
  isChineseUi,
  onCenterSelectedNode,
  onZoomChange,
  selectedThreadId,
}: BranchTreeCanvasToolsProps) {
  return (
    <div className="fa-tree-canvas-tools">
      <div
        className="fa-tree-viewport-tools"
        role="group"
        aria-label={isChineseUi ? "分支树缩放与定位" : "Branch tree zoom and locate controls"}
      >
        <button
          className="fa-tree-zoom-button"
          {...tooltipProps(isChineseUi ? "缩小分支树" : "Zoom out branch tree")}
          disabled={branchZoom <= BRANCH_ZOOM_MIN}
          onClick={() => onZoomChange(branchZoom - BRANCH_ZOOM_STEP)}
          type="button"
        >
          -
        </button>
        <button
          className="fa-tree-zoom-level"
          {...tooltipProps(isChineseUi ? "重置缩放到 100%" : "Reset zoom to 100%")}
          disabled={Math.abs(branchZoom - 1) < 0.001}
          onClick={() => onZoomChange(1)}
          type="button"
        >
          {branchZoomLabel(branchZoom)}
        </button>
        <button
          className="fa-tree-zoom-button"
          {...tooltipProps(isChineseUi ? "放大分支树" : "Zoom in branch tree")}
          disabled={branchZoom >= BRANCH_ZOOM_MAX}
          onClick={() => onZoomChange(branchZoom + BRANCH_ZOOM_STEP)}
          type="button"
        >
          +
        </button>
        <button
          className="fa-tree-locate-button"
          {...tooltipProps(isChineseUi ? "定位到当前选中节点" : "Center the selected node")}
          disabled={!selectedThreadId}
          onClick={onCenterSelectedNode}
          type="button"
        >
          {isChineseUi ? "定位" : "Locate"}
        </button>
      </div>
    </div>
  );
}
