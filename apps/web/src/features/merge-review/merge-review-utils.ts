import type {
	FocusAgentApplyMergeDecisionRequest,
	FocusAgentMergeProposal,
	MergeMode,
	MergeTarget,
} from "@focus-agent/web-sdk";

export type MergeReviewDecision = "approve" | "reject";

export type MergeReviewDraft = {
	artifacts: string;
	decision: MergeReviewDecision;
	evidenceRefs: string;
	findings: string;
	mode: MergeMode;
	openQuestions: string;
	rationale: string;
	selectedArtifacts: string;
	summary: string;
	target: MergeTarget;
};

export function parseLineList(value: string) {
	return value
		.split("\n")
		.map((item) => item.trim())
		.filter(Boolean);
}

export function modeOptionLabel(value: MergeMode, isChineseUi: boolean) {
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

export function targetOptionLabel(value: MergeTarget, isChineseUi: boolean) {
	switch (value) {
		case "return_thread":
			return isChineseUi ? "返回上游" : "Return upstream";
		case "root_thread":
			return isChineseUi ? "主分支" : "Main branch";
		default:
			return value;
	}
}

export function recommendedImportModeLabel(
	value: MergeMode | undefined,
	isChineseUi: boolean,
) {
	return isChineseUi
		? `推荐导入方式：${modeOptionLabel(value ?? "summary_only", true)}`
		: `Recommended import mode: ${modeOptionLabel(value ?? "summary_only", false)}`;
}

export function mergeReviewStatusLabel(
	status: string | undefined,
	isChineseUi: boolean,
) {
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

export function mergedBranchReadOnlyLabel(isChineseUi: boolean) {
	return isChineseUi
		? "已合并分支不能继续生成或合并结论。"
		: "Merged branches cannot generate or merge conclusions.";
}

export function createMergeReviewDraft(
	proposal?: FocusAgentMergeProposal | null,
): MergeReviewDraft {
	const recommendedMode = proposal?.recommended_import_mode;
	const defaultMode =
		recommendedMode && recommendedMode !== "none"
			? recommendedMode
			: "summary_only";
	return {
		artifacts: (proposal?.artifacts ?? []).join("\n"),
		decision: "approve",
		evidenceRefs: (proposal?.evidence_refs ?? []).join("\n"),
		findings: (proposal?.key_findings ?? []).join("\n"),
		mode: defaultMode,
		openQuestions: (proposal?.open_questions ?? []).join("\n"),
		rationale: "",
		selectedArtifacts: "",
		summary: proposal?.summary ?? "",
		target: "return_thread",
	};
}

export function createMergeReviewPayload(
	draft: MergeReviewDraft,
): FocusAgentApplyMergeDecisionRequest {
	const shouldShowSelectedArtifacts =
		draft.decision === "approve" && draft.mode === "selected_artifacts";
	return {
		approved: draft.decision === "approve",
		mode: draft.mode,
		target: draft.target,
		rationale: draft.rationale.trim() || undefined,
		selected_artifacts: shouldShowSelectedArtifacts
			? parseLineList(draft.selectedArtifacts)
			: undefined,
		proposal_overrides: {
			summary: draft.summary.trim() || null,
			key_findings: parseLineList(draft.findings),
			open_questions: parseLineList(draft.openQuestions),
			evidence_refs: parseLineList(draft.evidenceRefs),
			artifacts: parseLineList(draft.artifacts),
			recommended_import_mode: draft.mode,
		},
	};
}
