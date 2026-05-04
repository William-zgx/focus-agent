import type { BranchMeta } from "@focus-agent/web-sdk";

interface ThreadHeaderActionLabelOptions {
	branchMeta?: BranchMeta | null;
	conclusionGenerationError?: string | null;
	hasPreparedConclusion: boolean;
	isChineseUi: boolean;
	isGeneratingConclusion: boolean;
	isMergedBranch: boolean;
	isReviewRoute: boolean;
	threadId: string;
}

export function statusNeedsProposal(status?: string) {
	return (
		!status ||
		(status !== "awaiting_merge_review" && status !== "preparing_merge_review")
	);
}

function mergedBranchForkDisabledLabel(isChineseUi: boolean) {
	return isChineseUi
		? "已合并分支不能新建分支"
		: "Merged branches cannot create new branches";
}

function mergedBranchConclusionDisabledLabel(isChineseUi: boolean) {
	return isChineseUi
		? "已合并分支不能生成或合并结论"
		: "Merged branches cannot generate or merge conclusions";
}

export function threadHeaderActionLabels({
	branchMeta,
	conclusionGenerationError,
	hasPreparedConclusion,
	isChineseUi,
	isGeneratingConclusion,
	isMergedBranch,
	isReviewRoute,
	threadId,
}: ThreadHeaderActionLabelOptions) {
	const defaultNewBranchTooltip = isChineseUi
		? "从当前线程创建分支"
		: "Create a branch from this thread";
	const newBranchTooltip = isMergedBranch
		? mergedBranchForkDisabledLabel(isChineseUi)
		: defaultNewBranchTooltip;
	const currentLabel =
		branchMeta?.branch_name ||
		(threadId
			? isChineseUi
				? "主线"
				: "Main"
			: isChineseUi
				? "未选择"
				: "No thread");

	if (isReviewRoute) {
		return {
			currentLabel,
			defaultNewBranchTooltip,
			newBranchTooltip,
			reviewActionText: isChineseUi ? "回到线程" : "Back to thread",
			reviewActionTooltip: isChineseUi ? "回到当前线程" : "Back to thread",
		};
	}

	if (isMergedBranch) {
		return {
			currentLabel,
			defaultNewBranchTooltip,
			newBranchTooltip,
			reviewActionText: isChineseUi ? "已合并" : "Merged",
			reviewActionTooltip: mergedBranchConclusionDisabledLabel(isChineseUi),
		};
	}

	if (isGeneratingConclusion) {
		return {
			currentLabel,
			defaultNewBranchTooltip,
			newBranchTooltip,
			reviewActionText: isChineseUi ? "生成结论中" : "Generating conclusion",
			reviewActionTooltip: isChineseUi
				? "分支结论正在生成"
				: "Conclusion is being generated",
		};
	}

	if (hasPreparedConclusion) {
		return {
			currentLabel,
			defaultNewBranchTooltip,
			newBranchTooltip,
			reviewActionText: isChineseUi ? "合并结论" : "Merge conclusion",
			reviewActionTooltip: isChineseUi
				? "打开合并结论弹窗"
				: "Open merge conclusion dialog",
		};
	}

	if (conclusionGenerationError) {
		return {
			currentLabel,
			defaultNewBranchTooltip,
			newBranchTooltip,
			reviewActionText: isChineseUi ? "重新生成结论" : "Regenerate conclusion",
			reviewActionTooltip: isChineseUi
				? "上次生成失败，重新生成分支结论"
				: "The last generation failed. Regenerate the branch conclusion.",
		};
	}

	return {
		currentLabel,
		defaultNewBranchTooltip,
		newBranchTooltip,
		reviewActionText: isChineseUi ? "生成结论" : "Generate conclusion",
		reviewActionTooltip: isChineseUi
			? "异步生成分支结论"
			: "Generate conclusion asynchronously",
	};
}
