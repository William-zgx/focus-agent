import type { BranchTreeNode } from "@focus-agent/web-sdk";
import type { CSSProperties, FormEvent, RefObject } from "react";
import { createPortal } from "react-dom";

import {
  branchStatusLabel,
  branchTokenUsageLabel,
  roleColor,
  roleLabel,
} from "@/features/branch-tree/branch-tree-helpers";
import { tooltipProps } from "@/shared/ui/tooltip";

type BranchTreeNodeDetailOverlayProps = {
  detailAnchorRef: RefObject<HTMLElement | null>;
  detailCanReviewConclusion: boolean;
  detailConclusionActionLabel: string;
  detailConclusionActionTooltip: string;
  detailConclusionError: string | null;
  detailConclusionPreparing: boolean;
  detailDepth: number;
  detailHasPreparedConclusion: boolean;
  detailNode: BranchTreeNode | null;
  detailNodeStatusTone: string;
  detailOverlayRef: RefObject<HTMLDivElement | null>;
  detailStyle: CSSProperties;
  getParentBranchLabel: (node: BranchTreeNode) => string;
  isChineseUi: boolean;
  isWorking: boolean;
  onArchiveToggle: (node: BranchTreeNode) => void;
  onCancelRename: () => void;
  onKeepOpen: () => void;
  onPrepareProposal: (node: BranchTreeNode) => void;
  onRenameDraftChange: (value: string) => void;
  onRenameSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onRequestHide: () => void;
  onStartRename: (node: BranchTreeNode) => void;
  onViewMergeReview: (node: BranchTreeNode) => void;
  renameBranchDraft: string;
  renameBranchTarget: BranchTreeNode | null;
  routeThreadId: string;
};

function threadLabel(isChineseUi: boolean) {
  return isChineseUi ? "线程" : "Thread";
}

function parentLabel(isChineseUi: boolean) {
  return isChineseUi ? "父分支" : "Parent";
}

function roleLabelText(isChineseUi: boolean) {
  return isChineseUi ? "角色" : "Role";
}

function statusLabel(isChineseUi: boolean) {
  return isChineseUi ? "状态" : "Status";
}

function depthLabel(isChineseUi: boolean) {
  return isChineseUi ? "层级" : "Depth";
}

function tokenLabel(isChineseUi: boolean) {
  return isChineseUi ? "分支累计" : "Branch total";
}

