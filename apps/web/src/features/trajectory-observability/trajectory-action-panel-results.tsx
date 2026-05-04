import type {
	FocusAgentTrajectoryBatchPromotionPreviewResponse,
	FocusAgentTrajectoryBatchReplayCompareResponse,
	FocusAgentTrajectoryPromotionResponse,
	FocusAgentTrajectoryReplayResponse,
} from "@focus-agent/web-sdk";

import {
	compactId,
	copyText,
	downloadTextArtifact,
	formatDuration,
	formatSignedDelta,
} from "./trajectory-action-panel-helpers";

interface TrajectoryResultConsoleProps {
	isChineseUi: boolean;
}

interface ReplayResultConsoleProps extends TrajectoryResultConsoleProps {
	expanded: boolean;
	onExpandedChange: (expanded: boolean) => void;
	replayResult: FocusAgentTrajectoryReplayResponse;
}

export function ReplayResultConsole({
	expanded,
	isChineseUi,
	onExpandedChange,
	replayResult,
}: ReplayResultConsoleProps) {
	return (
		<div className="fa-observability-action-console">
			<div
				className={`fa-inline-notice ${replayResult.replay_result.passed ? "is-success" : "is-danger"}`.trim()}
			>
				{replayResult.replay_result.passed
					? isChineseUi
						? "Replay 已完成，结果通过。"
						: "Replay completed successfully."
					: isChineseUi
						? "Replay 已完成，但结果未通过。"
						: "Replay completed, but the case did not pass."}
			</div>
			<div className="fa-observability-action-summary">
				<div>
					<span>{isChineseUi ? "Case ID" : "Case ID"}</span>
					<strong>{replayResult.replay_case.id}</strong>
				</div>
				<div>
					<span>{isChineseUi ? "回放模型" : "Replay model"}</span>
					<strong>{replayResult.model_used}</strong>
				</div>
				<div>
					<span>{isChineseUi ? "回放延迟" : "Replay latency"}</span>
					<strong>
						{formatDuration(
							Number(replayResult.replay_result.metrics?.latency_ms ?? 0),
						)}
					</strong>
				</div>
				<div>
					<span>{isChineseUi ? "路径是否变化" : "Tool path changed"}</span>
					<strong>{String(replayResult.comparison.tool_path_changed)}</strong>
				</div>
			</div>
			<details
				className="fa-observability-action-disclosure"
				open={expanded}
				onToggle={(event) =>
					onExpandedChange((event.currentTarget as HTMLDetailsElement).open)
				}
			>
				<summary>{isChineseUi ? "展开 Replay 详情" : "Show replay details"}</summary>
				<div className="fa-observability-action-console">
					<div className="fa-observability-command-bar">
						<button
							className="fa-chat-toolbar-button"
							onClick={() =>
								void copyText(JSON.stringify(replayResult.replay_case, null, 2))
							}
							type="button"
						>
							{isChineseUi ? "复制 Replay Case" : "Copy replay case"}
						</button>
						<button
							className="fa-chat-toolbar-button"
							onClick={() => void copyText(replayResult.replay_case_jsonl)}
							type="button"
						>
							{isChineseUi ? "复制 Replay JSONL" : "Copy replay JSONL"}
						</button>
						<button
							className="fa-chat-toolbar-button"
							onClick={() =>
								void copyText(JSON.stringify(replayResult.replay_result, null, 2))
							}
							type="button"
						>
							{isChineseUi ? "复制 Replay 结果" : "Copy replay result"}
						</button>
					</div>
					<div className="fa-observability-diff-grid">
						<div className="fa-observability-diff-card">
							<span>{isChineseUi ? "工具路径变化" : "Tool path delta"}</span>
							<strong>
								{replayResult.comparison.tool_path_changed
									? isChineseUi
										? "已变化"
										: "Changed"
									: isChineseUi
										? "未变化"
										: "Unchanged"}
							</strong>
							<div className="fa-observability-diff-paths">
								<div>
									<span>{isChineseUi ? "原始" : "Source"}</span>
									<p>
										{replayResult.comparison.source_tools.join(" → ") || "—"}
									</p>
								</div>
								<div>
									<span>{isChineseUi ? "回放" : "Replay"}</span>
									<p>
										{replayResult.comparison.replay_tools.join(" → ") || "—"}
									</p>
								</div>
							</div>
						</div>
						<div className="fa-observability-diff-card">
							<span>{isChineseUi ? "指标对比" : "Metric delta"}</span>
							<strong>
								{isChineseUi ? "延迟差值" : "Latency delta"}{" "}
								{formatSignedDelta(
									replayResult.comparison.replay_latency_ms,
									replayResult.comparison.source_latency_ms,
									"ms",
								)}
							</strong>
							<div className="fa-observability-diff-metrics">
								<div>
									<span>{isChineseUi ? "Fallback" : "Fallback"}</span>
									<p>{`${replayResult.comparison.source_fallback_uses} → ${replayResult.comparison.replay_fallback_uses}`}</p>
								</div>
								<div>
									<span>{isChineseUi ? "Cache Hits" : "Cache hits"}</span>
									<p>{`${replayResult.comparison.source_cache_hits} → ${replayResult.comparison.replay_cache_hits}`}</p>
								</div>
								<div>
									<span>{isChineseUi ? "工具数" : "Tool calls"}</span>
									<p>{`${replayResult.comparison.source_tool_calls} → ${replayResult.comparison.replay_tool_calls}`}</p>
								</div>
							</div>
						</div>
						<div className="fa-observability-diff-card">
							<span>{isChineseUi ? "答案预览" : "Answer preview"}</span>
							<strong>{isChineseUi ? "原始 / 回放" : "Source / replay"}</strong>
							<div className="fa-observability-diff-previews">
								<div>
									<span>{isChineseUi ? "原始" : "Source"}</span>
									<p>{replayResult.comparison.source_answer_preview || "—"}</p>
								</div>
								<div>
									<span>{isChineseUi ? "回放" : "Replay"}</span>
									<p>{replayResult.comparison.replay_answer_preview || "—"}</p>
								</div>
							</div>
						</div>
					</div>
					<div className="fa-observability-action-snippet">
						<span>{isChineseUi ? "Replay 结果" : "Replay result"}</span>
						<pre>{JSON.stringify(replayResult.replay_result, null, 2)}</pre>
					</div>
				</div>
			</details>
		</div>
	);
}

