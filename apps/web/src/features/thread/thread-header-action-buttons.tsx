import type { BranchMeta } from "@focus-agent/web-sdk";
import {
	type FormEvent,
	type RefObject,
	useEffect,
	useId,
	useRef,
} from "react";

import {
	BackToMainIcon,
	BackToParentIcon,
	BackToThreadIcon,
	BranchFocusIcon,
	BranchPlusIcon,
	ConclusionDraftIcon,
	ConclusionReadyIcon,
	RefreshConclusionIcon,
} from "@/shared/ui/toolbar-icons";
import { tooltipProps } from "@/shared/ui/tooltip";

interface ThreadHeaderActionButtonsProps {
	actionsRef: RefObject<HTMLDivElement | null>;
	branchMeta?: BranchMeta | null;
	conclusionGenerationError?: string | null;
	conversationId: string;
	currentLabel: string;
	defaultNewBranchTooltip: string;
	hasPreparedConclusion: boolean;
	isChineseUi: boolean;
	isCreatingBranch: boolean;
	isGeneratingConclusion: boolean;
	isMergedBranch: boolean;
	isRenamingCurrentBranch: boolean;
	isReviewRoute: boolean;
	isWorking: boolean;
	newBranchTooltip: string;
	onBackMain: () => void;
	onBackParent: () => void;
	onCancelRenameCurrentBranch: () => void;
	onFocusBranchPanel: () => void;
	onForkBranch: () => void;
	onRenameCurrentBranch: () => void;
	onRenameCurrentBranchDraftChange: (value: string) => void;
	onRenameCurrentBranchSubmit: (event: FormEvent<HTMLFormElement>) => void;
	onReviewAction: () => void;
	renameCurrentBranchDraft: string;
	reviewActionText: string;
	reviewActionTooltip: string;
	threadId: string;
}

function ReviewActionIcon({
	conclusionGenerationError,
	hasPreparedConclusion,
	isReviewRoute,
}: Pick<
	ThreadHeaderActionButtonsProps,
	"conclusionGenerationError" | "hasPreparedConclusion" | "isReviewRoute"
>) {
	if (isReviewRoute) {
		return <BackToThreadIcon />;
	}

	if (hasPreparedConclusion) {
		return <ConclusionReadyIcon />;
	}

	if (conclusionGenerationError) {
		return <RefreshConclusionIcon />;
	}

	return <ConclusionDraftIcon />;
}

