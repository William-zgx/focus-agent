import { useEffect } from "react";
import type { ThreadStateResponse } from "@focus-agent/web-sdk";

import { MergeReviewCard } from "@/features/merge-review/merge-review-card";

type MergeReviewModalHostProps = {
  activeThreadState: ThreadStateResponse | undefined;
  conversationId: string;
  isChineseUi: boolean;
  isReviewRoute: boolean;
  onClose: () => void;
  threadId: string;
};

export function MergeReviewModalHost({
  activeThreadState,
  conversationId,
  isChineseUi,
  isReviewRoute,
  onClose,
  threadId,
}: MergeReviewModalHostProps) {
  const activeThreadIsMergedBranch = activeThreadState?.branch_meta?.branch_status === "merged";

  useEffect(() => {
    document.body.classList.toggle("has-modal", isReviewRoute);
    return () => {
      document.body.classList.remove("has-modal");
    };
  }, [isReviewRoute]);

  useEffect(() => {
    if (!isReviewRoute) return;

    function handleKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key !== "Escape") return;
      onClose();
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [isReviewRoute, onClose]);

  if (!isReviewRoute) return null;

  return (
    <>
      <button
        aria-label={isChineseUi ? "关闭弹层" : "Close dialog"}
        className="fa-modal-backdrop"
        onClick={onClose}
        type="button"
      />

      {threadId ? (
        <section className="fa-focus-modal" role="dialog" aria-modal="true" aria-labelledby="fa-merge-review-title">
          <div className="fa-focus-modal-card">
            <div className="fa-focus-modal-head">
              <div className="fa-focus-modal-copy">
                <h3 id="fa-merge-review-title">
                  {isChineseUi ? "合并结论" : "Merge conclusion"}
                </h3>
                <p>
                  {isChineseUi
                    ? "检查已生成的分支结论，选择导入方式，并明确批准或拒绝上游导入。"
                    : "Review the generated branch conclusion, choose an import mode, and explicitly approve or reject the upstream import."}
                </p>
              </div>
              <button
                aria-label={isChineseUi ? "关闭合并评审弹层" : "Close merge review dialog"}
                className="fa-focus-modal-close"
                onClick={onClose}
                type="button"
              >
                ×
              </button>
            </div>
            {activeThreadState?.branch_meta ? (
              activeThreadIsMergedBranch ? (
                <div className="fa-inline-notice is-danger">
                  {isChineseUi
                    ? "已合并分支不能继续生成或合并结论。"
                    : "Merged branches cannot generate or merge conclusions."}
                </div>
              ) : (
                <MergeReviewCard
                  rootThreadId={conversationId}
                  threadId={threadId}
                  proposal={activeThreadState.merge_proposal}
                  branchName={activeThreadState.branch_meta.branch_name}
                  pendingStatus={activeThreadState.branch_meta.branch_status}
                  onClose={onClose}
                />
              )
            ) : (
              <div className="fa-inline-notice is-danger">
                {isChineseUi
                  ? "合并评审只适用于分支线程。"
                  : "Merge review only applies to branch threads."}
              </div>
            )}
          </div>
        </section>
      ) : null}
    </>
  );
}
