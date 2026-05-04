import type {
	FocusAgentImportedConclusion,
	FocusAgentMergeProposal,
} from "@focus-agent/web-sdk";
import { useNavigate } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";

import { useShellUi } from "@/app/shell/shell-ui-context";
import { useBranchActions } from "@/features/branch-tree/use-branch-actions";

import {
	createModeOptions,
	createTargetOptions,
	MergeReviewLoadingState,
	MergeReviewProposalForm,
} from "./merge-review-sections";
import {
	createMergeReviewDraft,
	createMergeReviewPayload,
	type MergeReviewDraft,
	mergedBranchReadOnlyLabel,
} from "./merge-review-utils";

interface MergeReviewCardProps {
	rootThreadId: string;
	threadId: string;
	proposal?: FocusAgentMergeProposal | null;
	branchName?: string;
	pendingStatus?: string;
	onClose?: () => void | Promise<void>;
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
	const [draft, setDraft] = useState(() => createMergeReviewDraft(proposal));
	const [lastImported, setLastImported] =
		useState<FocusAgentImportedConclusion | null>(null);
	const [errorMessage, setErrorMessage] = useState<string | null>(null);
	const proposalSignature = proposal ? JSON.stringify(proposal) : "no-proposal";
	const isPreparingConclusion = isPreparing || isMergeProposalPreparing(threadId);
	const isMergedBranch = pendingStatus === "merged";

	const modeOptions = useMemo(
		() => createModeOptions(isChineseUi),
		[isChineseUi],
	);
	const targetOptions = useMemo(
		() => createTargetOptions(isChineseUi),
		[isChineseUi],
	);

	useEffect(() => {
		setDraft(createMergeReviewDraft(proposal));
		setLastImported(null);
		setErrorMessage(null);
	}, [threadId, proposalSignature, proposal]);

	function handleDraftChange(
		next: (current: MergeReviewDraft) => MergeReviewDraft,
	) {
		setDraft(next);
	}

	async function handlePrepareProposal() {
		if (isMergedBranch) {
			setErrorMessage(mergedBranchReadOnlyLabel(isChineseUi));
			return;
		}
		setIsPreparing(true);
		markMergeProposalPreparing(threadId);
		setErrorMessage(null);
		try {
			const nextProposal = await prepareMergeProposal(threadId);
			markMergeProposalReady(threadId);
			setDraft(createMergeReviewDraft(nextProposal));
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
		if (isMergedBranch) {
			setErrorMessage(mergedBranchReadOnlyLabel(isChineseUi));
			return;
		}

		setIsSubmitting(true);
		setErrorMessage(null);
		try {
			const response = await applyMergeDecision(
				threadId,
				createMergeReviewPayload(draft),
			);
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
			{proposal ? (
				<MergeReviewProposalForm
					branchName={branchName}
					draft={draft}
					isChineseUi={isChineseUi}
					isMergedBranch={isMergedBranch}
					isPreparingConclusion={isPreparingConclusion}
					isSubmitting={isSubmitting}
					modeOptions={modeOptions}
					onClose={onClose}
					onDraftChange={handleDraftChange}
					onSubmit={() => void handleSubmit()}
					pendingStatus={pendingStatus}
					proposal={proposal}
					targetOptions={targetOptions}
				/>
			) : (
				<MergeReviewLoadingState
					isChineseUi={isChineseUi}
					isMergedBranch={isMergedBranch}
					isPreparingConclusion={isPreparingConclusion}
					onPrepareProposal={() => void handlePrepareProposal()}
				/>
			)}

			{lastImported ? (
				<div className="fa-focus-modal-note is-success">
					{isChineseUi ? "已导入结论" : "Imported conclusion"}:{" "}
					{lastImported.summary}
				</div>
			) : null}

			{errorMessage ? (
				<div className="fa-focus-modal-note is-danger">{errorMessage}</div>
			) : null}
		</div>
	);
}
