import { useNavigate, useRouterState } from "@tanstack/react-router";
import { type FormEvent, useEffect, useRef, useState } from "react";

import type {
	HeaderRenameScope,
	HeaderRenameScopeSetter,
} from "@/app/shell/app-shell-chat-header";
import { useShellUi } from "@/app/shell/shell-ui-context";
import { useBranchActions } from "@/features/branch-tree/use-branch-actions";
import { ThreadHeaderActionButtons } from "@/features/thread/thread-header-action-buttons";
import {
	statusNeedsProposal,
	threadHeaderActionLabels,
} from "@/features/thread/thread-header-action-labels";
import { useThreadHeaderCompact } from "@/features/thread/use-thread-header-compact";
import { useThreadState } from "@/features/thread/use-thread-state";

interface ThreadHeaderActionsProps {
	activeRenameScope?: HeaderRenameScope;
	onRenameScopeChange?: HeaderRenameScopeSetter;
	onRequestOpenSidebar?: () => void;
}

export function ThreadHeaderActions({
	activeRenameScope,
	onRenameScopeChange,
	onRequestOpenSidebar,
}: ThreadHeaderActionsProps) {
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
	const { prepareMergeProposal, renameBranch } = useBranchActions({
		rootThreadId: conversationId,
		threadId,
	});
	const [isWorking, setIsWorking] = useState(false);
	const [isRenamingCurrentBranch, setIsRenamingCurrentBranch] = useState(false);
	const [renameBranchDraft, setRenameBranchDraft] = useState("");
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
		Boolean(data?.merge_proposal) ||
		branchMeta?.branch_status === "awaiting_merge_review";
	const isBranchRenameVisible =
		isRenamingCurrentBranch &&
		(activeRenameScope === undefined || activeRenameScope === "branch");
	const conclusionGenerationError = threadId
		? getMergeProposalError(threadId)
		: null;
	const labels = threadHeaderActionLabels({
		branchMeta,
		conclusionGenerationError,
		hasPreparedConclusion,
		isChineseUi,
		isGeneratingConclusion,
		isMergedBranch,
		isReviewRoute,
		threadId,
	});

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

	useThreadHeaderCompact(actionsRef, [
		branchMeta?.branch_id,
		branchMeta?.branch_name,
		branchMeta?.parent_thread_id,
		branchMeta?.branch_status,
		conversationId,
		isChineseUi,
		isReviewRoute,
		isWorking,
		isBranchRenameVisible,
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
		if (!isReviewRoute && isMergedBranch) return;
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

	function handleRenameCurrentBranch() {
		if (!branchMeta?.branch_id || !threadId || isWorking) return;
		onRenameScopeChange?.("branch");
		setRenameBranchDraft(branchMeta.branch_name || "");
		setIsRenamingCurrentBranch(true);
	}

	function cancelRenameCurrentBranch() {
		setIsRenamingCurrentBranch(false);
		setRenameBranchDraft("");
		onRenameScopeChange?.((currentScope) =>
			currentScope === "branch" ? null : currentScope,
		);
	}

	useEffect(() => {
		if (
			isRenamingCurrentBranch &&
			activeRenameScope !== undefined &&
			activeRenameScope !== "branch"
		) {
			setIsRenamingCurrentBranch(false);
			setRenameBranchDraft("");
		}
	}, [activeRenameScope, isRenamingCurrentBranch]);

	async function handleRenameCurrentBranchSubmit(
		event: FormEvent<HTMLFormElement>,
	) {
		event.preventDefault();
		if (!branchMeta?.branch_id || !threadId) return;
		if (!isBranchRenameVisible) {
			cancelRenameCurrentBranch();
			return;
		}
		const nextName = renameBranchDraft.trim();
		if (!nextName) return;
		setIsWorking(true);
		try {
			await renameBranch(threadId, nextName);
			cancelRenameCurrentBranch();
		} finally {
			setIsWorking(false);
		}
	}

	return (
		<ThreadHeaderActionButtons
			actionsRef={actionsRef}
			branchMeta={branchMeta}
			conclusionGenerationError={conclusionGenerationError}
			conversationId={conversationId}
			currentLabel={labels.currentLabel}
			defaultNewBranchTooltip={labels.defaultNewBranchTooltip}
			hasPreparedConclusion={hasPreparedConclusion}
			isChineseUi={isChineseUi}
			isCreatingBranch={isCreatingBranch}
			isGeneratingConclusion={isGeneratingConclusion}
			isMergedBranch={isMergedBranch}
			isRenamingCurrentBranch={isBranchRenameVisible}
			isReviewRoute={isReviewRoute}
			isWorking={isWorking}
			newBranchTooltip={labels.newBranchTooltip}
			onBackMain={() => void handleBackMain()}
			onBackParent={() => void handleBackParent()}
			onCancelRenameCurrentBranch={cancelRenameCurrentBranch}
			onFocusBranchPanel={focusBranchPanel}
			onForkBranch={() => void handleForkBranch()}
			onRenameCurrentBranch={handleRenameCurrentBranch}
			onRenameCurrentBranchDraftChange={setRenameBranchDraft}
			onRenameCurrentBranchSubmit={(event) =>
				void handleRenameCurrentBranchSubmit(event)
			}
			onReviewAction={() => void handleReviewAction()}
			renameCurrentBranchDraft={renameBranchDraft}
			reviewActionText={labels.reviewActionText}
			reviewActionTooltip={labels.reviewActionTooltip}
			threadId={threadId}
		/>
	);
}
