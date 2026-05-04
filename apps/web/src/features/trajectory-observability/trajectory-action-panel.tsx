import type {
	FocusAgentTrajectoryBatchPromotionPreviewResponse,
	FocusAgentTrajectoryBatchReplayCompareResponse,
	FocusAgentTrajectoryPromotionResponse,
	FocusAgentTrajectoryReplayResponse,
	FocusAgentTrajectoryTurnDetail,
	FocusAgentTrajectoryTurnSummary,
} from "@focus-agent/web-sdk";
import { useMemo, useState } from "react";

import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";
import {
	buildTrajectoryActionRequest,
	type RunningTrajectoryAction,
} from "./trajectory-action-panel-helpers";
import {
	BatchPromotionResultConsole,
	BatchReplayResultConsole,
	PromotionResultConsole,
	ReplayResultConsole,
} from "./trajectory-action-panel-results";

interface TrajectoryActionPanelProps {
	batchItems?: FocusAgentTrajectoryTurnSummary[];
	isChineseUi: boolean;
	onClearBatchSelection?: () => void;
	selected: FocusAgentTrajectoryTurnDetail | null;
}

export function TrajectoryActionPanel({
	batchItems = [],
	isChineseUi,
	onClearBatchSelection,
	selected,
}: TrajectoryActionPanelProps) {
	const { client } = useFocusAgent();
	const selectedTurnId = selected?.id ?? "";
	const batchTurnIds = useMemo(
		() => batchItems.map((item) => item.id),
		[batchItems],
	);
	const batchTurnIdsKey = batchTurnIds.join("\n");
	const hasBatchSelection = batchTurnIds.length > 0;
	const [caseIdPrefix, setCaseIdPrefix] = useState("traj");
	const [copyToolTrajectory, setCopyToolTrajectory] = useState(true);
	const [copyAnswerSubstring, setCopyAnswerSubstring] = useState(false);
	const [answerSubstringChars, setAnswerSubstringChars] = useState("160");
	const [runningAction, setRunningAction] =
		useState<RunningTrajectoryAction | null>(null);
	const [error, setError] = useState<string | null>(null);
	const [singleResultTurnId, setSingleResultTurnId] = useState(selectedTurnId);
	const [batchResultTurnIdsKey, setBatchResultTurnIdsKey] =
		useState(batchTurnIdsKey);
	const [replayResult, setReplayResult] =
		useState<FocusAgentTrajectoryReplayResponse | null>(null);
	const [promotionResult, setPromotionResult] =
		useState<FocusAgentTrajectoryPromotionResponse | null>(null);
	const [batchReplayResult, setBatchReplayResult] =
		useState<FocusAgentTrajectoryBatchReplayCompareResponse | null>(null);
	const [batchPromotionResult, setBatchPromotionResult] =
		useState<FocusAgentTrajectoryBatchPromotionPreviewResponse | null>(null);
	const [expandedReplayDetails, setExpandedReplayDetails] = useState(false);
	const [expandedPromotionDetails, setExpandedPromotionDetails] =
		useState(false);
	const [expandedBatchDetails, setExpandedBatchDetails] = useState(false);

	if (singleResultTurnId !== selectedTurnId) {
		setSingleResultTurnId(selectedTurnId);
		setReplayResult(null);
		setPromotionResult(null);
		setError(null);
		setExpandedReplayDetails(false);
		setExpandedPromotionDetails(false);
	}

	if (batchResultTurnIdsKey !== batchTurnIdsKey) {
		setBatchResultTurnIdsKey(batchTurnIdsKey);
		setBatchReplayResult(null);
		setBatchPromotionResult(null);
		setExpandedBatchDetails(false);
	}

	function getActionRequest() {
		return buildTrajectoryActionRequest({
			answerSubstringChars,
			caseIdPrefix,
			copyAnswerSubstring,
			copyToolTrajectory,
		});
	}

	async function handleReplay() {
		if (!selected) return;
		setRunningAction("replay");
		setError(null);
		try {
			const result = await client.replayTrajectoryTurn(
				selected.id,
				getActionRequest(),
			);
			setReplayResult(result);
			setExpandedReplayDetails(false);
		} catch (nextError) {
			setError(
				nextError instanceof Error
					? nextError.message
					: "Failed to replay trajectory turn.",
			);
		} finally {
			setRunningAction(null);
		}
	}

	async function handlePromote() {
		if (!selected) return;
		setRunningAction("promote");
		setError(null);
		try {
			const result = await client.promoteTrajectoryTurn(
				selected.id,
				getActionRequest(),
			);
			setPromotionResult(result);
			setExpandedPromotionDetails(false);
		} catch (nextError) {
			setError(
				nextError instanceof Error
					? nextError.message
					: "Failed to promote trajectory turn.",
			);
		} finally {
			setRunningAction(null);
		}
	}

	async function handleBatchReplayCompare() {
		if (!hasBatchSelection) return;
		setRunningAction("batchReplay");
		setError(null);
		try {
			const result = await client.batchReplayCompareTrajectoryTurns({
				turn_ids: batchTurnIds,
				...getActionRequest(),
			});
			setBatchReplayResult(result);
			setBatchPromotionResult(null);
			setExpandedBatchDetails(false);
		} catch (nextError) {
			setError(
				nextError instanceof Error
					? nextError.message
					: "Failed to compare trajectory turns.",
			);
		} finally {
			setRunningAction(null);
		}
	}

	async function handleBatchPromotePreview() {
		if (!hasBatchSelection) return;
		setRunningAction("batchPromote");
		setError(null);
		try {
			const result = await client.batchPromoteTrajectoryTurnsPreview({
				turn_ids: batchTurnIds,
				...getActionRequest(),
			});
			setBatchPromotionResult(result);
			setBatchReplayResult(null);
			setExpandedBatchDetails(false);
		} catch (nextError) {
			setError(
				nextError instanceof Error
					? nextError.message
					: "Failed to preview trajectory promotion batch.",
			);
		} finally {
			setRunningAction(null);
		}
	}

	if (!selected && !hasBatchSelection) {
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

	return (
		<div className="fa-observability-detail-block fa-trajectory-workbench-action-panel">
			<h3>{isChineseUi ? "复盘动作" : "Replay actions"}</h3>

			<p>
				{isChineseUi
					? "从当前样本直接回放，或把已勾选样本做批量治理预览。批量 promote-preview 只生成预览，不写入数据集。"
					: "Replay the selected turn directly, or run governance previews for checked turns. Batch promote-preview is non-writing."}
			</p>

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

			<div className="fa-observability-command-bar">
				<button
					className="fa-chat-toolbar-button is-primary"
					disabled={runningAction !== null}
					onClick={() => void handleReplay()}
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
					onClick={() => void handlePromote()}
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

			<div className="fa-trajectory-workbench-batch-action-panel">
				<div className="fa-trajectory-workbench-batch-action-head">
					<div>
						<span>{isChineseUi ? "批量治理" : "Batch governance"}</span>
						<strong>
							{isChineseUi
								? `${batchTurnIds.length} 条已勾选`
								: `${batchTurnIds.length} selected`}
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
						onClick={() => void handleBatchPromotePreview()}
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
						onClick={() => void handleBatchReplayCompare()}
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

			{error ? <div className="fa-inline-notice is-danger">{error}</div> : null}

			{replayResult ? (
				<ReplayResultConsole
					expanded={expandedReplayDetails}
					isChineseUi={isChineseUi}
					onExpandedChange={setExpandedReplayDetails}
					replayResult={replayResult}
				/>
			) : null}

			{promotionResult ? (
				<PromotionResultConsole
					expanded={expandedPromotionDetails}
					isChineseUi={isChineseUi}
					onExpandedChange={setExpandedPromotionDetails}
					promotionResult={promotionResult}
				/>
			) : null}

			{batchPromotionResult ? (
				<BatchPromotionResultConsole
					batchPromotionResult={batchPromotionResult}
					expanded={expandedBatchDetails}
					isChineseUi={isChineseUi}
					onExpandedChange={setExpandedBatchDetails}
				/>
			) : null}

			{batchReplayResult ? (
				<BatchReplayResultConsole
					batchReplayResult={batchReplayResult}
					expanded={expandedBatchDetails}
					isChineseUi={isChineseUi}
					onExpandedChange={setExpandedBatchDetails}
				/>
			) : null}

			{!replayResult && !promotionResult && !error ? (
				<div className="fa-inline-notice">
					{isChineseUi
						? "从当前选中的 trajectory turn 直接执行 replay，或生成一条可复制/下载的非写入 promote preview JSONL。"
						: "Run replay directly from the selected trajectory turn, or generate a copyable non-writing promote-preview JSONL."}
				</div>
			) : null}
		</div>
	);
}
