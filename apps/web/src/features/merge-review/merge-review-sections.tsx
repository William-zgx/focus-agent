import type {
	FocusAgentMergeProposal,
	MergeMode,
	MergeTarget,
} from "@focus-agent/web-sdk";

import type {
	MergeReviewDecision,
	MergeReviewDraft,
} from "./merge-review-utils";
import {
	mergeReviewStatusLabel,
	modeOptionLabel,
	recommendedImportModeLabel,
	targetOptionLabel,
} from "./merge-review-utils";

type MergeReviewDraftField = keyof MergeReviewDraft;

function updateDraftField<K extends MergeReviewDraftField>(
	onDraftChange: (
		next: (current: MergeReviewDraft) => MergeReviewDraft,
	) => void,
	field: K,
	value: MergeReviewDraft[K],
) {
	onDraftChange((current) => ({ ...current, [field]: value }));
}

function MergeReviewTextSection({
	field,
	isChineseUi,
	labelEn,
	labelZh,
	onDraftChange,
	placeholderEn,
	placeholderZh,
	value,
}: {
	field: Extract<
		MergeReviewDraftField,
		"artifacts" | "evidenceRefs" | "findings" | "openQuestions" | "summary"
	>;
	isChineseUi: boolean;
	labelEn: string;
	labelZh: string;
	onDraftChange: (
		next: (current: MergeReviewDraft) => MergeReviewDraft,
	) => void;
	placeholderEn: string;
	placeholderZh: string;
	value: string;
}) {
	return (
		<div className="fa-focus-modal-section">
			<h4>{isChineseUi ? labelZh : labelEn}</h4>
			<label className="fa-focus-modal-field">
				<span>{isChineseUi ? labelZh : labelEn}</span>
				<textarea
					onChange={(event) =>
						updateDraftField(onDraftChange, field, event.target.value)
					}
					placeholder={isChineseUi ? placeholderZh : placeholderEn}
					value={value}
				/>
			</label>
		</div>
	);
}

export function MergeReviewLoadingState({
	isChineseUi,
	isMergedBranch,
	isPreparingConclusion,
	onPrepareProposal,
}: {
	isChineseUi: boolean;
	isMergedBranch: boolean;
	isPreparingConclusion: boolean;
	onPrepareProposal: () => void;
}) {
	return (
		<div className="fa-focus-modal-loading">
			<strong>
				{isChineseUi ? "正在准备合并提案..." : "Preparing merge proposal..."}
			</strong>
			<p>
				{isChineseUi
					? "这可能需要一点时间来生成分支总结。"
					: "This can take a moment while the branch summary is prepared."}
			</p>
			<div className="fa-focus-modal-actions">
				<button
					disabled={isPreparingConclusion || isMergedBranch}
					onClick={onPrepareProposal}
					type="button"
				>
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
	);
}

