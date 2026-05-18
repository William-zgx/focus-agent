import type { BranchTreeNode } from "@focus-agent/web-sdk";
import { useNavigate } from "@tanstack/react-router";
import type { FormEvent } from "react";
import { useCallback, useMemo, useState } from "react";

import { useShellUi } from "@/app/shell/shell-ui-context";
import {
	findNode,
	statusAccentTone,
} from "@/features/branch-tree/branch-tree-helpers";
import { useBranchActions } from "@/features/branch-tree/use-branch-actions";

type UseBranchTreeActionsOptions = {
	detailNode: BranchTreeNode | null;
	onKeepDetailOpen: () => void;
	root?: BranchTreeNode | null;
	rootThreadId: string;
	routeThreadId: string;
	selectedThreadId: string;
};

export function useBranchTreeActions({
	detailNode,
	onKeepDetailOpen,
	root,
	rootThreadId,
	routeThreadId,
	selectedThreadId,
}: UseBranchTreeActionsOptions) {
	const navigate = useNavigate();
	const [isWorking, setIsWorking] = useState(false);
	const [renameBranchTarget, setRenameBranchTarget] =
		useState<BranchTreeNode | null>(null);
	const [renameBranchDraft, setRenameBranchDraft] = useState("");
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
	const { archiveBranch, activateBranch, prepareMergeProposal, renameBranch } =
		useBranchActions({
			rootThreadId,
			threadId: selectedThreadId || routeThreadId,
		});

	const createBranchFromTarget = useCallback(
		async (targetThreadId: string, isMergedTarget: boolean) => {
			if (!targetThreadId || isMergedTarget) return;
			await createBranch({ parentThreadId: targetThreadId });
		},
		[createBranch],
	);

	const startRenameBranch = useCallback(
		(node: BranchTreeNode) => {
			if (!node.branch_id) return;
			setRenameBranchTarget(node);
			setRenameBranchDraft(node.branch_name);
			onKeepDetailOpen();
		},
		[onKeepDetailOpen],
	);

	const cancelRenameBranch = useCallback(() => {
		setRenameBranchTarget(null);
		setRenameBranchDraft("");
	}, []);

	const handleRenameBranch = useCallback(
		async (event: FormEvent<HTMLFormElement>) => {
			event.preventDefault();
			const node = renameBranchTarget;
			if (!node?.branch_id) return;
			const nextName = renameBranchDraft.trim();
			if (!nextName || nextName === node.branch_name) {
				cancelRenameBranch();
				return;
			}
			setIsWorking(true);
			try {
				await renameBranch(node.thread_id, nextName);
				cancelRenameBranch();
			} finally {
				setIsWorking(false);
			}
		},
		[cancelRenameBranch, renameBranch, renameBranchDraft, renameBranchTarget],
	);

	const handleArchiveToggle = useCallback(
		async (node: BranchTreeNode) => {
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
		},
		[activateBranch, archiveBranch],
	);

	const handleOpenMergeReview = useCallback(
		async (node: BranchTreeNode) => {
			if (!node.branch_id) return;
			await navigate({
				to: "/c/$conversationId/t/$threadId/review",
				params: {
					conversationId: node.root_thread_id,
					threadId: node.thread_id,
				},
			});
		},
		[navigate],
	);

	const handlePrepareProposal = useCallback(
		async (node: BranchTreeNode) => {
			if (
				!node.branch_id ||
				node.is_archived ||
				isMergeProposalPreparing(node.thread_id)
			)
				return;
			setIsWorking(true);
			markMergeProposalPreparing(node.thread_id);
			try {
				setShellStatus(null);
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
		},
		[
			isChineseUi,
			isMergeProposalPreparing,
			markMergeProposalFailed,
			markMergeProposalPreparing,
			markMergeProposalReady,
			prepareMergeProposal,
			setShellStatus,
		],
	);

	const getParentBranchLabel = useCallback(
		(node: BranchTreeNode) => {
			if (!node.parent_thread_id) {
				return isChineseUi ? "主线" : "Main";
			}
			const parent = findNode(root ?? undefined, node.parent_thread_id);
			return parent?.branch_name || node.parent_thread_id;
		},
		[isChineseUi, root],
	);

	const detailActionViewModel = useMemo(() => {
		const detailConclusionPreparing = detailNode
			? detailNode.branch_status === "preparing_merge_review" ||
				isMergeProposalPreparing(detailNode.thread_id)
			: false;
		const detailHasPreparedConclusion =
			detailNode?.branch_status === "awaiting_merge_review";
		const detailCanReviewConclusion = Boolean(
			detailNode?.branch_id &&
				!detailNode.is_archived &&
				!["merged", "discarded", "closed"].includes(detailNode.branch_status),
		);
		const detailConclusionError = detailNode
			? getMergeProposalError(detailNode.thread_id)
			: null;
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

		return {
			detailCanReviewConclusion,
			detailConclusionActionLabel,
			detailConclusionActionTooltip,
			detailConclusionError,
			detailConclusionPreparing,
			detailHasPreparedConclusion,
			detailNodeStatusTone: detailNode
				? statusAccentTone(detailNode.branch_status)
				: "",
		};
	}, [
		detailNode,
		getMergeProposalError,
		isChineseUi,
		isMergeProposalPreparing,
	]);

	return {
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
	};
}
