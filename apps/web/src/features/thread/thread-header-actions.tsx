import { useNavigate, useRouterState } from "@tanstack/react-router";
import { useLayoutEffect, useRef, useState } from "react";

import { useShellUi } from "@/app/shell/shell-ui-context";
import { useBranchActions } from "@/features/branch-tree/use-branch-actions";
import { useThreadState } from "@/features/thread/use-thread-state";
import { syncTooltipText, tooltipProps } from "@/shared/ui/tooltip";

interface ThreadHeaderActionsProps {
  onRequestOpenSidebar?: () => void;
}

function statusNeedsProposal(status?: string) {
  return !status || (status !== "awaiting_merge_review" && status !== "preparing_merge_review");
}

function mergedBranchForkDisabledLabel(isChineseUi: boolean) {
  return isChineseUi ? "已合并分支不能新建分支" : "Merged branches cannot create new branches";
}

export function ThreadHeaderActions({ onRequestOpenSidebar }: ThreadHeaderActionsProps) {
  const navigate = useNavigate();
  const { conversationId, threadId, isReviewRoute } = useRouterState({
    select: (state) => {
      const routeParams = (state.matches.at(-1)?.params ?? {}) as Partial<
        Record<"conversationId" | "threadId", string>
      >;
      return {
        conversationId: String(routeParams.conversationId ?? ""),
        threadId: String(routeParams.threadId ?? ""),
        isReviewRoute: state.location.pathname.endsWith("/review"),
      };
    },
  });
  const { data } = useThreadState(threadId);
  const branchMeta = data?.branch_meta;
  const { prepareMergeProposal } = useBranchActions({
    rootThreadId: conversationId,
    threadId,
  });
  const [isWorking, setIsWorking] = useState(false);
  const actionsRef = useRef<HTMLDivElement | null>(null);
  const {
    createBranch,
    isCreatingBranch,
    setShellStatus,
    isChineseUi,
    markMergeProposalPreparing,
    markMergeProposalReady,
    markMergeProposalFailed,
    isMergeProposalPreparing,
    getMergeProposalError,
  } = useShellUi();
  const isMergedBranch = branchMeta?.branch_status === "merged";
  const isGeneratingConclusion =
    Boolean(threadId) &&
    (branchMeta?.branch_status === "preparing_merge_review" ||
      isMergeProposalPreparing(threadId));
  const hasPreparedConclusion =
    Boolean(data?.merge_proposal) || branchMeta?.branch_status === "awaiting_merge_review";
  const conclusionGenerationError = threadId ? getMergeProposalError(threadId) : null;
  const defaultNewBranchTooltip = isChineseUi ? "从当前线程创建分支" : "Create a branch from this thread";
  const newBranchTooltip = isMergedBranch
    ? mergedBranchForkDisabledLabel(isChineseUi)
    : defaultNewBranchTooltip;
  const reviewActionText = isReviewRoute
    ? isChineseUi
      ? "回到线程"
      : "Back to thread"
    : isGeneratingConclusion
      ? isChineseUi
        ? "生成结论中"
        : "Generating conclusion"
      : hasPreparedConclusion
        ? isChineseUi
          ? "合并结论"
          : "Merge conclusion"
        : conclusionGenerationError
          ? isChineseUi
            ? "重新生成结论"
            : "Regenerate conclusion"
        : isChineseUi
          ? "生成结论"
          : "Generate conclusion";
  const reviewActionTooltip = isReviewRoute
    ? isChineseUi
      ? "回到当前线程"
      : "Back to thread"
    : isGeneratingConclusion
      ? isChineseUi
        ? "分支结论正在生成"
        : "Conclusion is being generated"
      : hasPreparedConclusion
        ? isChineseUi
          ? "打开合并结论弹窗"
          : "Open merge conclusion dialog"
        : conclusionGenerationError
          ? isChineseUi
            ? "上次生成失败，重新生成分支结论"
            : "The last generation failed. Regenerate the branch conclusion."
        : isChineseUi
          ? "异步生成分支结论"
          : "Generate conclusion asynchronously";

  const currentLabel = branchMeta?.branch_name || (threadId ? (isChineseUi ? "主线" : "Main") : isChineseUi ? "未选择" : "No thread");

  function focusBranchPanel() {
    onRequestOpenSidebar?.();
    window.requestAnimationFrame(() => {
      const panel = document.querySelector(".fa-sidebar-panel");
      if (!(panel instanceof HTMLElement)) return;
      panel.classList.add("is-spotlight");
      panel.scrollIntoView({ block: "nearest", behavior: "smooth" });
      window.setTimeout(() => panel.classList.remove("is-spotlight"), 700);
    });
  }

  useLayoutEffect(() => {
    let frameId = 0;

    function buttonLabelIsTruncated(button: HTMLElement) {
      const label = button.querySelector(".fa-toolbar-text");
      if (!(label instanceof HTMLElement)) {
        return false;
      }
      return label.scrollWidth > label.clientWidth + 2;
    }

    function visibleElementWidth(element: Element | null) {
      if (!(element instanceof HTMLElement) || element.hidden) {
        return 0;
      }
      return Math.ceil(Math.max(element.scrollWidth, element.getBoundingClientRect().width));
    }

    function actionGroupsNeedCompact(actions: HTMLElement) {
      const groups = Array.from(actions.children).filter(
        (child) => child instanceof HTMLElement && !child.hidden,
      );
      if (!groups.length) {
        return false;
      }
      const styles = window.getComputedStyle(actions);
      const gap = Number.parseFloat(styles.columnGap || styles.gap || "0") || 0;
      const requiredWidth =
        groups.reduce((total, group) => total + visibleElementWidth(group), 0) +
        gap * Math.max(0, groups.length - 1);
      return requiredWidth > actions.clientWidth + 2;
    }

    function compactButtonsAreClipped(actions: HTMLElement, compactButtons: HTMLElement[]) {
      const actionsRect = actions.getBoundingClientRect();
      return compactButtons.some((button) => {
        const rect = button.getBoundingClientRect();
        return rect.left < actionsRect.left - 1 || rect.right > actionsRect.right + 1;
      });
    }

    function recomputeCompact() {
      const container = actionsRef.current;
      if (!container) return;
      const compactButtons = Array.from(
        container.querySelectorAll('[data-compact-button="true"]'),
      ).filter((button): button is HTMLElement => button instanceof HTMLElement);
      container.classList.remove("is-compact");
      for (const button of compactButtons) {
        syncTooltipText(button, button.dataset.defaultTooltip);
      }
      const hasTruncatedLabel = compactButtons.some((button) => buttonLabelIsTruncated(button));
      const shouldHideLabel =
        actionGroupsNeedCompact(container) ||
        compactButtonsAreClipped(container, compactButtons) ||
        hasTruncatedLabel;
      container.classList.toggle("is-compact", shouldHideLabel);
      for (const button of compactButtons) {
        const tooltip = button.dataset.fullLabel || button.getAttribute("aria-label") || "";
        if (shouldHideLabel && tooltip) {
          syncTooltipText(button, tooltip);
        } else if (button.dataset.defaultTooltip || button.title) {
          syncTooltipText(button, button.dataset.defaultTooltip);
        } else {
          syncTooltipText(button, undefined);
        }
      }
    }

    function scheduleRecomputeCompact() {
      window.cancelAnimationFrame(frameId);
      frameId = window.requestAnimationFrame(() => {
        recomputeCompact();
      });
    }

    const container = actionsRef.current;
    if (!container) return;
    const header = container.closest(".fa-chat-header-top");

    scheduleRecomputeCompact();
    const observer = new ResizeObserver(() => {
      scheduleRecomputeCompact();
    });
    observer.observe(container);
    if (header instanceof HTMLElement) {
      observer.observe(header);
    }
    const mutationObserver = new MutationObserver(() => {
      scheduleRecomputeCompact();
    });
    mutationObserver.observe(container, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeFilter: ["hidden", "class", "style", "data-full-label"],
    });
    window.addEventListener("resize", scheduleRecomputeCompact);
    document.fonts?.ready?.then(() => {
      scheduleRecomputeCompact();
    });
    return () => {
      observer.disconnect();
      mutationObserver.disconnect();
      window.cancelAnimationFrame(frameId);
      window.removeEventListener("resize", scheduleRecomputeCompact);
    };
  }, [
    branchMeta?.branch_id,
    branchMeta?.branch_name,
    branchMeta?.parent_thread_id,
    branchMeta?.branch_status,
    conversationId,
    isChineseUi,
    isReviewRoute,
    isWorking,
    threadId,
  ]);

  async function openReviewRoute(targetThreadId: string) {
    await navigate({
      to: "/c/$conversationId/t/$threadId/review",
      params: {
        conversationId,
        threadId: targetThreadId,
      },
    });
  }

  async function openThread(targetThreadId: string) {
    await navigate({
      to: "/c/$conversationId/t/$threadId",
      params: {
        conversationId,
        threadId: targetThreadId,
      },
    });
  }

  async function handleForkBranch() {
    if (!threadId || isMergedBranch) return;
    await createBranch({ parentThreadId: threadId });
  }

  async function handleBackMain() {
    if (!conversationId) return;
    await openThread(conversationId);
  }

  async function handleBackParent() {
    if (!branchMeta?.parent_thread_id) return;
    await openThread(branchMeta.parent_thread_id);
  }

  async function handleReviewAction() {
    if (!branchMeta?.branch_id || !threadId) return;
    setIsWorking(true);
    let didStartGeneration = false;
    try {
      if (isReviewRoute) {
        await openThread(threadId);
        setShellStatus(
          {
            tone: "success",
            text: isChineseUi ? "已返回线程" : "Returned to thread",
          },
          { autoClearMs: 2200 },
        );
        return;
      }
      if (hasPreparedConclusion) {
        await openReviewRoute(threadId);
        return;
      }
      if (statusNeedsProposal(branchMeta.branch_status)) {
        didStartGeneration = true;
        markMergeProposalPreparing(threadId);
        setShellStatus(null);
        await prepareMergeProposal(threadId);
        markMergeProposalReady(threadId);
      }
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : isChineseUi
            ? "生成结论失败，请重新生成"
            : "Failed to generate conclusion. Please regenerate.";
      if (didStartGeneration) {
        markMergeProposalFailed(threadId, message);
      }
    } finally {
      setIsWorking(false);
    }
  }

  return (
    <div ref={actionsRef} className="fa-chat-header-actions">
      <div className="fa-chat-header-primary-actions">
        <button
          className="fa-chat-toolbar-pill fa-focus-branches-button"
          data-compact-button="true"
          data-full-label={`${isChineseUi ? "当前分支" : "current"}: ${currentLabel}`}
          {...tooltipProps(isChineseUi ? "定位左侧分支树" : "Focus branches", {
            defaultTooltip: isChineseUi ? "定位左侧分支树" : "Focus branches",
          })}
          aria-label={`${isChineseUi ? "当前分支" : "current"}: ${currentLabel}`}
          onClick={focusBranchPanel}
          type="button"
        >
          <span className="fa-toolbar-icon" aria-hidden="true">
            <svg viewBox="0 0 20 20">
              <path
                fillRule="evenodd"
                clipRule="evenodd"
                d="M10 3.2a6.8 6.8 0 1 1 0 13.6 6.8 6.8 0 0 1 0-13.6Zm0 2.3a4.5 4.5 0 1 0 0 9 4.5 4.5 0 0 0 0-9Z"
                fill="currentColor"
              />
              <rect x="9.15" y="1.85" width="1.7" height="3.1" rx="0.85" fill="currentColor" />
              <rect x="9.15" y="15.05" width="1.7" height="3.1" rx="0.85" fill="currentColor" />
              <rect x="1.85" y="9.15" width="3.1" height="1.7" rx="0.85" fill="currentColor" />
              <rect x="15.05" y="9.15" width="3.1" height="1.7" rx="0.85" fill="currentColor" />
              <circle cx="10" cy="10" r="1.6" fill="currentColor" />
            </svg>
          </span>
          <span className="fa-toolbar-text">
            {isChineseUi ? "当前分支" : "current"}: {currentLabel}
          </span>
        </button>

        <button
          className="fa-chat-toolbar-button is-primary fa-new-branch-button"
          data-compact-button="true"
          data-full-label={isChineseUi ? "新建分支" : "New branch"}
          {...tooltipProps(newBranchTooltip, {
            defaultTooltip: defaultNewBranchTooltip,
          })}
          aria-label={isChineseUi ? "新建分支" : "New branch"}
          disabled={!threadId || isWorking || isMergedBranch || isCreatingBranch}
          onClick={() => void handleForkBranch()}
          type="button"
        >
          <span className="fa-toolbar-icon" aria-hidden="true">
            <svg viewBox="0 0 20 20">
              <circle cx="5" cy="5" r="1.75" fill="currentColor" />
              <circle cx="5" cy="15" r="1.75" fill="currentColor" />
              <rect x="4.15" y="6.6" width="1.7" height="6.8" rx="0.85" fill="currentColor" />
              <rect x="6.7" y="14.15" width="4.3" height="1.7" rx="0.85" fill="currentColor" />
              <rect x="12.15" y="4.9" width="5.7" height="1.7" rx="0.85" fill="currentColor" />
              <rect x="14.15" y="2.9" width="1.7" height="5.7" rx="0.85" fill="currentColor" />
            </svg>
          </span>
          <span className="fa-toolbar-text">{isChineseUi ? "新建分支" : "New branch"}</span>
        </button>

        {branchMeta ? (
          <button
            className="fa-chat-toolbar-button fa-review-button"
            data-compact-button="true"
            data-full-label={reviewActionText}
            {...tooltipProps(reviewActionTooltip, {
              defaultTooltip: reviewActionTooltip,
            })}
            disabled={isWorking || (!isReviewRoute && isGeneratingConclusion)}
            onClick={() => void handleReviewAction()}
            type="button"
            aria-label={reviewActionText}
          >
            <span className="fa-toolbar-icon" aria-hidden="true">
              <svg viewBox="0 0 20 20">
                <path d="M4.5 10h8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                <path
                  d="m10 6 4 4-4 4"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </span>
            <span className="fa-toolbar-text">
              {reviewActionText}
            </span>
          </button>
        ) : null}
      </div>

      {branchMeta ? (
        <div className="fa-chat-header-nav">
          {threadId !== conversationId ? (
            <button
              className="fa-chat-toolbar-button fa-back-main-button"
              data-compact-button="true"
              data-full-label={isChineseUi ? "回到主线" : "Back to main"}
              {...tooltipProps(isChineseUi ? "回到主线线程" : "Back to main", {
                defaultTooltip: isChineseUi ? "回到主线线程" : "Back to main",
              })}
              aria-label={isChineseUi ? "回到主线" : "Back to main"}
              onClick={() => void handleBackMain()}
              type="button"
            >
              <span className="fa-toolbar-icon" aria-hidden="true">
                <svg viewBox="0 0 20 20">
                  <path
                    d="m12.5 5-5 5 5 5"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </span>
              <span className="fa-toolbar-text">{isChineseUi ? "回到主分支" : "Back to main"}</span>
            </button>
          ) : null}
          {branchMeta.parent_thread_id && branchMeta.parent_thread_id !== conversationId ? (
            <button
              className="fa-chat-toolbar-button fa-back-parent-button"
              data-compact-button="true"
              data-full-label={isChineseUi ? "回到上一层" : "Back one level"}
              {...tooltipProps(isChineseUi ? "回到父分支线程" : "Back one level", {
                defaultTooltip: isChineseUi ? "回到父分支线程" : "Back one level",
              })}
              aria-label={isChineseUi ? "回到上一层" : "Back one level"}
              onClick={() => void handleBackParent()}
              type="button"
            >
              <span className="fa-toolbar-icon" aria-hidden="true">
                <svg viewBox="0 0 20 20">
                  <path
                    d="M14 6H9a3 3 0 0 0-3 3v5"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                  />
                  <path
                    d="m9 6-3 3 3 3"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </span>
              <span className="fa-toolbar-text">{isChineseUi ? "回到上一层" : "Back one level"}</span>
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