export function ThreadHeaderActionButtons({
	actionsRef,
	branchMeta,
	conclusionGenerationError,
	conversationId,
	currentLabel,
	defaultNewBranchTooltip,
	hasPreparedConclusion,
	isChineseUi,
	isCreatingBranch,
	isGeneratingConclusion,
	isMergedBranch,
	isRenamingCurrentBranch,
	isReviewRoute,
	isWorking,
	newBranchTooltip,
	onBackMain,
	onBackParent,
	onCancelRenameCurrentBranch,
	onFocusBranchPanel,
	onForkBranch,
	onRenameCurrentBranch,
	onRenameCurrentBranchDraftChange,
	onRenameCurrentBranchSubmit,
	onReviewAction,
	renameCurrentBranchDraft,
	reviewActionText,
	reviewActionTooltip,
	threadId,
}: ThreadHeaderActionButtonsProps) {
	const renameInputId = useId();
	const renameInputRef = useRef<HTMLInputElement | null>(null);

	useEffect(() => {
		if (isRenamingCurrentBranch) {
			renameInputRef.current?.focus();
		}
	}, [isRenamingCurrentBranch]);

	return (
		<div ref={actionsRef} className="fa-chat-header-actions">
			<div className="fa-chat-header-primary-actions">
				{isRenamingCurrentBranch ? (
					<form
						className="fa-inline-rename-form is-header-branch"
						onSubmit={onRenameCurrentBranchSubmit}
					>
						<label className="sr-only" htmlFor={renameInputId}>
							{isChineseUi ? "重命名当前分支" : "Rename current branch"}
						</label>
						<input
							id={renameInputId}
							ref={renameInputRef}
							className="fa-inline-rename-input"
							disabled={isWorking}
							onChange={(event) =>
								onRenameCurrentBranchDraftChange(event.target.value)
							}
							value={renameCurrentBranchDraft}
						/>
						<button
							className="fa-branch-inline-action is-primary"
							disabled={isWorking || !renameCurrentBranchDraft.trim()}
							type="submit"
						>
							{isChineseUi ? "保存" : "Save"}
						</button>
						<button
							className="fa-branch-inline-action"
							disabled={isWorking}
							onClick={onCancelRenameCurrentBranch}
							type="button"
						>
							{isChineseUi ? "取消" : "Cancel"}
						</button>
					</form>
				) : (
					<button
						className="fa-chat-toolbar-pill fa-focus-branches-button"
						data-compact-button="true"
						data-full-label={`${isChineseUi ? "当前分支" : "current"}: ${currentLabel}`}
						{...tooltipProps(
							branchMeta?.branch_id
								? isChineseUi
									? "定位左侧分支树；双击可重命名当前分支"
									: "Focus branches; double-click to rename the current branch"
								: isChineseUi
									? "定位左侧分支树"
									: "Focus branches",
							{
								defaultTooltip: isChineseUi
									? "定位左侧分支树"
									: "Focus branches",
							},
						)}
						aria-label={`${isChineseUi ? "当前分支" : "current"}: ${currentLabel}`}
						onClick={onFocusBranchPanel}
						onDoubleClick={onRenameCurrentBranch}
						type="button"
					>
						<span className="fa-toolbar-icon" aria-hidden="true">
							<BranchFocusIcon />
						</span>
						<span className="fa-toolbar-text">
							{isChineseUi ? "当前分支" : "current"}: {currentLabel}
						</span>
					</button>
				)}

				<button
					className="fa-chat-toolbar-button is-primary fa-new-branch-button"
					data-compact-button="true"
					data-full-label={isChineseUi ? "新建分支" : "New branch"}
					{...tooltipProps(newBranchTooltip, {
						defaultTooltip: defaultNewBranchTooltip,
					})}
					aria-label={isChineseUi ? "新建分支" : "New branch"}
					disabled={!threadId || isMergedBranch || isCreatingBranch}
					onClick={onForkBranch}
					type="button"
				>
					<span className="fa-toolbar-icon" aria-hidden="true">
						<BranchPlusIcon />
					</span>
					<span className="fa-toolbar-text">
						{isChineseUi ? "新建分支" : "New branch"}
					</span>
				</button>

				{branchMeta ? (
					<button
						className="fa-chat-toolbar-button fa-review-button"
						data-compact-button="true"
						data-full-label={reviewActionText}
						{...tooltipProps(reviewActionTooltip, {
							defaultTooltip: reviewActionTooltip,
						})}
						disabled={
							isWorking ||
							(!isReviewRoute && (isGeneratingConclusion || isMergedBranch))
						}
						onClick={onReviewAction}
						type="button"
						aria-label={reviewActionText}
					>
						<span className="fa-toolbar-icon" aria-hidden="true">
							<ReviewActionIcon
								conclusionGenerationError={conclusionGenerationError}
								hasPreparedConclusion={hasPreparedConclusion}
								isReviewRoute={isReviewRoute}
							/>
						</span>
						<span className="fa-toolbar-text">{reviewActionText}</span>
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
							onClick={onBackMain}
							type="button"
						>
							<span className="fa-toolbar-icon" aria-hidden="true">
								<BackToMainIcon />
							</span>
							<span className="fa-toolbar-text">
								{isChineseUi ? "回到主分支" : "Back to main"}
							</span>
						</button>
					) : null}
					{branchMeta.parent_thread_id &&
					branchMeta.parent_thread_id !== conversationId ? (
						<button
							className="fa-chat-toolbar-button fa-back-parent-button"
							data-compact-button="true"
							data-full-label={isChineseUi ? "回到上一层" : "Back one level"}
							{...tooltipProps(
								isChineseUi ? "回到父分支线程" : "Back one level",
								{
									defaultTooltip: isChineseUi
										? "回到父分支线程"
										: "Back one level",
								},
							)}
							aria-label={isChineseUi ? "回到上一层" : "Back one level"}
							onClick={onBackParent}
							type="button"
						>
							<span className="fa-toolbar-icon" aria-hidden="true">
								<BackToParentIcon />
							</span>
							<span className="fa-toolbar-text">
								{isChineseUi ? "回到上一层" : "Back one level"}
							</span>
						</button>
					) : null}
				</div>
			) : null}
		</div>
	);
}
