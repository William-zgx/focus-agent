import type {
	FocusAgentTrajectoryTurnDetail,
	FocusAgentTrajectoryTurnSummary,
} from "@focus-agent/web-sdk";
import { useMemo } from "react";

import {
	TrajectoryActionIdleNotice,
	TrajectoryActionOptionsForm,
	TrajectoryActionPanelEmptyState,
	TrajectoryBatchActionControls,
	TrajectorySingleActionControls,
} from "./trajectory-action-panel-controls";
import {
	BatchPromotionResultConsole,
	BatchReplayResultConsole,
	PromotionResultConsole,
	ReplayResultConsole,
} from "./trajectory-action-panel-results";
import { useTrajectoryActionPanelState } from "./use-trajectory-action-panel-state";

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
	const batchTurnIds = useMemo(
		() => batchItems.map((item) => item.id),
		[batchItems],
	);
	const hasBatchSelection = batchTurnIds.length > 0;
	const actionState = useTrajectoryActionPanelState({
		batchTurnIds,
		hasBatchSelection,
		selected,
	});

	if (!selected && !hasBatchSelection) {
		return <TrajectoryActionPanelEmptyState isChineseUi={isChineseUi} />;
	}

	return (
		<div className="fa-observability-detail-block fa-trajectory-workbench-action-panel">
			<h3>{isChineseUi ? "复盘动作" : "Replay actions"}</h3>

			<p>
				{isChineseUi
					? "从当前样本直接回放，或把已勾选样本做批量治理预览。批量 promote-preview 只生成预览，不写入数据集。"
					: "Replay the selected turn directly, or run governance previews for checked turns. Batch promote-preview is non-writing."}
			</p>

			<TrajectoryActionOptionsForm
				answerSubstringChars={actionState.answerSubstringChars}
				caseIdPrefix={actionState.caseIdPrefix}
				copyAnswerSubstring={actionState.copyAnswerSubstring}
				copyToolTrajectory={actionState.copyToolTrajectory}
				isChineseUi={isChineseUi}
				setAnswerSubstringChars={actionState.setAnswerSubstringChars}
				setCaseIdPrefix={actionState.setCaseIdPrefix}
				setCopyAnswerSubstring={actionState.setCopyAnswerSubstring}
				setCopyToolTrajectory={actionState.setCopyToolTrajectory}
			/>

			<TrajectorySingleActionControls
				isChineseUi={isChineseUi}
				onPromote={() => void actionState.handlePromote()}
				onReplay={() => void actionState.handleReplay()}
				runningAction={actionState.runningAction}
			/>

			<TrajectoryBatchActionControls
				hasBatchSelection={hasBatchSelection}
				isChineseUi={isChineseUi}
				onBatchPromotePreview={() =>
					void actionState.handleBatchPromotePreview()
				}
				onBatchReplayCompare={() => void actionState.handleBatchReplayCompare()}
				onClearBatchSelection={onClearBatchSelection}
				runningAction={actionState.runningAction}
				selectedCount={batchTurnIds.length}
			/>

			{actionState.error ? (
				<div className="fa-inline-notice is-danger">{actionState.error}</div>
			) : null}

			{actionState.replayResult ? (
				<ReplayResultConsole
					expanded={actionState.expandedReplayDetails}
					isChineseUi={isChineseUi}
					onExpandedChange={actionState.setExpandedReplayDetails}
					replayResult={actionState.replayResult}
				/>
			) : null}

			{actionState.promotionResult ? (
				<PromotionResultConsole
					expanded={actionState.expandedPromotionDetails}
					isChineseUi={isChineseUi}
					onExpandedChange={actionState.setExpandedPromotionDetails}
					promotionResult={actionState.promotionResult}
				/>
			) : null}

			{actionState.batchPromotionResult ? (
				<BatchPromotionResultConsole
					batchPromotionResult={actionState.batchPromotionResult}
					expanded={actionState.expandedBatchDetails}
					isChineseUi={isChineseUi}
					onExpandedChange={actionState.setExpandedBatchDetails}
				/>
			) : null}

			{actionState.batchReplayResult ? (
				<BatchReplayResultConsole
					batchReplayResult={actionState.batchReplayResult}
					expanded={actionState.expandedBatchDetails}
					isChineseUi={isChineseUi}
					onExpandedChange={actionState.setExpandedBatchDetails}
				/>
			) : null}

			{!actionState.replayResult &&
			!actionState.promotionResult &&
			!actionState.error ? (
				<TrajectoryActionIdleNotice isChineseUi={isChineseUi} />
			) : null}
		</div>
	);
}