interface PromotionResultConsoleProps extends TrajectoryResultConsoleProps {
	expanded: boolean;
	onExpandedChange: (expanded: boolean) => void;
	promotionResult: FocusAgentTrajectoryPromotionResponse;
}

export function PromotionResultConsole({
	expanded,
	isChineseUi,
	onExpandedChange,
	promotionResult,
}: PromotionResultConsoleProps) {
	return (
		<div className="fa-observability-action-console">
			<div className="fa-inline-notice is-success">
				{isChineseUi
					? "Promote skeleton 预览已生成（未写入）。"
					: "Promotion skeleton preview generated (not written)."}
			</div>
			<div className="fa-observability-action-summary">
				<div>
					<span>{isChineseUi ? "Case ID" : "Case ID"}</span>
					<strong>{promotionResult.case_id}</strong>
				</div>
				<div>
					<span>{isChineseUi ? "来源 Turn" : "Source turn"}</span>
					<strong>{promotionResult.source_turn_id}</strong>
				</div>
			</div>
			<details
				className="fa-observability-action-disclosure"
				open={expanded}
				onToggle={(event) =>
					onExpandedChange((event.currentTarget as HTMLDetailsElement).open)
				}
			>
				<summary>
					{isChineseUi ? "展开 Promote 详情" : "Show promotion details"}
				</summary>
				<div className="fa-observability-action-console">
					<div className="fa-observability-command-bar">
						<button
							className="fa-chat-toolbar-button"
							onClick={() => void copyText(promotionResult.jsonl)}
							type="button"
						>
							{isChineseUi ? "复制 JSONL" : "Copy JSONL"}
						</button>
						<button
							className="fa-chat-toolbar-button"
							onClick={() =>
								downloadTextArtifact(
									`${promotionResult.case_id}.jsonl`,
									`${promotionResult.jsonl}\n`,
									"application/x-ndjson",
								)
							}
							type="button"
						>
							{isChineseUi ? "下载 JSONL" : "Download JSONL"}
						</button>
					</div>
					<div className="fa-observability-action-snippet">
						<span>{isChineseUi ? "Promote Skeleton" : "Promotion skeleton"}</span>
						<pre>{promotionResult.jsonl}</pre>
					</div>
				</div>
			</details>
		</div>
	);
}

