import type {
	FocusAgentTrajectoryStatsRow,
	FocusAgentTrajectoryTurnDetail,
	FocusAgentTrajectoryTurnSummary,
} from "@focus-agent/web-sdk";

import { TrajectoryActionPanel } from "./trajectory-action-panel";
import { TrajectoryEmptyState } from "./trajectory-states";
import type { ActionRailSection, CorrelationSignal } from "./trajectory-utils";
import {
	compactSnippet,
	formatDuration,
	formatMetric,
} from "./trajectory-utils";

type PivotAction = {
	id: string;
	label: string;
	caption: string;
	disabled: boolean;
	action: () => void;
};

type TrajectoryActionRailProps = {
	actionRailSections: ActionRailSection[];
	batchItems: FocusAgentTrajectoryTurnSummary[];
	correlationCoverage: number;
	correlationSignals: CorrelationSignal[];
	hottestTools: FocusAgentTrajectoryStatsRow[];
	isChineseUi: boolean;
	isStatsLoading: boolean;
	onClearBatchSelection: () => void;
	onCopyCommand: () => void;
	onCopyLink: () => void;
	onCopyText: (value: string) => void;
	onDownloadSelectedRecord: () => void;
	onSetToolFilter: (value: string) => void;
	pivotActions: PivotAction[];
	selected: FocusAgentTrajectoryTurnDetail | null;
	commandSnippet: string;
	statsOverview?: {
		non_succeeded_count?: number;
		total_fallback_uses?: number;
		total_cache_hits?: number;
		total_tool_failures?: number;
		total_tool_recovered?: number;
		total_degraded_answers?: number;
	};
	toolFilter: string;
};

