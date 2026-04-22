import type { BranchTreeNode } from "@focus-agent/web-sdk";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { type CSSProperties, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { useShellUi } from "@/app/shell/shell-ui-context";
import { useBranchActions } from "@/features/branch-tree/use-branch-actions";
import { useBranchTree } from "@/features/branch-tree/use-branch-tree";
import { useConversationActions } from "@/features/conversations/use-conversation-actions";
import { useConversations } from "@/features/conversations/use-conversations";
import { tooltipProps } from "@/shared/ui/tooltip";

type GraphNode = {
  node: BranchTreeNode;
  x: number;
  y: number;
};

type GraphEdge = {
  from: string;
  to: string;
  color: string;
};

const NODE_X_START = 42;
const NODE_X_GAP = 108;
const NODE_Y_START = 48;
const NODE_Y_GAP = 76;
const GRAPH_NODE_SIZE = 24;
const GRAPH_NODE_RADIUS = GRAPH_NODE_SIZE / 2;
const GRAPH_EDGE_NODE_CLEARANCE = GRAPH_NODE_RADIUS + 1;
const GRAPH_FOCUS_TARGET_Y = 184;
const GRAPH_TOP_PADDING = 34;
const BRANCH_DETAIL_WIDTH = 228;
const BRANCH_DETAIL_HEIGHT_ESTIMATE = 260;
const BRANCH_DETAIL_HIDE_DELAY_MS = 120;
const BRANCH_ZOOM_MIN = 0.5;
const BRANCH_ZOOM_MAX = 1.8;
const BRANCH_ZOOM_STEP = 0.1;
const BRANCH_ZOOM_WHEEL_SENSITIVITY = 0.0015;

type WebKitGestureEvent = Event & {
  scale?: number;
};

function roleLabel(role: BranchTreeNode["branch_role"], isChineseUi = false) {
  switch (role) {
    case "deep_dive":
      return isChineseUi ? "深挖" : "Deep dive";
    case "execute":
      return isChineseUi ? "执行" : "Execute";
    case "explore_alternatives":
      return isChineseUi ? "探索" : "Explore";
    case "verify":
      return isChineseUi ? "验证" : "Verify";
    case "writeup":
      return isChineseUi ? "写作" : "Writeup";
    default:
      return isChineseUi ? "主线" : "Main";
  }
}

function roleColor(role: BranchTreeNode["branch_role"]) {
  switch (role) {
    case "main":
      return "#6BA9FF";
    case "explore_alternatives":
      return "#5EC2FF";
    case "deep_dive":
      return "#A78BFA";
    case "execute":
      return "#FB7185";
    case "verify":
      return "#F59E0B";
    case "writeup":
      return "#34D399";
    default:
      return "#5EC2FF";
  }
}

function statusTone(status: BranchTreeNode["branch_status"]) {
  switch (status) {
    case "preparing_merge_review":
      return "is-pending";
    case "awaiting_merge_review":
      return "is-ready";
    case "paused":
      return "is-paused";
    case "merged":
      return "is-merged";
    case "discarded":
    case "closed":
      return "is-merged";
    default:
      return "";
  }
}

function statusAccentTone(status: BranchTreeNode["branch_status"]) {
  switch (status) {
    case "awaiting_merge_review":
      return "is-success";
    case "preparing_merge_review":
    case "paused":
      return "is-warn";
    case "merged":
      return "is-danger";
    default:
      return "";
  }
}

function findNode(root: BranchTreeNode | undefined, threadId: string | undefined): BranchTreeNode | undefined {
  if (!root || !threadId) return undefined;
  if (root.thread_id === threadId) return root;
  for (const child of root.children) {
    const hit = findNode(child, threadId);
    if (hit) return hit;
  }
  return undefined;
}

function countNodes(node?: BranchTreeNode | null): number {
  if (!node) return 0;
  return 1 + node.children.reduce((sum, child) => sum + countNodes(child), 0);
}

function branchStatusLabel(status: BranchTreeNode["branch_status"], isChineseUi = false) {
  if (status === "awaiting_merge_review") return isChineseUi ? "等待评审" : "Awaiting review";
  if (status === "preparing_merge_review") return isChineseUi ? "准备评审" : "Preparing review";
  if (isChineseUi) {
    const labels: Record<string, string> = {
      active: "进行中",
      paused: "已暂停",
      merged: "已合并",
      discarded: "已丢弃",
      closed: "已关闭",
    };
    return labels[status] || status;
  }
  return status.replaceAll("_", " ");
}

function shouldShowArchivedSecondaryLine(primary: string | undefined, secondary: string | undefined) {
  const normalizedPrimary = String(primary ?? "").trim();
  const normalizedSecondary = String(secondary ?? "").trim();
  return Boolean(normalizedSecondary) && normalizedPrimary !== normalizedSecondary;
}

function mergedBranchForkDisabledLabel(isChineseUi = false) {
  return isChineseUi ? "已合并分支不能新建分支" : "Merged branches cannot create new branches";
}

function threadMetaLabel(isChineseUi: boolean) {
  return isChineseUi ? "线程" : "Thread";
}

function parentMetaLabel(isChineseUi: boolean) {
  return isChineseUi ? "父分支" : "Parent";
}

function roleMetaLabel(isChineseUi: boolean) {
  return isChineseUi ? "角色" : "Role";
}

function statusMetaLabel(isChineseUi: boolean) {
  return isChineseUi ? "状态" : "Status";
}

function depthMetaLabel(isChineseUi: boolean) {
  return isChineseUi ? "层级" : "Depth";
}

function clampBranchZoom(value: number) {
  return Math.min(BRANCH_ZOOM_MAX, Math.max(BRANCH_ZOOM_MIN, Number(value.toFixed(2))));
}

function branchZoomLabel(value: number) {
  return `${Math.round(value * 100)}%`;
}

function buildGraph(root?: BranchTreeNode | null, focusThreadId?: string): {
  nodes: GraphNode[];
  edges: GraphEdge[];
  width: number;
  height: number;
} {
  if (!root) {
    return { nodes: [], edges: [], width: 220, height: 220 };
  }

  const nodes: GraphNode[] = [];
  const edges: GraphEdge[] = [];
  let cursorY = NODE_Y_START;
  let maxDepth = 0;

  function walk(node: BranchTreeNode, depth: number, parent?: BranchTreeNode): number {
    maxDepth = Math.max(maxDepth, depth);
    const childCenters: number[] = [];
    for (const child of node.children) {
      childCenters.push(walk(child, depth + 1, node));
    }

    const y =
      childCenters.length > 0
        ? (childCenters[0] + childCenters[childCenters.length - 1]) / 2
        : (() => {
            const next = cursorY;
            cursorY += NODE_Y_GAP;
            return next;
          })();
    const x = NODE_X_START + depth * NODE_X_GAP;

    nodes.push({ node, x, y });
    if (parent) {
      edges.push({
        from: parent.thread_id,
        to: node.thread_id,
        color: roleColor(node.branch_role),
      });
    }
    return y;
  }

  walk(root, 0);

  const maxY = Math.max(...nodes.map((item) => item.y), NODE_Y_START);
  const minY = Math.min(...nodes.map((item) => item.y), NODE_Y_START);
  const focusNode = focusThreadId
    ? nodes.find((item) => item.node.thread_id === focusThreadId)
    : undefined;
  const requestedShift = focusNode ? GRAPH_FOCUS_TARGET_Y - focusNode.y : 0;
  const minShift = GRAPH_TOP_PADDING - minY;
  const verticalShift = Math.max(minShift, requestedShift);
  const shiftedNodes =
    verticalShift === 0
      ? nodes
      : nodes.map((item) => ({
          ...item,
          y: item.y + verticalShift,
        }));
  const shiftedMaxY = Math.max(...shiftedNodes.map((item) => item.y), NODE_Y_START);
  const width = Math.max(240, NODE_X_START * 2 + maxDepth * NODE_X_GAP + 56);
  const height = Math.max(220, shiftedMaxY + NODE_Y_START);

  return { nodes: shiftedNodes, edges, width, height };
}

function edgePath(from: GraphNode, to: GraphNode) {
  const startX = from.x;
  const startY = from.y + GRAPH_EDGE_NODE_CLEARANCE;
  const endX = to.x;
  const endY = to.y - GRAPH_EDGE_NODE_CLEARANCE;
  const offsetY = Math.max(24, Math.min(48, (endY - startY) * 0.35));
  const offsetX = Math.max(28, Math.abs(endX - startX) * 0.4);
  return `M ${startX} ${startY} C ${startX + offsetX} ${startY + offsetY}, ${endX - offsetX} ${endY - offsetY}, ${endX} ${endY}`;
}

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
  const [isWorking, setIsWorking] = useState(false);
  const [detailThreadId, setDetailThreadId] = useState<string>("");
  const [detailDepth, setDetailDepth] = useState(0);
  const [detailStyle, setDetailStyle] = useState<CSSProperties>({});
  const [branchZoom, setBranchZoom] = useState(1);
  const [viewportNudge, setViewportNudge] = useState({
    x: 0,
    y: 0,
  });
  const detailAnchorRef = useRef<HTMLElement | null>(null);
  const detailOverlayRef = useRef<HTMLDivElement | null>(null);
  const detailHideTimerRef = useRef<number | null>(null);
  const treeCanvasRef = useRef<HTMLDivElement | null>(null);
  const graphShellRef = useRef<HTMLDivElement | null>(null);
  const branchZoomRef = useRef(1);
  const gestureStartZoomRef = useRef(1);
  const pendingZoomCenterBehaviorRef = useRef<ScrollBehavior | null>(null);
  const canvasAutoCenteringRef = useRef(false);
  const {
    createBranch,
    isCreatingBranch,
    isChineseUi,
    setShellStatus,
    markMergeProposalPreparing,
    markMergeProposalReady,
    markMergeProposalFailed,
    isMergeProposalPreparing,
    getMergeProposalError,
  } = useShellUi();
  const { data: conversationsData } = useConversations();
  const { activateConversation } = useConversationActions();
  const archivedConversations = useMemo(
    () => (conversationsData?.conversations ?? []).filter((conversation) => conversation.is_archived),
    [conversationsData?.conversations],
  );
  const [archivedConversationsExpanded, setArchivedConversationsExpanded] = useState(
    archivedConversations.length > 0,
  );
  const [archivedBranchesExpanded, setArchivedBranchesExpanded] = useState(
    (data?.archived_branches?.length ?? 0) > 0,
  );

  branchZoomRef.current = branchZoom;

  useEffect(() => {
    if (params.threadId) {
      setFocusedThreadId(params.threadId);
    } else if (data?.root?.thread_id) {
      setFocusedThreadId(data.root.thread_id);
    } else {
      setFocusedThreadId("");
    }
  }, [params.threadId, data?.root?.thread_id]);

  useEffect(() => {
    if (!archivedConversations.length) {
      setArchivedConversationsExpanded(false);
      return;
    }
    setArchivedConversationsExpanded((current) => current || archivedConversations.length > 0);
  }, [archivedConversations.length]);

  useEffect(() => {
    if (!(data?.archived_branches?.length ?? 0)) {
      setArchivedBranchesExpanded(false);
      return;
    }
    setArchivedBranchesExpanded((current) => current || (data?.archived_branches?.length ?? 0) > 0);
  }, [data?.archived_branches?.length]);

  const selectedContextThreadId = focusedThreadId || params.threadId || "";
  const selectedNode =
    findNode(data?.root, selectedContextThreadId) ??
    data?.root ??
    data?.archived_branches?.[0] ??
    null;
  const selectedThreadId = selectedContextThreadId || selectedNode?.thread_id || "";
  const graph = useMemo(() => buildGraph(data?.root, selectedThreadId), [data?.root, selectedThreadId]);
  const nodeIndex = useMemo(() => {
    const index = new Map<string, GraphNode>();
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
  const createBranchTooltip = isMergedCreateTarget
    ? mergedBranchForkDisabledLabel(isChineseUi)
    : isChineseUi
      ? "从当前选中节点创建新分支"
      : "Create a branch from the selected node";
  const detailNode = findNode(data?.root, detailThreadId) ?? null;
  const previewThreadId = detailThreadId || selectedThreadId;
  const previewNode = detailNode ?? selectedNode;
  const detailNodeStatusTone = detailNode ? statusAccentTone(detailNode.branch_status) : "";
  const detailConclusionPreparing = detailNode
    ? detailNode.branch_status === "preparing_merge_review" ||
      isMergeProposalPreparing(detailNode.thread_id)
    : false;
  const detailHasPreparedConclusion = detailNode?.branch_status === "awaiting_merge_review";
  const detailCanReviewConclusion = Boolean(
    detailNode?.branch_id &&
      !detailNode.is_archived &&
      !["merged", "discarded", "closed"].includes(detailNode.branch_status),
  );
  const detailConclusionError = detailNode ? getMergeProposalError(detailNode.thread_id) : null;
  const detailConclusionActionLabel = detailConclusionPreparing
    ? isChineseUi
      ? "生成结论中"
      : "Generating"
    : detailHasPreparedConclusion
      ? isChineseUi
        ? "合并结论"
        : "Merge conclusion"
      : detailConclusionError
        ? isChineseUi
          ? "重新生成结论"
          : "Regenerate conclusion"
      : isChineseUi
        ? "生成结论"
        : "Generate conclusion";
  const detailConclusionActionTooltip = detailConclusionPreparing
    ? isChineseUi
      ? "分支结论正在生成"
      : "Conclusion is being generated"
    : detailHasPreparedConclusion
      ? isChineseUi
        ? "打开合并结论弹窗"
        : "Open merge conclusion dialog"
      : detailConclusionError
        ? isChineseUi
          ? "上次生成失败，重新生成分支结论"
          : "The last generation failed. Regenerate the branch conclusion."
      : isChineseUi
        ? "异步生成分支结论"
        : "Generate conclusion asynchronously";
  const detailOverlay =
    detailNode && typeof document !== "undefined"
      ? createPortal(
          <div
            ref={detailOverlayRef}
            className="fa-branch-detail-overlay is-visible"
            onMouseEnter={() => clearBranchDetailHideTimer()}
            onMouseLeave={(event) => {
              if (
                event.relatedTarget instanceof Node &&
                detailAnchorRef.current?.contains(event.relatedTarget)
              ) {
                return;
              }
              scheduleHideBranchDetail();
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
                  {threadMetaLabel(isChineseUi)} · {detailNode.thread_id}
                </div>
              </div>

              <div className="fa-branch-node-badges">
                {!detailNode.branch_id ? (
                  <span className="fa-branch-node-badge current">
                    {isChineseUi ? "主线" : "Root"}
                  </span>
                ) : null}
                {detailNode.thread_id === params.threadId ? (
                  <span className="fa-branch-node-badge current">
                    {isChineseUi ? "当前" : "Current"}
                  </span>
                ) : null}
                <span className="fa-branch-node-badge">
                  {roleLabel(detailNode.branch_role, isChineseUi)}
                </span>
                <span className={`fa-branch-node-badge ${detailNodeStatusTone}`.trim()}>
                  {branchStatusLabel(detailNode.branch_status, isChineseUi)}
                </span>
                <span className="fa-branch-node-badge">
                  {isChineseUi ? "深度" : "Depth"} {detailDepth}
                </span>
              </div>

              <div className="fa-branch-node-meta">
                {[
                  [threadMetaLabel(isChineseUi), detailNode.thread_id],
                  [parentMetaLabel(isChineseUi), parentBranchLabel(detailNode)],
                  [roleMetaLabel(isChineseUi), roleLabel(detailNode.branch_role, isChineseUi)],
                  [
                    statusMetaLabel(isChineseUi),
                    branchStatusLabel(detailNode.branch_status, isChineseUi),
                  ],
                  [depthMetaLabel(isChineseUi), String(detailDepth)],
                ].map(([label, value]) => (
                  <div key={label} className="fa-branch-node-meta-row">
                    <span className="fa-branch-node-meta-label">{label}</span>
                    <span className="fa-branch-node-meta-value">{value}</span>
                  </div>
                ))}
              </div>

              <div className="fa-branch-node-actions">
                {detailNode.branch_id ? (
                  <button
                    className="fa-branch-inline-action"
                    {...tooltipProps(isChineseUi ? "重命名这个分支" : "Rename this branch")}
                    disabled={isWorking}
                    onClick={() => void handleRenameBranch(detailNode)}
                    type="button"
                  >
                    {isChineseUi ? "重命名" : "Rename"}
                  </button>
                ) : null}
                {detailCanReviewConclusion ? (
                  <button
                    className={`fa-branch-inline-action ${
                      detailHasPreparedConclusion ? "is-primary" : ""
                    }`.trim()}
                    {...tooltipProps(detailConclusionActionTooltip)}
                    disabled={isWorking || detailConclusionPreparing}
                    onClick={() =>
                      void (detailHasPreparedConclusion
                        ? handleOpenMergeReview(detailNode)
                        : handlePrepareProposal(detailNode))
                    }
                    type="button"
                  >
                    {detailConclusionActionLabel}
                  </button>
                ) : null}
                {detailCanReviewConclusion && detailHasPreparedConclusion ? (
                  <button
                    className="fa-branch-inline-action"
                    {...tooltipProps(
                      isChineseUi ? "重新生成这个分支的结论" : "Regenerate conclusion for this branch",
                    )}
                    disabled={isWorking || detailConclusionPreparing}
                    onClick={() => void handlePrepareProposal(detailNode)}
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
                          : "Archive this branch"
                    )}
                    disabled={isWorking}
                    onClick={() => void handleArchiveToggle(detailNode)}
                    type="button"
                  >
                    {detailNode.is_archived
                      ? isChineseUi
                        ? "激活"
                        : "Activate"
                      : isChineseUi
                        ? "归档"
                        : "Archive"}
                  </button>
                ) : null}
                {detailConclusionError ? (
                  <div className="fa-branch-node-error">{detailConclusionError}</div>
                ) : null}
              </div>
            </div>
          </div>,
          document.body,
        )
      : null;
  const { forkBranch, archiveBranch, activateBranch, prepareMergeProposal, renameBranch } = useBranchActions({
    rootThreadId: params.conversationId,
    threadId: selectedThreadId || params.threadId,
  });

  function clearBranchDetailHideTimer() {
    if (detailHideTimerRef.current == null) return;
    window.clearTimeout(detailHideTimerRef.current);
    detailHideTimerRef.current = null;
  }

  function hideBranchDetail() {
    clearBranchDetailHideTimer();
    detailAnchorRef.current = null;
    setDetailThreadId("");
    setDetailStyle({});
  }

  function scheduleHideBranchDetail() {
    clearBranchDetailHideTimer();
    detailHideTimerRef.current = window.setTimeout(() => {
      detailHideTimerRef.current = null;
      hideBranchDetail();
    }, BRANCH_DETAIL_HIDE_DELAY_MS);
  }

  function getBranchDetailStyle(anchor: HTMLElement): CSSProperties {
    const rect = anchor.getBoundingClientRect();
    const scrollFrame =
      anchor.closest<HTMLElement>(".fa-sidebar-scroll") ??
      anchor.closest<HTMLElement>(".fa-sidebar-panel");
    const overlayWidth = Math.min(BRANCH_DETAIL_WIDTH, window.innerWidth - 32);
    const overlayHeight =
      detailOverlayRef.current?.getBoundingClientRect().height ||
      BRANCH_DETAIL_HEIGHT_ESTIMATE;
    const margin = 16;
    const gap = 16;
    const scrollbarGutter = scrollFrame ? 18 : 0;
    const horizontalMin = scrollFrame
      ? Math.max(margin, scrollFrame.getBoundingClientRect().left + margin)
      : margin;
    const horizontalMax = scrollFrame
      ? Math.min(
          window.innerWidth - margin,
          scrollFrame.getBoundingClientRect().right - margin - scrollbarGutter,
        )
      : window.innerWidth - margin;
    const preferredRight = rect.right + gap;
    const preferredLeft = rect.left - gap - overlayWidth;
    let left = preferredRight;

    if (preferredRight + overlayWidth > horizontalMax && preferredLeft >= horizontalMin) {
      left = preferredLeft;
    }

    left = Math.min(Math.max(horizontalMin, left), Math.max(horizontalMin, horizontalMax - overlayWidth));
    const placedBesideAnchor =
      (left >= preferredRight - 1 && left <= preferredRight + 1) ||
      (left >= preferredLeft - 1 && left <= preferredLeft + 1);
    const centeredTop = rect.top + rect.height / 2 - overlayHeight / 2;
    const belowTop = rect.bottom + gap;
    const aboveTop = rect.top - gap - overlayHeight;
    let top = placedBesideAnchor
      ? centeredTop
      : belowTop + overlayHeight <= window.innerHeight - margin || aboveTop < margin
        ? belowTop
        : aboveTop;

    top = Math.min(Math.max(margin, top), Math.max(margin, window.innerHeight - overlayHeight - margin));

    return {
      left: `${left}px`,
      top: `${top}px`,
    };
  }

  function updateBranchDetailPosition() {
    const anchor = detailAnchorRef.current;
    if (!anchor) return;
    setDetailStyle(getBranchDetailStyle(anchor));
  }

  function centerSelectedNode(zoom = branchZoomRef.current, behavior: ScrollBehavior = "smooth") {
    const canvas = treeCanvasRef.current;
    const node = nodeIndex.get(selectedThreadId);
    if (!canvas || !node) return;

    const canvasInsets = readCanvasInsets();
    const nodeCenterX = canvasInsets.x + node.x * zoom;
    const nodeCenterY = canvasInsets.y + node.y * zoom;
    const maxScrollLeft = Math.max(0, canvas.scrollWidth - canvas.clientWidth);
    const maxScrollTop = Math.max(0, canvas.scrollHeight - canvas.clientHeight);
    const desiredLeft = nodeCenterX - canvas.clientWidth / 2;
    const desiredTop = nodeCenterY - canvas.clientHeight / 2;
    const left = Math.min(Math.max(0, desiredLeft), maxScrollLeft);
    const top = Math.min(Math.max(0, desiredTop), maxScrollTop);

    canvasAutoCenteringRef.current = true;
    setViewportNudge({
      x: Math.round(left - desiredLeft),
      y: Math.round(top - desiredTop),
    });
    canvas.scrollTo({ left, top, behavior });
    window.requestAnimationFrame(() => {
      canvasAutoCenteringRef.current = false;
    });
  }

  function readCanvasInsets() {
    const canvas = treeCanvasRef.current;
    if (!canvas || typeof window === "undefined") return { x: 0, y: 0 };
    const styles = window.getComputedStyle(canvas);
    return {
      x: Number.parseFloat(styles.paddingLeft) || 0,
      y: Number.parseFloat(styles.paddingTop) || 0,
    };
  }

  function updateBranchZoom(nextZoom: number, behavior: ScrollBehavior = "auto") {
    const zoom = clampBranchZoom(nextZoom);
    branchZoomRef.current = zoom;
    pendingZoomCenterBehaviorRef.current = behavior;
    setBranchZoom((current) => (Math.abs(current - zoom) < 0.001 ? current : zoom));
  }

  function showBranchDetail(node: BranchTreeNode, anchorElement: HTMLElement) {
    clearBranchDetailHideTimer();
    const nextStyle = getBranchDetailStyle(anchorElement);
    const isSameAnchor = detailAnchorRef.current === anchorElement;
    detailAnchorRef.current = anchorElement;
    setDetailStyle(nextStyle);
    if (detailThreadId !== node.thread_id) {
      setDetailThreadId(node.thread_id);
    } else if (!isSameAnchor) {
      updateBranchDetailPosition();
    }
    const nextDepth = Number(node.branch_depth || 0);
    if (detailDepth !== nextDepth) {
      setDetailDepth(nextDepth);
    }
  }

  useEffect(() => {
    if (!detailThreadId) return;

    function handleViewportChange() {
      updateBranchDetailPosition();
    }

    window.addEventListener("scroll", handleViewportChange, true);
    window.addEventListener("resize", handleViewportChange);
    return () => {
      window.removeEventListener("scroll", handleViewportChange, true);
      window.removeEventListener("resize", handleViewportChange);
    };
  }, [detailThreadId]);

  useEffect(() => {
    const canvas = treeCanvasRef.current;
    if (!canvas) return;

    function handleScroll() {
      if (canvasAutoCenteringRef.current) return;
      setViewportNudge((current) => (current.x === 0 && current.y === 0 ? current : { x: 0, y: 0 }));
    }

    canvas.addEventListener("scroll", handleScroll, { passive: true });
    return () => canvas.removeEventListener("scroll", handleScroll);
  }, []);

  useEffect(() => {
    setViewportNudge({ x: 0, y: 0 });
  }, [selectedThreadId]);

  useEffect(() => {
    const behavior = pendingZoomCenterBehaviorRef.current;
    if (!behavior) return;
    pendingZoomCenterBehaviorRef.current = null;
    const frame = window.requestAnimationFrame(() => {
      centerSelectedNode(branchZoom, behavior);
      updateBranchDetailPosition();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [branchZoom]);

  useEffect(() => {
    const canvas = treeCanvasRef.current;
    if (!canvas) return;

    function handleWheel(event: WheelEvent) {
      if (!event.ctrlKey && !event.metaKey) return;
      event.preventDefault();
      const nextZoom = branchZoomRef.current * Math.exp(-event.deltaY * BRANCH_ZOOM_WHEEL_SENSITIVITY);
      updateBranchZoom(nextZoom, "auto");
    }

    const handleGestureStart: EventListener = (event) => {
      event.preventDefault();
      gestureStartZoomRef.current = branchZoomRef.current;
    };

    const handleGestureChange: EventListener = (event) => {
      event.preventDefault();
      const scale = (event as WebKitGestureEvent).scale ?? 1;
      updateBranchZoom(gestureStartZoomRef.current * scale, "auto");
    };

    canvas.addEventListener("wheel", handleWheel, { passive: false });
    canvas.addEventListener("gesturestart", handleGestureStart, { passive: false } as AddEventListenerOptions);
    canvas.addEventListener("gesturechange", handleGestureChange, { passive: false } as AddEventListenerOptions);

    return () => {
      canvas.removeEventListener("wheel", handleWheel);
      canvas.removeEventListener("gesturestart", handleGestureStart);
      canvas.removeEventListener("gesturechange", handleGestureChange);
    };
  }, [selectedThreadId, graph]);

  useEffect(() => {
    if (detailThreadId && !detailNode) {
      hideBranchDetail();
    }
  }, [detailNode, detailThreadId]);

  useEffect(() => () => clearBranchDetailHideTimer(), []);

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

  async function handleCreateBranch() {
    if (!createBranchTargetThreadId || isMergedCreateTarget) return;
    await createBranch({ parentThreadId: createBranchTargetThreadId });
  }

  async function handleRenameBranch(node: BranchTreeNode) {
    if (!node.branch_id) return;
    const nextName = window.prompt(
      isChineseUi ? "重命名分支" : "Rename branch",
      node.branch_name,
    );
    if (!nextName || !nextName.trim()) return;
    setIsWorking(true);
    try {
      await renameBranch(node.thread_id, nextName.trim());
    } finally {
      setIsWorking(false);
    }
  }

  async function handleArchiveToggle(node: BranchTreeNode) {
    if (!node.branch_id) return;
    setIsWorking(true);
    try {
      if (node.is_archived) {
        await activateBranch(node.thread_id);
      } else {
        await archiveBranch(node.thread_id);
      }
    } finally {
      setIsWorking(false);
    }
  }

  async function handleOpenMergeReview(node: BranchTreeNode) {
    if (!node.branch_id) return;
    await navigate({
      to: "/c/$conversationId/t/$threadId/review",
      params: {
        conversationId: node.root_thread_id,
        threadId: node.thread_id,
      },
    });
  }

  async function handlePrepareProposal(node: BranchTreeNode) {
    if (!node.branch_id || node.is_archived || isMergeProposalPreparing(node.thread_id)) return;
    setIsWorking(true);
    markMergeProposalPreparing(node.thread_id);
    try {
      setShellStatus(
        null,
      );
      await prepareMergeProposal(node.thread_id);
      markMergeProposalReady(node.thread_id);
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : isChineseUi
            ? "生成结论失败，请重新生成"
            : "Failed to generate conclusion. Please regenerate.";
      markMergeProposalFailed(node.thread_id, message);
    } finally {
      setIsWorking(false);
    }
  }

  function parentBranchLabel(node: BranchTreeNode) {
    if (!node.parent_thread_id) {
      return isChineseUi ? "主线" : "Main";
    }
    const parent = findNode(data?.root, node.parent_thread_id);
    return parent?.branch_name || node.parent_thread_id;
  }

  return (
    <div className="fa-branch-panel">
      <section className="fa-tree-card">
        <div className="fa-tree-toolbar">
          <div className="fa-tree-actions">
            <button
              className="fa-toolbar-primary"
              {...tooltipProps(createBranchTooltip, {
                defaultTooltip: isChineseUi ? "从当前选中节点创建新分支" : "Create a branch from the selected node",
              })}
              disabled={!createBranchTargetThreadId || isMergedCreateTarget || isCreatingBranch}
              onClick={() => void handleCreateBranch()}
              type="button"
            >
              {isChineseUi ? "新建分支" : "New branch"}
            </button>
            <button
              className="fa-toolbar-secondary"
              {...tooltipProps(isChineseUi ? "刷新分支树" : "Refresh branches")}
              disabled={!params.conversationId || isFetching}
              onClick={() => void refetch()}
              type="button"
            >
              {isChineseUi ? "刷新分支树" : "Refresh branches"}
            </button>
            <span className="fa-tree-count-summary">
              {isChineseUi ? "进行中" : "In progress"} {countNodes(data?.root)} ·{" "}
              {isChineseUi ? "已归档" : "Archived"} {data?.archived_branches?.length ?? 0}
            </span>
          </div>
        </div>

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
            <div
              className="fa-tree-canvas-tools"
              role="group"
              aria-label={isChineseUi ? "分支树缩放控制" : "Branch tree zoom controls"}
            >
              <div className="fa-tree-viewport-tools">
                <button
                  className="fa-tree-zoom-button"
                  {...tooltipProps(isChineseUi ? "缩小分支树" : "Zoom out branch tree")}
                  disabled={branchZoom <= BRANCH_ZOOM_MIN}
                  onClick={() => updateBranchZoom(branchZoom - BRANCH_ZOOM_STEP, "smooth")}
                  type="button"
                >
                  -
                </button>
                <button
                  className="fa-tree-zoom-level"
                  {...tooltipProps(isChineseUi ? "重置缩放到 100%" : "Reset zoom to 100%")}
                  disabled={Math.abs(branchZoom - 1) < 0.001}
                  onClick={() => updateBranchZoom(1, "smooth")}
                  type="button"
                >
                  {branchZoomLabel(branchZoom)}
                </button>
                <button
                  className="fa-tree-zoom-button"
                  {...tooltipProps(isChineseUi ? "放大分支树" : "Zoom in branch tree")}
                  disabled={branchZoom >= BRANCH_ZOOM_MAX}
                  onClick={() => updateBranchZoom(branchZoom + BRANCH_ZOOM_STEP, "smooth")}
                  type="button"
                >
                  +
                </button>
                <button
                  className="fa-tree-locate-button"
                  {...tooltipProps(isChineseUi ? "定位到当前选中节点" : "Center the selected node")}
                  disabled={!selectedThreadId}
                  onClick={() => centerSelectedNode(branchZoomRef.current, "smooth")}
                  type="button"
                >
                  {isChineseUi ? "定位" : "Locate"}
                </button>
              </div>
            </div>
            <div ref={treeCanvasRef} className="fa-tree-canvas">
            {isLoading ? (
              <div className="fa-inline-notice">{isChineseUi ? "正在加载分支树..." : "Loading branch tree..."}</div>
            ) : null}
            {!isLoading && !data?.root ? (
              <div className="fa-inline-notice">
                {isChineseUi ? "先打开一个对话，再加载对应分支树。" : "Open a conversation to load its branch tree."}
              </div>
            ) : null}

            {data?.root ? (
              <div className="fa-tree-canvas-content">
                <div
                  ref={graphShellRef}
                  className="fa-branch-graph-shell"
                  style={{
                    width: `${graph.width * branchZoom}px`,
                    height: `${graph.height * branchZoom}px`,
                    transform: `translate(${viewportNudge.x}px, ${viewportNudge.y}px)`,
                  }}
                >
                  <div
                    className={`fa-branch-graph-main ${
                      selectedThreadId ? "has-active-selection" : ""
                    }`}
                    style={{
                      width: `${graph.width}px`,
                      height: `${graph.height}px`,
                      transform: `scale(${branchZoom})`,
                    }}
                  >
                    <div
                      className="fa-branch-graph-root-label"
                      style={
                        {
                          "--fa-branch-role-color": roleColor(data.root.branch_role),
                        } as CSSProperties
                      }
                    >
                      {isChineseUi ? "主线时间轴" : "Main timeline"}
                    </div>
                    <svg
                      className="fa-branch-graph-lines"
                      width={graph.width}
                      height={graph.height}
                      viewBox={`0 0 ${graph.width} ${graph.height}`}
                      aria-hidden="true"
                    >
                      {graph.edges.map((edge) => {
                        const from = nodeIndex.get(edge.from);
                        const to = nodeIndex.get(edge.to);
                        if (!from || !to) return null;
                        const isContext =
                          edge.from === previewThreadId ||
                          edge.to === previewThreadId ||
                          previewNode?.parent_thread_id === edge.from;
                        const isFocused =
                          edge.from === selectedThreadId || edge.to === selectedThreadId;
                        return (
                          <path
                            key={`${edge.from}-${edge.to}`}
                            className={`fa-branch-graph-edge ${isContext ? "is-context" : ""} ${
                              isFocused ? "is-focused" : ""
                            }`}
                            d={edgePath(from, to)}
                            stroke={edge.color}
                          />
                        );
                      })}
                    </svg>

                    {graph.nodes.map((item) => {
                      const node = item.node;
                      const active = node.thread_id === params.threadId;
                      const focused = node.thread_id === selectedThreadId;
                      const isContext =
                        node.thread_id === previewThreadId ||
                        node.parent_thread_id === previewThreadId ||
                        previewNode?.parent_thread_id === node.thread_id;
                      const tone = statusTone(node.branch_status);
                      return (
                        <div
                          key={node.thread_id}
                          className={`fa-branch-graph-node-shell ${
                            active || detailThreadId === node.thread_id ? "active-card" : ""
                          }`}
                          style={{ left: `${item.x}px`, top: `${item.y}px` }}
                          onMouseEnter={(event) =>
                            showBranchDetail(node, event.currentTarget.querySelector("button") as HTMLElement)
                          }
                          onMouseLeave={(event) => {
                            if (
                              event.relatedTarget instanceof Node &&
                              detailOverlayRef.current?.contains(event.relatedTarget)
                            ) {
                              return;
                            }
                            scheduleHideBranchDetail();
                          }}
                        >
                          <button
                            className={`fa-branch-graph-node ${active ? "is-active" : ""} ${
                              focused ? "is-focused" : ""
                            } ${isContext ? "is-context" : ""} ${tone}`}
                            style={
                              {
                                "--fa-branch-role-color": roleColor(node.branch_role),
                              } as CSSProperties
                            }
                            onClick={() => void openThread(node.thread_id)}
                            onFocus={(event) => showBranchDetail(node, event.currentTarget)}
                            onBlur={(event) => {
                              if (
                                event.relatedTarget instanceof Node &&
                                detailOverlayRef.current?.contains(event.relatedTarget)
                              ) {
                                return;
                              }
                              scheduleHideBranchDetail();
                            }}
                            type="button"
                          >
                            <span className="sr-only">
                              {node.branch_name} · {roleLabel(node.branch_role, isChineseUi)} ·{" "}
                              {branchStatusLabel(node.branch_status, isChineseUi)}
                            </span>
                          </button>
                        </div>
                      );
                    })}

                  </div>
                </div>
              </div>
            ) : null}
            </div>
          </div>
        </div>
      </section>

      <section className="fa-tree-card is-archived">
        <div className="fa-tree-section-header">
          <div className="fa-tree-section-title-group">
            <h3 className="fa-tree-subsection-title">
              {isChineseUi ? "已归档会话" : "Archived conversations"}
            </h3>
            <div className="fa-tree-summary">
              {isChineseUi
                ? "归档后会从活动区移除，恢复后才会回来。"
                : "Archived conversations leave the active list until you restore them."}
            </div>
          </div>
          <button
            className={`fa-tree-section-toggle ${archivedConversationsExpanded ? "" : "is-collapsed"}`.trim()}
            onClick={() => setArchivedConversationsExpanded((value) => !value)}
            type="button"
            aria-expanded={archivedConversationsExpanded}
            aria-label={isChineseUi ? "展开或收起已归档会话" : "Toggle archived conversations"}
          >
            <svg viewBox="0 0 20 20" aria-hidden="true">
              <path
                d="m7 4 6 6-6 6"
                fill="none"
                stroke="currentColor"
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="1.8"
              />
            </svg>
          </button>
        </div>
        {archivedConversations.length && archivedConversationsExpanded ? (
          <div className="fa-archived-list is-conversations">
            {archivedConversations.map((conversation) => (
              <div
                key={conversation.root_thread_id}
                className="fa-archived-item is-conversation"
                style={
                  {
                    "--fa-branch-role-color": "#8FA7BF",
                  } as CSSProperties
                }
              >
                <div className="fa-archived-item-head">
                  <div className="fa-archived-item-copy">
                    <div className="fa-archived-item-name">{conversation.title}</div>
                    {shouldShowArchivedSecondaryLine(conversation.title, conversation.root_thread_id) ? (
                      <div className="fa-archived-item-id">{conversation.root_thread_id}</div>
                    ) : null}
                  </div>
                  <div className="fa-archived-item-toolbar">
                    <div className="fa-tree-node-actions is-archived-actions">
                      <button
                        className="fa-branch-action-button"
                        onClick={() => void openConversation(conversation.root_thread_id)}
                        type="button"
                      >
                        {isChineseUi ? "打开" : "Open"}
                      </button>
                      <button
                        className="fa-branch-action-button"
                        {...tooltipProps(isChineseUi ? "恢复这个对话" : "Restore this conversation")}
                        disabled={isWorking}
                        onClick={() => void activateConversation(conversation.root_thread_id)}
                        type="button"
                      >
                        {isChineseUi ? "恢复" : "Restore"}
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : archivedConversations.length ? null : (
          <div className="fa-inline-notice fa-archived-empty">
            {isChineseUi ? "暂无已归档会话。" : "No archived conversations."}
          </div>
        )}
      </section>

      <section className="fa-tree-card is-archived">
        <div className="fa-tree-section-header">
          <div className="fa-tree-section-title-group">
            <h3 className="fa-tree-subsection-title">
              {isChineseUi ? "已归档分支" : "Archived branches"}
            </h3>
            <div className="fa-tree-summary">
              {isChineseUi
                ? "归档后会从分支树中移除，恢复后才会回来。"
                : "Archived branches leave the tree until you restore them."}
            </div>
          </div>
          <button
            className={`fa-tree-section-toggle ${archivedBranchesExpanded ? "" : "is-collapsed"}`.trim()}
            onClick={() => setArchivedBranchesExpanded((value) => !value)}
            type="button"
            aria-expanded={archivedBranchesExpanded}
            aria-label={isChineseUi ? "展开或收起已归档分支" : "Toggle archived branches"}
          >
            <svg viewBox="0 0 20 20" aria-hidden="true">
              <path
                d="m7 4 6 6-6 6"
                fill="none"
                stroke="currentColor"
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="1.8"
              />
            </svg>
          </button>
        </div>
        {data?.archived_branches?.length && archivedBranchesExpanded ? (
          <div className="fa-archived-list">
            {data.archived_branches.map((node) => (
              <div
                key={node.thread_id}
                className="fa-archived-item"
                style={
                  {
                    "--fa-branch-role-color": roleColor(node.branch_role),
                  } as CSSProperties
                }
              >
                <div className="fa-archived-item-head">
                  <div className="fa-archived-item-copy">
                    <div className="fa-archived-item-name">{node.branch_name}</div>
                    {shouldShowArchivedSecondaryLine(node.branch_name, node.thread_id) ? (
                      <div className="fa-archived-item-id">{node.thread_id}</div>
                    ) : null}
                  </div>
                  <div className="fa-archived-item-toolbar">
                    <div
                      className={`fa-archived-item-status is-archived ${statusAccentTone(node.branch_status)}`.trim()}
                    >
                      {branchStatusLabel(node.branch_status, isChineseUi)}
                    </div>
                    <div className="fa-tree-node-actions is-archived-actions">
                      <button className="fa-branch-action-button" onClick={() => void openThread(node.thread_id)} type="button">
                        {isChineseUi ? "打开" : "Open"}
                      </button>
                      <button
                        className="fa-branch-action-button"
                        {...tooltipProps(isChineseUi ? "恢复这个分支" : "Restore this branch")}
                        disabled={isWorking}
                        onClick={() => void handleArchiveToggle(node)}
                        type="button"
                      >
                        {isChineseUi ? "恢复" : "Restore"}
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : data?.archived_branches?.length ? null : (
          <div className="fa-inline-notice fa-archived-empty">
            {isChineseUi ? "暂无已归档分支。" : "No archived branches."}
          </div>
        )}
      </section>

      {detailOverlay}
    </div>
  );
}
