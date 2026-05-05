import type { FocusAgentTrajectoryReplayResponse } from "@focus-agent/web-sdk";

import {
	copyText,
	formatDuration,
	formatSignedDelta,
} from "./trajectory-action-panel-helpers";
import {
	ActionDetailsDisclosure,
	ActionResultSnippet,
	type TrajectoryResultConsoleProps,
} from "./trajectory-result-console-parts";

interface ReplayResultConsoleProps extends TrajectoryResultConsoleProps {
	expanded: boolean;
	onExpandedChange: (expanded: boolean) => void;
	replayResult: FocusAgentTrajectoryReplayResponse;
}

function ReplayStatusNotice({
	isChineseUi,
	replayResult,
}: {
	isChineseUi: boolean;
	replayResult: FocusAgentTrajectoryReplayResponse;
}) {
	return (
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
	);
}

function ReplaySummary({
	isChineseUi,
	replayResult,
}: {
	isChineseUi: boolean;
	replayResult: FocusAgentTrajectoryReplayResponse;
}) {
	return (
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
	);
}

function ReplayDiffGrid({
	isChineseUi,
	replayResult,
}: {
	isChineseUi: boolean;
	replayResult: FocusAgentTrajectoryReplayResponse;
}) {
	return (
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
						<p>{replayResult.comparison.source_tools.join(" → ") || "—"}</p>
					</div>
					<div>
						<span>{isChineseUi ? "回放" : "Replay"}</span>
						<p>{replayResult.comparison.replay_tools.join(" → ") || "—"}</p>
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
	);
}

function ReplayCommandBar({
	isChineseUi,
	replayResult,
}: {
	isChineseUi: boolean;
	replayResult: FocusAgentTrajectoryReplayResponse;
}) {
	return (
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
	);
}

export function ReplayResultConsole({
	expanded,
	isChineseUi,
	onExpandedChange,
	replayResult,
}: ReplayResultConsoleProps) {
	return (
		<div className="fa-observability-action-console">
			<ReplayStatusNotice
				isChineseUi={isChineseUi}
				replayResult={replayResult}
			/>
			<ReplaySummary isChineseUi={isChineseUi} replayResult={replayResult} />
			<ActionDetailsDisclosure
				expanded={expanded}
				onExpandedChange={onExpandedChange}
				summary={isChineseUi ? "展开 Replay 详情" : "Show replay details"}
			>
				<div className="fa-observability-action-console">
					<ReplayCommandBar
						isChineseUi={isChineseUi}
						replayResult={replayResult}
					/>
					<ReplayDiffGrid
						isChineseUi={isChineseUi}
						replayResult={replayResult}
					/>
					<ActionResultSnippet
						label={isChineseUi ? "Replay 结果" : "Replay result"}
						value={JSON.stringify(replayResult.replay_result, null, 2)}
					/>
				</div>
			</ActionDetailsDisclosure>
		</div>
	);
}