export function BranchNodeDetailOverlay({
  detailAnchorRef,
  detailCanReviewConclusion,
  detailConclusionActionLabel,
  detailConclusionActionTooltip,
  detailConclusionError,
  detailConclusionPreparing,
  detailDepth,
  detailHasPreparedConclusion,
  detailNode,
  detailNodeStatusTone,
  detailOverlayRef,
  detailStyle,
  getParentBranchLabel,
  isChineseUi,
  isWorking,
  onArchiveToggle,
  onCancelRename,
  onKeepOpen,
  onPrepareProposal,
  onRenameDraftChange,
  onRenameSubmit,
  onRequestHide,
  onStartRename,
  onViewMergeReview,
  renameBranchDraft,
  renameBranchTarget,
  routeThreadId,
}: BranchTreeNodeDetailOverlayProps) {
  if (!detailNode || typeof document === "undefined") return null;

  const parentBranchLabel = getParentBranchLabel(detailNode);
  const rowForParent = parentBranchLabel
    ? parentBranchLabel
    : isChineseUi
      ? "主线"
      : "Main";
  const metaRows = [
    [threadLabel(isChineseUi), detailNode.thread_id],
    [parentLabel(isChineseUi), rowForParent],
    [roleLabelText(isChineseUi), roleLabel(detailNode.branch_role, isChineseUi)],
    [statusLabel(isChineseUi), branchStatusLabel(detailNode.branch_status, isChineseUi)],
    [depthLabel(isChineseUi), String(detailDepth)],
    [tokenLabel(isChineseUi), branchTokenUsageLabel(detailNode)],
  ].map(([label, value]) => (
    <div key={`${label}-${value}`} className="fa-branch-node-meta-row">
      <span className="fa-branch-node-meta-label">{label}</span>
      <span className="fa-branch-node-meta-value">{value}</span>
    </div>
  ));

  return createPortal(
    <div
      role="dialog"
      tabIndex={-1}
      ref={detailOverlayRef}
      className="fa-branch-detail-overlay is-visible"
      onMouseEnter={onKeepOpen}
      onMouseLeave={(event) => {
        if (event.relatedTarget instanceof Node && detailAnchorRef.current?.contains(event.relatedTarget)) {
          return;
        }
        onRequestHide();
      }}
      style={detailStyle}
    >
      <div
        className="fa-branch-node-detail"
        style={
          {
            "--fa-branch-role-color": roleColor(detailNode.branch_role),
          } as CSSProperties
        }
      >
        <div className="fa-branch-node-detail-head">
          <div className="fa-branch-node-title">{detailNode.branch_name}</div>
          <div className="fa-branch-node-subtitle">
            {threadLabel(isChineseUi)} · {detailNode.thread_id}
          </div>
        </div>

        <div className="fa-branch-node-badges">
          {!detailNode.branch_id ? (
            <span className="fa-branch-node-badge current">{isChineseUi ? "主线" : "Root"}</span>
          ) : null}
          {detailNode.thread_id === routeThreadId ? (
            <span className="fa-branch-node-badge current">{isChineseUi ? "当前" : "Current"}</span>
          ) : null}
          <span className="fa-branch-node-badge">{roleLabel(detailNode.branch_role, isChineseUi)}</span>
          <span className={`fa-branch-node-badge ${detailNodeStatusTone}`.trim()}>
            {branchStatusLabel(detailNode.branch_status, isChineseUi)}
          </span>
          <span className="fa-branch-node-badge">
            {isChineseUi ? "深度" : "Depth"} {detailDepth}
          </span>
          <span className="fa-branch-node-badge">
            {branchTokenUsageLabel(detailNode)}
          </span>
        </div>

        <div className="fa-branch-node-meta">{metaRows}</div>

        {renameBranchTarget?.thread_id === detailNode.thread_id ? (
          <form className="fa-inline-rename-form is-branch" onSubmit={onRenameSubmit}>
            <label className="sr-only" htmlFor={`branch-rename-input-${detailNode.thread_id}`}>
              {isChineseUi ? "重命名分支" : "Rename branch"}
            </label>
            <input
              id={`branch-rename-input-${detailNode.thread_id}`}
              className="fa-inline-rename-input"
              autoFocus
              disabled={isWorking}
              value={renameBranchDraft}
              onChange={(event) => onRenameDraftChange(event.target.value)}
            />
            <button
              className="fa-branch-inline-action is-primary"
              disabled={isWorking || !renameBranchDraft.trim()}
              type="submit"
            >
              {isChineseUi ? "保存" : "Save"}
            </button>
            <button className="fa-branch-inline-action" disabled={isWorking} onClick={onCancelRename} type="button">
              {isChineseUi ? "取消" : "Cancel"}
            </button>
          </form>
        ) : null}

        <div className="fa-branch-node-actions">
          {detailNode.branch_id && renameBranchTarget?.thread_id !== detailNode.thread_id ? (
            <button
              className="fa-branch-inline-action"
              {...tooltipProps(isChineseUi ? "重命名这个分支" : "Rename this branch")}
              disabled={isWorking}
              onClick={() => onStartRename(detailNode)}
              type="button"
            >
              {isChineseUi ? "重命名" : "Rename"}
            </button>
          ) : null}
          {detailCanReviewConclusion ? (
            <button
              className={`fa-branch-inline-action ${detailHasPreparedConclusion ? "is-primary" : ""}`.trim()}
              {...tooltipProps(detailConclusionActionTooltip)}
              disabled={isWorking || detailConclusionPreparing}
              onClick={() =>
                detailHasPreparedConclusion ? onViewMergeReview(detailNode) : onPrepareProposal(detailNode)
              }
              type="button"
            >
              {detailConclusionActionLabel}
            </button>
          ) : null}
          {detailCanReviewConclusion && detailHasPreparedConclusion ? (
            <button
              className="fa-branch-inline-action"
              {...tooltipProps(isChineseUi ? "重新生成这个分支的结论" : "Regenerate conclusion for this branch")}
              disabled={isWorking || detailConclusionPreparing}
              onClick={() => onPrepareProposal(detailNode)}
              type="button"
            >
              {isChineseUi ? "重新生成结论" : "Regenerate conclusion"}
            </button>
          ) : null}
          {detailNode.branch_id ? (
            <button
              className="fa-branch-inline-action warn"
              {...tooltipProps(
                detailNode.is_archived
                  ? isChineseUi
                    ? "重新激活这个分支"
                    : "Activate this branch"
                  : isChineseUi
                    ? "归档这个分支"
                    : "Archive this branch",
              )}
              disabled={isWorking}
              onClick={() => onArchiveToggle(detailNode)}
              type="button"
            >
              {detailNode.is_archived ? (isChineseUi ? "激活" : "Activate") : isChineseUi ? "归档" : "Archive"}
            </button>
          ) : null}
          {detailConclusionError ? <div className="fa-branch-node-error">{detailConclusionError}</div> : null}
        </div>
      </div>
    </div>,
    document.body,
  );
}
