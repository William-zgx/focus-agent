import type {
	FocusAgentTrajectoryBatchPromotionPreviewResponse,
	FocusAgentTrajectoryBatchReplayCompareResponse,
} from "@focus-agent/web-sdk";

import { compactId, copyText } from "./trajectory-action-panel-helpers";
import {
	ActionDetailsDisclosure,
	ActionResultSnippet,
	type TrajectoryResultConsoleProps,
} from "./trajectory-result-console-parts";

interface BatchPromotionResultConsoleProps
	extends TrajectoryResultConsoleProps {
	batchPromotionResult: FocusAgentTrajectoryBatchPromotionPreviewResponse;
	expanded: boolean;
	onExpandedChange: (expanded: boolean) => void;
}

interface BatchReplayResultConsoleProps extends TrajectoryResultConsoleProps {
	batchReplayResult: FocusAgentTrajectoryBatchReplayCompareResponse;
	expanded: boolean;
	onExpandedChange: (expanded: boolean) => void;
}

function BatchPromotionMarkers({
	batchPromotionResult,
	isChineseUi,
}: {
	batchPromotionResult: FocusAgentTrajectoryBatchPromotionPreviewResponse;
	isChineseUi: boolean;
}) {
	return (
		<div className="fa-trajectory-workbench-batch-result-list">
			{batchPromotionResult.items.map((item) => (
				<div
					key={item.source_turn_id}
					className="fa-trajectory-workbench-batch-result-marker is-success"
				>
					<div>
						<span>{compactId(item.source_turn_id)}</span>
						<strong>
							{item.case_id || (isChineseUi ? "可生成" : "Ready")}
						</strong>
					</div>
					<span>{isChineseUi ? "非写入预览" : "Non-writing preview"}</span>
				</div>
			))}
		</div>
	);
}

function BatchReplayMarkers({
	batchReplayResult,
	isChineseUi,
}: {
	batchReplayResult: FocusAgentTrajectoryBatchReplayCompareResponse;
	isChineseUi: boolean;
}) {
	return (
		<div className="fa-trajectory-workbench-batch-result-list">
			{batchReplayResult.results.map((item) => {
				const passed = Boolean(item.replay_result.passed);
				const changed = Boolean(item.comparison.tool_path_changed);
				return (
					<div
						key={item.source_turn_id}
						className={`fa-trajectory-workbench-batch-result-marker ${passed ? "is-success" : "is-warning"}`.trim()}
					>
						<div>
							<span>{compactId(item.source_turn_id)}</span>
							<strong>
								{passed
									? isChineseUi
										? "通过"
										: "Passed"
									: isChineseUi
										? "未通过"
										: "Did not pass"}
							</strong>
						</div>
						<span>
							{changed
								? isChineseUi
									? "工具路径变化"
									: "Tool path changed"
								: isChineseUi
									? "工具路径未变化"
									: "Tool path unchanged"}
						</span>
					</div>
				);
			})}
		</div>
	);
}

export function BatchPromotionResultConsole({
	batchPromotionResult,
	expanded,
	isChineseUi,
	onExpandedChange,
}: BatchPromotionResultConsoleProps) {
	const resultJson = JSON.stringify(batchPromotionResult, null, 2);
	return (
		<div className="fa-observability-action-console fa-trajectory-workbench-batch-result-console">
			<div className="fa-inline-notice is-success">
				{isChineseUi
					? `批量 promote-preview 已完成（未写入）：${batchPromotionResult.items.length}/${batchPromotionResult.count} 条可用。`
					: `Batch promote-preview completed (non-writing): ${batchPromotionResult.items.length}/${batchPromotionResult.count} usable.`}
			</div>
			<BatchPromotionMarkers
				batchPromotionResult={batchPromotionResult}
				isChineseUi={isChineseUi}
			/>
			<ActionDetailsDisclosure
				expanded={expanded}
				onExpandedChange={onExpandedChange}
				summary={
					isChineseUi ? "展开批量预览详情" : "Show batch preview details"
				}
			>
				<div className="fa-observability-command-bar">
					<button
						className="fa-chat-toolbar-button"
						onClick={() => void copyText(resultJson)}
						type="button"
					>
						{isChineseUi ? "复制结果 JSON" : "Copy result JSON"}
					</button>
					{batchPromotionResult.jsonl ? (
						<button
							className="fa-chat-toolbar-button"
							onClick={() => void copyText(batchPromotionResult.jsonl || "")}
							type="button"
						>
							{isChineseUi ? "复制合并 JSONL" : "Copy merged JSONL"}
						</button>
					) : null}
				</div>
				<ActionResultSnippet
					label={isChineseUi ? "批量 Promote Preview" : "Batch promote-preview"}
					value={resultJson}
				/>
			</ActionDetailsDisclosure>
		</div>
	);
}

export function BatchReplayResultConsole({
	batchReplayResult,
	expanded,
	isChineseUi,
	onExpandedChange,
}: BatchReplayResultConsoleProps) {
	const resultJson = JSON.stringify(batchReplayResult, null, 2);
	return (
		<div className="fa-observability-action-console fa-trajectory-workbench-batch-result-console">
			<div className="fa-inline-notice">
				{isChineseUi
					? `批量 replay-compare 已完成：${batchReplayResult.summary.passed}/${batchReplayResult.summary.total} 条通过。`
					: `Batch replay-compare completed: ${batchReplayResult.summary.passed}/${batchReplayResult.summary.total} passed.`}
			</div>
			<BatchReplayMarkers
				batchReplayResult={batchReplayResult}
				isChineseUi={isChineseUi}
			/>
			<ActionDetailsDisclosure
				expanded={expanded}
				onExpandedChange={onExpandedChange}
				summary={
					isChineseUi ? "展开批量 Replay 对比详情" : "Show batch replay details"
				}
			>
				<div className="fa-observability-command-bar">
					<button
						className="fa-chat-toolbar-button"
						onClick={() => void copyText(resultJson)}
						type="button"
					>
						{isChineseUi ? "复制结果 JSON" : "Copy result JSON"}
					</button>
				</div>
				<ActionResultSnippet
					label={isChineseUi ? "批量 Replay Compare" : "Batch replay-compare"}
					value={resultJson}
				/>
			</ActionDetailsDisclosure>
		</div>
	);
}
