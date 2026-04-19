import type {
  FocusAgentApplyMergeDecisionRequest,
  FocusAgentImportedConclusion,
  FocusAgentMergeProposal,
  MergeMode,
  MergeTarget,
} from "@focus-agent/web-sdk";
import { useNavigate } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";

import { useShellUi } from "@/app/shell/shell-ui-context";
import { useBranchActions } from "@/features/branch-tree/use-branch-actions";

interface MergeReviewCardProps {
  rootThreadId: string;
  threadId: string;
  proposal?: FocusAgentMergeProposal | null;
  branchName?: string;
  pendingStatus?: string;
  onClose?: () => void | Promise<void>;
}

function parseLineList(value: string) {
  return value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}

function modeOptionLabel(value: MergeMode, isChineseUi: boolean) {
  switch (value) {
    case "summary_only":
      return isChineseUi ? "仅摘要" : "Summary only";
    case "summary_plus_evidence":
      return isChineseUi ? "摘要 + 证据" : "Summary + evidence";
    case "selected_artifacts":
      return isChineseUi ? "仅选定产物" : "Selected artifacts only";
    case "none":
      return isChineseUi ? "丢弃" : "Discard";
    default:
      return value;
  }
}

function targetOptionLabel(value: MergeTarget, isChineseUi: boolean) {
  switch (value) {
    case "return_thread":
      return isChineseUi ? "返回上游" : "Return upstream";
    case "root_thread":
      return isChineseUi ? "主分支" : "Main branch";
    default:
      return value;
  }
}

function recommendedImportModeLabel(value: MergeMode | undefined, isChineseUi: boolean) {
  return isChineseUi
    ? `推荐导入方式：${modeOptionLabel(value ?? "summary_only", true)}`
    : `Recommended import mode: ${modeOptionLabel(value ?? "summary_only", false)}`;
}

function mergeReviewStatusLabel(status: string | undefined, isChineseUi: boolean) {
  switch (status) {
    case "awaiting_merge_review":
      return isChineseUi ? "等待评审" : "Awaiting review";
    case "preparing_merge_review":
      return isChineseUi ? "准备评审" : "Preparing review";
    case "merged":
      return isChineseUi ? "已合并" : "Merged";
    case "paused":
      return isChineseUi ? "已暂停" : "Paused";
    case "discarded":
      return isChineseUi ? "已丢弃" : "Discarded";
    case "closed":
      return isChineseUi ? "已关闭" : "Closed";
    default:
      return isChineseUi ? "进行中" : "Active";
  }
}