export function TrajectoryActionRail({
	actionRailSections,
	batchItems,
	commandSnippet,
	correlationCoverage,
	correlationSignals,
	hottestTools,
	isChineseUi,
	isStatsLoading,
	onClearBatchSelection,
	onCopyCommand,
	onCopyLink,
	onCopyText,
	onDownloadSelectedRecord,
	onSetToolFilter,
	pivotActions,
	selected,
	statsOverview,
	toolFilter,
}: TrajectoryActionRailProps) {
	const [
		anchorsSection,
		pivotsSection,
		toolsSection,
		quickSection,
		actionsSection,
	] = actionRailSections;

	if (!selected) {
		return (
			<TrajectoryEmptyState isChineseUi={isChineseUi} kind="rail-placeholder" />
		);
	}

	return (
		<div className="fa-trajectory-workbench-rail">
			<section className="fa-trajectory-workbench-rail-section">
				<div className="fa-trajectory-workbench-section-head">
					<div>
						<p>
							{isChineseUi ? anchorsSection.titleZh : anchorsSection.titleEn}
						</p>
						<h3>
							{isChineseUi
								? "交接和 deep link 用到的锚点"
								: "Anchors for handoff and deep links"}
						</h3>
						<span>
							{isChineseUi
								? anchorsSection.captionZh
								: anchorsSection.captionEn}
						</span>
					</div>
					{anchorsSection.count ? (
						<strong>{anchorsSection.count}</strong>
					) : null}
				</div>
				<div className="fa-observability-correlation-list">
					{correlationSignals.map((signal) => (
						<div key={signal.id} className="fa-observability-correlation-item">
							<div>
								<span>{isChineseUi ? signal.labelZh : signal.labelEn}</span>
								<strong className={signal.tone === "accent" ? "is-accent" : ""}>
									{signal.value}
								</strong>
							</div>
							<button
								className="fa-chat-toolbar-button"
								onClick={() => onCopyText(signal.value)}
								type="button"
							>
								{isChineseUi ? "复制" : "Copy"}
							</button>
						</div>
					))}
				</div>
				{correlationCoverage === 0 ? (
					<div className="fa-inline-notice">
						{isChineseUi
							? "当前样本还没有显式 request / trace / span 字段，页面会继续从 metadata 里自动探测。"
							: "This turn does not expose explicit request/trace/span fields yet, so the page keeps probing metadata."}
					</div>
				) : null}
			</section>

			<section className="fa-trajectory-workbench-rail-section">
				<div className="fa-trajectory-workbench-section-head">
					<div>
						<p>{isChineseUi ? pivotsSection.titleZh : pivotsSection.titleEn}</p>
						<h3>
							{isChineseUi
								? "Pivot 动作与范围信号"
								: "Pivot actions and scope signals"}
						</h3>
						<span>
							{isChineseUi ? pivotsSection.captionZh : pivotsSection.captionEn}
						</span>
					</div>
				</div>
				<div className="fa-observability-pivot-grid">
					{pivotActions.map((action) => (
						<button
							key={`rail-${action.id}`}
							className={`fa-observability-pivot-button ${action.disabled ? "is-disabled" : ""}`.trim()}
							disabled={action.disabled}
							onClick={action.action}
							type="button"
						>
							<strong>{action.label}</strong>
							<span>{compactSnippet(action.caption, 72) || "—"}</span>
						</button>
					))}
				</div>
				<div className="fa-observability-status-strip">
					<div>
						<span>{isChineseUi ? "工具失败" : "Tool failures"}</span>
						<strong>
							{isStatsLoading
								? "…"
								: formatMetric(statsOverview?.total_tool_failures, 0)}
						</strong>
					</div>
					<div>
						<span>{isChineseUi ? "工具恢复" : "Recovered tools"}</span>
						<strong>
							{isStatsLoading
								? "…"
								: formatMetric(statsOverview?.total_tool_recovered, 0)}
						</strong>
					</div>
					<div>
						<span>{isChineseUi ? "降级回答" : "Degraded answers"}</span>
						<strong>
							{isStatsLoading
								? "…"
								: formatMetric(statsOverview?.total_degraded_answers, 0)}
						</strong>
					</div>
					<div>
						<span>{isChineseUi ? "失败数" : "Failed turns"}</span>
						<strong>
							{isStatsLoading
								? "…"
								: formatMetric(statsOverview?.non_succeeded_count, 0)}
						</strong>
					</div>
					<div>
						<span>{isChineseUi ? "Fallback 总数" : "Fallback uses"}</span>
						<strong>
							{isStatsLoading
								? "…"
								: formatMetric(statsOverview?.total_fallback_uses, 0)}
						</strong>
					</div>
					<div>
						<span>{isChineseUi ? "Cache Hits" : "Cache hits"}</span>
						<strong>
							{isStatsLoading
								? "…"
								: formatMetric(statsOverview?.total_cache_hits, 0)}
						</strong>
					</div>
				</div>
			</section>

			<section className="fa-trajectory-workbench-rail-section">
				<div className="fa-trajectory-workbench-section-head">
					<div>
						<p>{isChineseUi ? toolsSection.titleZh : toolsSection.titleEn}</p>
						<h3>{isChineseUi ? "热点工具" : "Hot tools"}</h3>
						<span>
							{isChineseUi ? toolsSection.captionZh : toolsSection.captionEn}
						</span>
					</div>
					{toolsSection.count ? <strong>{toolsSection.count}</strong> : null}
				</div>
				{hottestTools.length ? (
					<div className="fa-observability-tool-list">
						{hottestTools.map((tool) => (
							<button
								key={tool.key}
								className={`fa-observability-tool-row ${toolFilter.trim() === String(tool.key ?? "") ? "is-active" : ""}`}
								onClick={() => onSetToolFilter(String(tool.key ?? ""))}
								type="button"
							>
								<div>
									<strong>{tool.key}</strong>
									<span>
										{isChineseUi
											? `${formatMetric(tool.turn_count, 0)} 条样本`
											: `${formatMetric(tool.turn_count, 0)} turns`}
									</span>
								</div>
								<span>{formatDuration(tool.avg_duration_ms)}</span>
							</button>
						))}
					</div>
				) : (
					<div className="fa-observability-empty is-compact">
						{isChineseUi
							? "暂无工具分布数据。"
							: "Tool distribution is not available yet."}
					</div>
				)}
			</section>

			<section className="fa-trajectory-workbench-rail-section">
				<div className="fa-trajectory-workbench-section-head">
					<div>
						<p>{isChineseUi ? quickSection.titleZh : quickSection.titleEn}</p>
						<h3>{isChineseUi ? "快捷动作" : "Quick actions"}</h3>
						<span>
							{isChineseUi ? quickSection.captionZh : quickSection.captionEn}
						</span>
					</div>
				</div>
				<div className="fa-observability-command-bar">
					<button
						className="fa-chat-toolbar-button"
						onClick={onCopyLink}
						type="button"
					>
						{isChineseUi ? "复制链接" : "Copy link"}
					</button>
					{commandSnippet ? (
						<button
							className="fa-chat-toolbar-button"
							onClick={onCopyCommand}
							type="button"
						>
							{isChineseUi ? "复制 CLI 命令" : "Copy CLI command"}
						</button>
					) : null}
					<button
						className="fa-chat-toolbar-button"
						onClick={onDownloadSelectedRecord}
						type="button"
					>
						{isChineseUi ? "下载 JSON" : "Download JSON"}
					</button>
				</div>
			</section>

			<section className="fa-trajectory-workbench-rail-section is-action-panel">
				<div className="fa-trajectory-workbench-section-head">
					<div>
						<p>
							{isChineseUi ? actionsSection.titleZh : actionsSection.titleEn}
						</p>
						<h3>{isChineseUi ? "复盘动作" : "Replay actions"}</h3>
						<span>
							{isChineseUi
								? actionsSection.captionZh
								: actionsSection.captionEn}
						</span>
					</div>
				</div>
				<TrajectoryActionPanel
					batchItems={batchItems}
					isChineseUi={isChineseUi}
					onClearBatchSelection={onClearBatchSelection}
					selected={selected}
				/>
			</section>
		</div>
	);
}