export function MergeReviewProposalForm({
	branchName,
	draft,
	isChineseUi,
	isMergedBranch,
	isPreparingConclusion,
	isSubmitting,
	modeOptions,
	onClose,
	onDraftChange,
	onSubmit,
	pendingStatus,
	proposal,
	targetOptions,
}: {
	branchName?: string;
	draft: MergeReviewDraft;
	isChineseUi: boolean;
	isMergedBranch: boolean;
	isPreparingConclusion: boolean;
	isSubmitting: boolean;
	modeOptions: Array<{ label: string; value: MergeMode }>;
	onClose?: () => void | Promise<void>;
	onDraftChange: (
		next: (current: MergeReviewDraft) => MergeReviewDraft,
	) => void;
	onSubmit: () => void;
	pendingStatus?: string;
	proposal: FocusAgentMergeProposal;
	targetOptions: Array<{ label: string; value: MergeTarget }>;
}) {
	const shouldShowSelectedArtifacts =
		draft.decision === "approve" && draft.mode === "selected_artifacts";

	return (
		<>
			{branchName || pendingStatus ? (
				<div className="fa-focus-modal-note">
					{branchName
						? `${isChineseUi ? "分支" : "Branch"}: ${branchName}`
						: null}
					{branchName && pendingStatus ? " · " : null}
					{pendingStatus
						? `${isChineseUi ? "状态" : "Status"}: ${mergeReviewStatusLabel(
								pendingStatus,
								isChineseUi,
							)}`
						: null}
				</div>
			) : null}
			<MergeReviewTextSection
				field="summary"
				isChineseUi={isChineseUi}
				labelEn="Summary"
				labelZh="摘要"
				onDraftChange={onDraftChange}
				placeholderEn="Edit the summary before merging"
				placeholderZh="可在合并前修改这段摘要"
				value={draft.summary}
			/>
			<MergeReviewTextSection
				field="findings"
				isChineseUi={isChineseUi}
				labelEn="Key findings"
				labelZh="关键发现"
				onDraftChange={onDraftChange}
				placeholderEn="One finding per line"
				placeholderZh="每行输入一条关键结论"
				value={draft.findings}
			/>
			<MergeReviewTextSection
				field="openQuestions"
				isChineseUi={isChineseUi}
				labelEn="Open questions"
				labelZh="开放问题"
				onDraftChange={onDraftChange}
				placeholderEn="One open question per line"
				placeholderZh="每行输入一条开放问题"
				value={draft.openQuestions}
			/>
			<MergeReviewTextSection
				field="evidenceRefs"
				isChineseUi={isChineseUi}
				labelEn="Evidence refs"
				labelZh="证据引用"
				onDraftChange={onDraftChange}
				placeholderEn="One evidence ref per line"
				placeholderZh="每行输入一条证据引用"
				value={draft.evidenceRefs}
			/>
			<MergeReviewTextSection
				field="artifacts"
				isChineseUi={isChineseUi}
				labelEn="Artifacts"
				labelZh="产物"
				onDraftChange={onDraftChange}
				placeholderEn="One artifact path or id per line"
				placeholderZh="每行输入一个 artifact 路径或 id"
				value={draft.artifacts}
			/>

			<div className="fa-focus-modal-note">
				{recommendedImportModeLabel(
					proposal.recommended_import_mode,
					isChineseUi,
				)}
			</div>

			<div className="fa-focus-modal-form">
				<label className="fa-focus-modal-field">
					<span>{isChineseUi ? "决定" : "Decision"}</span>
					<select
						onChange={(event) =>
							updateDraftField(
								onDraftChange,
								"decision",
								event.target.value as MergeReviewDecision,
							)
						}
						value={draft.decision}
					>
						<option value="approve">{isChineseUi ? "批准" : "Approve"}</option>
						<option value="reject">{isChineseUi ? "拒绝" : "Reject"}</option>
					</select>
				</label>

				<label className="fa-focus-modal-field">
					<span>{isChineseUi ? "导入方式" : "Import mode"}</span>
					<select
						onChange={(event) =>
							updateDraftField(
								onDraftChange,
								"mode",
								event.target.value as MergeMode,
							)
						}
						value={draft.mode}
					>
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
						onChange={(event) =>
							updateDraftField(
								onDraftChange,
								"target",
								event.target.value as MergeTarget,
							)
						}
						value={draft.target}
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
							onChange={(event) =>
								updateDraftField(
									onDraftChange,
									"selectedArtifacts",
									event.target.value,
								)
							}
							placeholder={
								isChineseUi
									? "每行输入一个 artifact 路径或 id"
									: "Enter one artifact path or id per line"
							}
							value={draft.selectedArtifacts}
						/>
					</label>
				) : null}

				<label className="fa-focus-modal-field">
					<span>{isChineseUi ? "理由" : "Rationale"}</span>
					<textarea
						onChange={(event) =>
							updateDraftField(onDraftChange, "rationale", event.target.value)
						}
						placeholder={
							isChineseUi ? "可选的审阅备注" : "Optional reviewer notes"
						}
						value={draft.rationale}
					/>
				</label>
			</div>

			<div className="fa-focus-modal-actions">
				{onClose ? (
					<button
						disabled={isPreparingConclusion || isSubmitting}
						onClick={() => void onClose()}
						type="button"
					>
						{isChineseUi ? "关闭" : "Close"}
					</button>
				) : null}
				<button
					disabled={isSubmitting || isMergedBranch}
					onClick={onSubmit}
					type="button"
				>
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
	);
}

export function createModeOptions(isChineseUi: boolean) {
	return (
		[
			"summary_only",
			"summary_plus_evidence",
			"selected_artifacts",
		] as MergeMode[]
	).map((value) => ({
		value,
		label: modeOptionLabel(value, isChineseUi),
	}));
}

export function createTargetOptions(isChineseUi: boolean) {
	return (["return_thread", "root_thread"] as MergeTarget[]).map((value) => ({
		value,
		label: targetOptionLabel(value, isChineseUi),
	}));
}