interface BatchPromotionResultConsoleProps extends TrajectoryResultConsoleProps {
	batchPromotionResult: FocusAgentTrajectoryBatchPromotionPreviewResponse;
	expanded: boolean;
	onExpandedChange: (expanded: boolean) => void;
}

export function BatchPromotionResultConsole({
	batchPromotionResult,
	expanded,
	isChineseUi,
	onExpandedChange,
}: BatchPromotionResultConsoleProps) {
	return (
		<div className="fa-observability-action-console fa-trajectory-workbench-batch-result-console">
			<div className="fa-inline-notice is-success">
				{isChineseUi
					? `批量 promote-preview 已完成（未写入）：${batchPromotionResult.items.length}/${batchPromotionResult.count} 条可用。`
					: `Batch promote-preview completed (non-writing): ${batchPromotionResult.items.length}/${batchPromotionResult.count} usable.`}
			</div>
			<div className="fa-trajectory-workbench-batch-result-list">
				{batchPromotionResult.items.map((item) => {
					return (
						<div
							key={item.source_turn_id}
							className="fa-trajectory-workbench-batch-result-marker is-success"
						>
							<div>
								<span>{compactId(item.source_turn_id)}</span>
								<strong>{item.case_id || (isChineseUi ? "可生成" : "Ready")}</strong>
							</div>
							<span>{isChineseUi ? "非写入预览" : "Non-writing preview"}</span>
						</div>
					);
				})}
			</div>
			<details
				className="fa-observability-action-disclosure"
				open={expanded}
				onToggle={(event) =>
					onExpandedChange((event.currentTarget as HTMLDetailsElement).open)
				}
			>
				<summary>
					{isChineseUi ? "展开批量预览详情" : "Show batch preview details"}
				</summary>
				<div className="fa-observability-command-bar">
					<button
						className="fa-chat-toolbar-button"
						onClick={() =>
							void copyText(JSON.stringify(batchPromotionResult, null, 2))
						}
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
				<div className="fa-observability-action-snippet">
					<span>{isChineseUi ? "批量 Promote Preview" : "Batch promote-preview"}</span>
					<pre>{JSON.stringify(batchPromotionResult, null, 2)}</pre>
				</div>
			</details>
		</div>
	);
}

interface BatchReplayResultConsoleProps extends TrajectoryResultConsoleProps {
	batchReplayResult: FocusAgentTrajectoryBatchReplayCompareResponse;
	expanded: boolean;
	onExpandedChange: (expanded: boolean) => void;
}

export function BatchReplayResultConsole({
	batchReplayResult,
	expanded,
	isChineseUi,
	onExpandedChange,
}: BatchReplayResultConsoleProps) {
	return (
		<div className="fa-observability-action-console fa-trajectory-workbench-batch-result-console">
			<div className="fa-inline-notice">
				{isChineseUi
					? `批量 replay-compare 已完成：${batchReplayResult.summary.passed}/${batchReplayResult.summary.total} 条通过。`
					: `Batch replay-compare completed: ${batchReplayResult.summary.passed}/${batchReplayResult.summary.total} passed.`}
			</div>
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
			<details
				className="fa-observability-action-disclosure"
				open={expanded}
				onToggle={(event) =>
					onExpandedChange((event.currentTarget as HTMLDetailsElement).open)
				}
			>
				<summary>
					{isChineseUi ? "展开批量 Replay 对比详情" : "Show batch replay details"}
				</summary>
				<div className="fa-observability-command-bar">
					<button
						className="fa-chat-toolbar-button"
						onClick={() =>
							void copyText(JSON.stringify(batchReplayResult, null, 2))
						}
						type="button"
					>
						{isChineseUi ? "复制结果 JSON" : "Copy result JSON"}
					</button>
				</div>
				<div className="fa-observability-action-snippet">
					<span>{isChineseUi ? "批量 Replay Compare" : "Batch replay-compare"}</span>
					<pre>{JSON.stringify(batchReplayResult, null, 2)}</pre>
				</div>
			</details>
		</div>
	);
}
