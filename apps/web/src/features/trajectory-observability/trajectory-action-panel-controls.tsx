import type { RunningTrajectoryAction } from "./trajectory-action-panel-helpers";

export function TrajectoryActionPanelEmptyState({
	isChineseUi,
}: {
	isChineseUi: boolean;
}) {
	return (
		<div className="fa-observability-detail-block fa-trajectory-workbench-action-panel">
			<h3>{isChineseUi ? "复盘动作" : "Replay actions"}</h3>
			<div className="fa-observability-empty">
				{isChineseUi
					? "选择一条 turn 后可单条 replay；勾选多条后可做批量治理预览。"
					: "Select a turn for single replay, or tick multiple turns for batch governance previews."}
			</div>
		</div>
	);
}

export function TrajectoryActionOptionsForm({
	answerSubstringChars,
	caseIdPrefix,
	copyAnswerSubstring,
	copyToolTrajectory,
	isChineseUi,
	setAnswerSubstringChars,
	setCaseIdPrefix,
	setCopyAnswerSubstring,
	setCopyToolTrajectory,
}: {
	answerSubstringChars: string;
	caseIdPrefix: string;
	copyAnswerSubstring: boolean;
	copyToolTrajectory: boolean;
	isChineseUi: boolean;
	setAnswerSubstringChars: (value: string) => void;
	setCaseIdPrefix: (value: string) => void;
	setCopyAnswerSubstring: (value: boolean) => void;
	setCopyToolTrajectory: (value: boolean) => void;
}) {
	return (
		<>
			<div className="fa-observability-action-grid">
				<label className="fa-observability-action-option">
					<span>{isChineseUi ? "Case 前缀" : "Case prefix"}</span>
					<input
						onChange={(event) => setCaseIdPrefix(event.target.value)}
						placeholder="traj"
						value={caseIdPrefix}
					/>
				</label>
				<label className="fa-observability-action-option">
					<span>{isChineseUi ? "答案锚点长度" : "Answer anchor chars"}</span>
					<input
						inputMode="numeric"
						onChange={(event) => setAnswerSubstringChars(event.target.value)}
						placeholder="160"
						value={answerSubstringChars}
					/>
				</label>
			</div>

			<div className="fa-observability-action-toggles">
				<label className="fa-observability-action-toggle">
					<input
						checked={copyToolTrajectory}
						onChange={(event) => setCopyToolTrajectory(event.target.checked)}
						type="checkbox"
					/>
					<span>
						{isChineseUi ? "拷贝工具轨迹约束" : "Copy tool-path expectations"}
					</span>
				</label>
				<label className="fa-observability-action-toggle">
					<input
						checked={copyAnswerSubstring}
						onChange={(event) => setCopyAnswerSubstring(event.target.checked)}
						type="checkbox"
					/>
					<span>
						{isChineseUi ? "拷贝答案片段锚点" : "Copy answer substring anchor"}
					</span>
				</label>
			</div>
		</>
	);
}

export function TrajectorySingleActionControls({
	isChineseUi,
	onPromote,
	onReplay,
	runningAction,
}: {
	isChineseUi: boolean;
	onPromote: () => void;
	onReplay: () => void;
	runningAction: RunningTrajectoryAction | null;
}) {
	return (
		<div className="fa-observability-command-bar">
			<button
				className="fa-chat-toolbar-button is-primary"
				disabled={runningAction !== null}
				onClick={onReplay}
				type="button"
			>
				{runningAction === "replay"
					? isChineseUi
						? "Replay 中..."
						: "Replaying..."
					: isChineseUi
						? "执行 Replay"
						: "Run replay"}
			</button>
			<button
				className="fa-chat-toolbar-button"
				disabled={runningAction !== null}
				onClick={onPromote}
				type="button"
			>
				{runningAction === "promote"
					? isChineseUi
						? "生成中..."
						: "Promoting..."
					: isChineseUi
						? "生成评测样本预览（不写入）"
						: "Preview eval sample (non-writing)"}
			</button>
		</div>
	);
}

export function TrajectoryBatchActionControls({
	hasBatchSelection,
	isChineseUi,
	onBatchPromotePreview,
	onBatchReplayCompare,
	onClearBatchSelection,
	runningAction,
	selectedCount,
}: {
	hasBatchSelection: boolean;
	isChineseUi: boolean;
	onBatchPromotePreview: () => void;
	onBatchReplayCompare: () => void;
	onClearBatchSelection?: () => void;
	runningAction: RunningTrajectoryAction | null;
	selectedCount: number;
}) {
	return (
		<div className="fa-trajectory-workbench-batch-action-panel">
			<div className="fa-trajectory-workbench-batch-action-head">
				<div>
					<span>{isChineseUi ? "批量治理" : "Batch governance"}</span>
					<strong>
						{isChineseUi
							? `${selectedCount} 条已勾选`
							: `${selectedCount} selected`}
					</strong>
				</div>
				{hasBatchSelection && onClearBatchSelection ? (
					<button
						className="fa-chat-toolbar-button"
						onClick={onClearBatchSelection}
						type="button"
					>
						{isChineseUi ? "清空" : "Clear"}
					</button>
				) : null}
			</div>
			<p>
				{isChineseUi
					? "Promote-preview 是非写入操作：只返回可复制的 dataset skeleton，不会落库或修改评测集。Replay-compare 会逐条回放并返回差异。"
					: "Promote-preview is non-writing: it only returns copyable dataset skeletons and does not persist or modify an eval set. Replay-compare replays each selected turn and returns diffs."}
			</p>
			<div className="fa-observability-command-bar">
				<button
					className="fa-chat-toolbar-button"
					disabled={!hasBatchSelection || runningAction !== null}
					onClick={onBatchPromotePreview}
					type="button"
				>
					{runningAction === "batchPromote"
						? isChineseUi
							? "批量预览中..."
							: "Previewing..."
						: isChineseUi
							? "批量 Promote 预览（不写入）"
							: "Batch promote-preview (non-writing)"}
				</button>
				<button
					className="fa-chat-toolbar-button"
					disabled={!hasBatchSelection || runningAction !== null}
					onClick={onBatchReplayCompare}
					type="button"
				>
					{runningAction === "batchReplay"
						? isChineseUi
							? "批量对比中..."
							: "Comparing..."
						: isChineseUi
							? "批量 Replay 对比"
							: "Batch replay-compare"}
				</button>
			</div>
		</div>
	);
}

export function TrajectoryActionIdleNotice({
	isChineseUi,
}: {
	isChineseUi: boolean;
}) {
	return (
		<div className="fa-inline-notice">
			{isChineseUi
				? "从当前选中的 trajectory turn 直接执行 replay，或生成一条可复制/下载的非写入 promote preview JSONL。"
				: "Run replay directly from the selected trajectory turn, or generate a copyable non-writing promote-preview JSONL."}
		</div>
	);
}