export function MergeReviewCard({
  rootThreadId,
  threadId,
  proposal,
  branchName,
  pendingStatus,
  onClose,
}: MergeReviewCardProps) {
  const { prepareMergeProposal, applyMergeDecision } = useBranchActions({
    rootThreadId,
    threadId,
  });
  const {
    isChineseUi,
    markMergeProposalPreparing,
    markMergeProposalReady,
    markMergeProposalFailed,
    isMergeProposalPreparing,
  } = useShellUi();
  const navigate = useNavigate();
  const [isPreparing, setIsPreparing] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [summary, setSummary] = useState(proposal?.summary ?? "");
  const [findings, setFindings] = useState((proposal?.key_findings ?? []).join("\n"));
  const [openQuestions, setOpenQuestions] = useState((proposal?.open_questions ?? []).join("\n"));
  const [evidenceRefs, setEvidenceRefs] = useState((proposal?.evidence_refs ?? []).join("\n"));
  const [artifacts, setArtifacts] = useState((proposal?.artifacts ?? []).join("\n"));
  const [decision, setDecision] = useState<"approve" | "reject">("approve");
  const [mode, setMode] = useState<MergeMode>(
    proposal?.recommended_import_mode ?? "summary_only",
  );
  const [target, setTarget] = useState<MergeTarget>("return_thread");
  const [selectedArtifacts, setSelectedArtifacts] = useState("");
  const [rationale, setRationale] = useState("");
  const [lastImported, setLastImported] = useState<FocusAgentImportedConclusion | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const proposalSignature = proposal ? JSON.stringify(proposal) : "no-proposal";
  const shouldShowSelectedArtifacts =
    decision === "approve" && mode === "selected_artifacts";
  const isPreparingConclusion = isPreparing || isMergeProposalPreparing(threadId);

  const modeOptions = useMemo(
    () =>
      (["summary_only", "summary_plus_evidence", "selected_artifacts"] as MergeMode[]).map(
        (value) => ({
          value,
          label: modeOptionLabel(value, isChineseUi),
        }),
      ),
    [isChineseUi],
  );
  const targetOptions = useMemo(
    () =>
      (["return_thread", "root_thread"] as MergeTarget[]).map((value) => ({
        value,
        label: targetOptionLabel(value, isChineseUi),
      })),
    [isChineseUi],
  );

  useEffect(() => {
    setSummary(proposal?.summary ?? "");
    setFindings((proposal?.key_findings ?? []).join("\n"));
    setOpenQuestions((proposal?.open_questions ?? []).join("\n"));
    setEvidenceRefs((proposal?.evidence_refs ?? []).join("\n"));
    setArtifacts((proposal?.artifacts ?? []).join("\n"));
    setDecision("approve");
    setMode(proposal?.recommended_import_mode ?? "summary_only");
    setTarget("return_thread");
    setSelectedArtifacts("");
    setRationale("");
    setLastImported(null);
    setErrorMessage(null);
  }, [threadId, proposalSignature]);

  async function handlePrepareProposal() {
    setIsPreparing(true);
    markMergeProposalPreparing(threadId);
    setErrorMessage(null);
    try {
      const nextProposal = await prepareMergeProposal(threadId);
      markMergeProposalReady(threadId);
      setSummary(nextProposal?.summary ?? "");
      setFindings((nextProposal?.key_findings ?? []).join("\n"));
      setOpenQuestions((nextProposal?.open_questions ?? []).join("\n"));
      setEvidenceRefs((nextProposal?.evidence_refs ?? []).join("\n"));
      setArtifacts((nextProposal?.artifacts ?? []).join("\n"));
      setMode(nextProposal?.recommended_import_mode ?? "summary_only");
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : isChineseUi
            ? "生成合并提案失败。"
            : "Failed to prepare proposal.";
      setErrorMessage(message);
      markMergeProposalFailed(threadId, message);
    } finally {
      setIsPreparing(false);
    }
  }

  async function handleSubmit() {
    const payload: FocusAgentApplyMergeDecisionRequest = {
      approved: decision === "approve",
      mode,
      target,
      rationale: rationale.trim() || undefined,
      selected_artifacts: shouldShowSelectedArtifacts
        ? parseLineList(selectedArtifacts)
        : undefined,
      proposal_overrides: {
        summary: summary.trim() || null,
        key_findings: parseLineList(findings),
        open_questions: parseLineList(openQuestions),
        evidence_refs: parseLineList(evidenceRefs),
        artifacts: parseLineList(artifacts),
        recommended_import_mode: mode,
      },
    };

    setIsSubmitting(true);
    setErrorMessage(null);
    try {
      const response = await applyMergeDecision(threadId, payload);
      setLastImported(response.imported ?? null);
      await navigate({
        to: "/c/$conversationId/t/$threadId",
        params: {
          conversationId: rootThreadId,
          threadId,
        },
      });
    } catch (error) {
      setErrorMessage(
        error instanceof Error
          ? error.message
          : isChineseUi
            ? "提交合并决策失败。"
            : "Failed to apply merge decision.",
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="fa-merge-review-shell">
      {!proposal ? (
        <div className="fa-focus-modal-loading">
          <strong>{isChineseUi ? "正在准备合并提案..." : "Preparing merge proposal..."}</strong>
          <p>
            {isChineseUi
              ? "这可能需要一点时间来生成分支总结。"
              : "This can take a moment while the branch summary is prepared."}
          </p>
          <div className="fa-focus-modal-actions">
            <button disabled={isPreparingConclusion} onClick={() => void handlePrepareProposal()} type="button">
              {isPreparingConclusion
                ? isChineseUi
                  ? "生成中..."
                  : "Preparing..."
                : isChineseUi
                  ? "生成带回结论"
                  : "Generate conclusion"}
            </button>
          </div>
        </div>
      ) : (
        <>
          {(branchName || pendingStatus) ? (
            <div className="fa-focus-modal-note">
              {branchName ? `${isChineseUi ? "分支" : "Branch"}: ${branchName}` : null}
              {branchName && pendingStatus ? " · " : null}
              {pendingStatus
                ? `${isChineseUi ? "状态" : "Status"}: ${mergeReviewStatusLabel(
                    pendingStatus,
                    isChineseUi,
                  )}`
                : null}
            </div>
          ) : null}
          <div className="fa-focus-modal-section">
            <h4>{isChineseUi ? "摘要" : "Summary"}</h4>
            <label className="fa-focus-modal-field">
              <span>{isChineseUi ? "摘要" : "Summary"}</span>
              <textarea
                onChange={(event) => setSummary(event.target.value)}
                placeholder={
                  isChineseUi ? "可在合并前修改这段摘要" : "Edit the summary before merging"
                }
                value={summary}
              />
            </label>
          </div>

          <div className="fa-focus-modal-section">
            <h4>{isChineseUi ? "关键发现" : "Key findings"}</h4>
            <label className="fa-focus-modal-field">
              <span>{isChineseUi ? "关键发现" : "Key findings"}</span>
              <textarea
                onChange={(event) => setFindings(event.target.value)}
                placeholder={isChineseUi ? "每行输入一条关键结论" : "One finding per line"}
                value={findings}
              />
            </label>
          </div>

          <div className="fa-focus-modal-section">
            <h4>{isChineseUi ? "开放问题" : "Open questions"}</h4>
            <label className="fa-focus-modal-field">
              <span>{isChineseUi ? "开放问题" : "Open questions"}</span>
              <textarea
                onChange={(event) => setOpenQuestions(event.target.value)}
                placeholder={
                  isChineseUi ? "每行输入一条开放问题" : "One open question per line"
                }
                value={openQuestions}
              />
            </label>
          </div>

          <div className="fa-focus-modal-section">
            <h4>{isChineseUi ? "证据引用" : "Evidence refs"}</h4>
            <label className="fa-focus-modal-field">
              <span>{isChineseUi ? "证据引用" : "Evidence refs"}</span>
              <textarea
                onChange={(event) => setEvidenceRefs(event.target.value)}
                placeholder={isChineseUi ? "每行输入一条证据引用" : "One evidence ref per line"}
                value={evidenceRefs}
              />
            </label>
          </div>

          <div className="fa-focus-modal-section">
            <h4>{isChineseUi ? "产物" : "Artifacts"}</h4>
            <label className="fa-focus-modal-field">
              <span>{isChineseUi ? "产物" : "Artifacts"}</span>
              <textarea
                onChange={(event) => setArtifacts(event.target.value)}
                placeholder={
                  isChineseUi
                    ? "每行输入一个 artifact 路径或 id"
                    : "One artifact path or id per line"
                }
                value={artifacts}
              />
            </label>
          </div>

          <div className="fa-focus-modal-note">
            {recommendedImportModeLabel(proposal.recommended_import_mode, isChineseUi)}
          </div>

          <div className="fa-focus-modal-form">
            <label className="fa-focus-modal-field">
              <span>{isChineseUi ? "决定" : "Decision"}</span>
              <select
                onChange={(event) => setDecision(event.target.value as "approve" | "reject")}
                value={decision}
              >
                <option value="approve">{isChineseUi ? "批准" : "Approve"}</option>
                <option value="reject">{isChineseUi ? "拒绝" : "Reject"}</option>
              </select>
            </label>

            <label className="fa-focus-modal-field">
              <span>{isChineseUi ? "导入方式" : "Import mode"}</span>
              <select onChange={(event) => setMode(event.target.value as MergeMode)} value={mode}>
                {modeOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="fa-focus-modal-field">
              <span>{isChineseUi ? "合并目标" : "Merge target"}</span>
              <select
                onChange={(event) => setTarget(event.target.value as MergeTarget)}
                value={target}
              >
                {targetOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            {shouldShowSelectedArtifacts ? (
              <label className="fa-focus-modal-field">
                <span>{isChineseUi ? "选定产物" : "Selected artifacts"}</span>
                <textarea
                  onChange={(event) => setSelectedArtifacts(event.target.value)}
                  placeholder={
                    isChineseUi
                      ? "每行输入一个 artifact 路径或 id"
                      : "Enter one artifact path or id per line"
                  }
                  value={selectedArtifacts}
                />
              </label>
            ) : null}

            <label className="fa-focus-modal-field">
              <span>{isChineseUi ? "理由" : "Rationale"}</span>
              <textarea
                onChange={(event) => setRationale(event.target.value)}
                placeholder={isChineseUi ? "可选的审阅备注" : "Optional reviewer notes"}
                value={rationale}
              />
            </label>
          </div>

          <div className="fa-focus-modal-actions">
            {onClose ? (
              <button disabled={isPreparingConclusion || isSubmitting} onClick={() => void onClose()} type="button">
                {isChineseUi ? "关闭" : "Close"}
              </button>
            ) : null}
            <button disabled={isSubmitting} onClick={() => void handleSubmit()} type="button">
              {isSubmitting
                ? isChineseUi
                  ? "提交中..."
                  : "Submitting..."
                : isChineseUi
                  ? "提交决定"
                  : "Submit decision"}
            </button>
          </div>
        </>
      )}

      {lastImported ? (
        <div className="fa-focus-modal-note is-success">
          {isChineseUi ? "已导入结论" : "Imported conclusion"}: {lastImported.summary}
        </div>
      ) : null}

      {errorMessage ? (
        <div className="fa-focus-modal-note is-danger">{errorMessage}</div>
      ) : null}
    </div>
  );
}
