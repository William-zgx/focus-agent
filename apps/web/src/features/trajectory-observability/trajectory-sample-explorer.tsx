import type { FocusAgentTrajectoryTurnSummary } from "@focus-agent/web-sdk";
import type { ReactNode } from "react";

import {
	buildTurnSummary,
	compactId,
	compactQuestion,
	formatDateTime,
	formatDuration,
	formatMetric,
	statusTone,
} from "./trajectory-utils";

type TrajectorySampleExplorerProps = {
	isChineseUi: boolean;
	isListLoading: boolean;
	items: FocusAgentTrajectoryTurnSummary[];
	locale: "zh-CN" | "en-US";
	matchCount: number;
	onClearBatchSelection: () => void;
	onSelectVisibleBatch: () => void;
	onSelectVisibleFailuresBatch: () => void;
	onToggleBatchSelection: (turnId: string) => void;
	onSelectTurn: (turnId: string) => void;
	selectedBatchIdSet: Set<string>;
	selectedBatchTurnIds: string[];
	selectedTurnId: string;
	children?: ReactNode;
};

export function TrajectorySampleExplorer({
	children,
	isChineseUi,
	isListLoading,
	items,
	locale,
	matchCount,
	onClearBatchSelection,
	onSelectVisibleBatch,
	onSelectVisibleFailuresBatch,
	onToggleBatchSelection,
	onSelectTurn,
	selectedBatchIdSet,
	selectedBatchTurnIds,
	selectedTurnId,
}: TrajectorySampleExplorerProps) {
	return (
		<>
			<div className="fa-trajectory-workbench-panel-head">
				<div className="fa-trajectory-workbench-panel-copy">
					<p>{isChineseUi ? "先选样本" : "Sample queue"}</p>
					<h2>
						{isChineseUi ? "高密度样本队列" : "High-density sample queue"}
					</h2>
					<span>
						{isChineseUi
							? "把筛选和空态都收在左栏里，尽量提高同屏可见的样本数。"
							: "Keep filters and list-state handling inside the left rail to maximize visible samples."}
					</span>
				</div>
				<strong>{isListLoading ? "…" : formatMetric(matchCount, 0)}</strong>
			</div>

			<div className="fa-trajectory-workbench-batch-toolbar">
				<div>
					<span>
						{isChineseUi ? "批量治理选择" : "Batch governance selection"}
					</span>
					<strong>
						{isChineseUi
							? `${selectedBatchTurnIds.length} 条已勾选`
							: `${selectedBatchTurnIds.length} selected`}
					</strong>
				</div>
				<div className="fa-observability-command-bar">
					<button
						className="fa-chat-toolbar-button"
						disabled={!items.length}
						onClick={onSelectVisibleBatch}
						type="button"
					>
						{isChineseUi ? "勾选当前页" : "Select visible"}
					</button>
					<button
						className="fa-chat-toolbar-button"
						disabled={
							!items.some((item) => item.status !== "succeeded" || item.error)
						}
						onClick={onSelectVisibleFailuresBatch}
						type="button"
					>
						{isChineseUi ? "仅勾选失败" : "Select failures"}
					</button>
					<button
						className="fa-chat-toolbar-button"
						disabled={!selectedBatchTurnIds.length}
						onClick={onClearBatchSelection}
						type="button"
					>
						{isChineseUi ? "清空" : "Clear"}
					</button>
				</div>
			</div>

			<div className="fa-trajectory-workbench-sample-list">
				{items.map((item) => (
					<div
						key={item.id}
						className={`fa-trajectory-workbench-sample-row ${selectedBatchIdSet.has(item.id) ? "is-batch-selected" : ""}`.trim()}
					>
						<label className="fa-trajectory-workbench-batch-checkbox">
							<input
								checked={selectedBatchIdSet.has(item.id)}
								onChange={() => onToggleBatchSelection(item.id)}
								type="checkbox"
							/>
							<span>{isChineseUi ? "批量" : "Batch"}</span>
						</label>
						<button
							className={`fa-trajectory-workbench-sample-card ${selectedTurnId === item.id ? "is-selected" : ""}`.trim()}
							onClick={() => onSelectTurn(item.id)}
							type="button"
						>
							<div className="fa-trajectory-workbench-sample-top">
								<span
									className={`fa-observability-pill is-${statusTone(item.status)}`}
								>
									{item.status}
								</span>
								<span>{formatDateTime(item.created_at, locale)}</span>
							</div>
							<strong>
								{compactQuestion(
									item.user_message || item.task_brief || item.id,
								)}
							</strong>
							<p className="fa-trajectory-workbench-sample-summary">
								{buildTurnSummary(item, isChineseUi)}
							</p>
							<div className="fa-trajectory-workbench-sample-anchors">
								<span>{`Req ${compactId(item.request_id)}`}</span>
								<span>{`Trace ${compactId(item.trace_id)}`}</span>
							</div>
							<div className="fa-trajectory-workbench-sample-anchors">
								<span>{compactId(item.thread_id)}</span>
								<span>{item.selected_model || "—"}</span>
							</div>
							<div className="fa-trajectory-workbench-sample-metrics">
								<span>{formatDuration(item.latency_ms)}</span>
								<span>{`${item.tool_calls} ${isChineseUi ? "工具" : "tools"}`}</span>
								<span>{`${item.fallback_uses} fallback`}</span>
							</div>
						</button>
					</div>
				))}
				{children}
			</div>
		</>
	);
}
