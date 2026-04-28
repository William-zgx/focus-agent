import type { SortMode, StatusMode } from "./trajectory-utils";
import type { FilterChip } from "./trajectory-utils";

type FiltersPanelProps = {
	fallbackOnly: boolean;
	filterChips: FilterChip[];
	filtersExpanded: boolean;
	hasErrorOnly: boolean;
	hasInvalidLatency: boolean;
	isChineseUi: boolean;
	minLatency: string;
	modelFilter: string;
	onApplyPreset: (preset: "failures" | "fallback" | "latency" | "all") => void;
	onResetFilters: () => void;
	requestFilter: string;
	setFallbackOnly: (value: boolean) => void;
	setFiltersExpanded: (
		value: boolean | ((current: boolean) => boolean),
	) => void;
	setHasErrorOnly: (value: boolean) => void;
	setMinLatency: (value: string) => void;
	setModelFilter: (value: string) => void;
	setRequestFilter: (value: string) => void;
	setSortMode: (value: SortMode) => void;
	setStatusFilter: (value: StatusMode) => void;
	setThreadFilter: (value: string) => void;
	setToolFilter: (value: string) => void;
	setTraceFilter: (value: string) => void;
	sortMode: SortMode;
	statusFilter: StatusMode;
	threadFilter: string;
	toolFilter: string;
	traceFilter: string;
};

export function TrajectoryFiltersPanel({
	fallbackOnly,
	filterChips,
	filtersExpanded,
	hasErrorOnly,
	hasInvalidLatency,
	isChineseUi,
	minLatency,
	modelFilter,
	onApplyPreset,
	onResetFilters,
	requestFilter,
	setFallbackOnly,
	setFiltersExpanded,
	setHasErrorOnly,
	setMinLatency,
	setModelFilter,
	setRequestFilter,
	setSortMode,
	setStatusFilter,
	setThreadFilter,
	setToolFilter,
	setTraceFilter,
	sortMode,
	statusFilter,
	threadFilter,
	toolFilter,
	traceFilter,
}: FiltersPanelProps) {
	return (
		<div className="fa-trajectory-workbench-explorer-bar">
			<div className="fa-observability-presets">
				<button
					className="fa-observability-preset"
					onClick={() => onApplyPreset("failures")}
					type="button"
				>
					{isChineseUi ? "最近失败" : "Failures"}
				</button>
				<button
					className="fa-observability-preset"
					onClick={() => onApplyPreset("fallback")}
					type="button"
				>
					{isChineseUi ? "Fallback" : "Fallback"}
				</button>
				<button
					className="fa-observability-preset"
					onClick={() => onApplyPreset("latency")}
					type="button"
				>
					{isChineseUi ? "高延迟" : "Latency"}
				</button>
				<button
					className="fa-observability-preset"
					onClick={() => onApplyPreset("all")}
					type="button"
				>
					{isChineseUi ? "全部" : "All"}
				</button>
			</div>

			<div className="fa-observability-active-filters">
				{filterChips.length ? (
					filterChips.map((chip) => (
						<button
							key={chip.id}
							className="fa-observability-filter-chip"
							onClick={chip.clear}
							type="button"
						>
							<span>{isChineseUi ? chip.labelZh : chip.labelEn}</span>
							<strong>×</strong>
						</button>
					))
				) : (
					<span className="fa-observability-filter-chip is-empty">
						{isChineseUi ? "当前没有附加过滤器" : "No extra filters active"}
					</span>
				)}
			</div>

			<div className="fa-observability-filter-drawer">
				<button
					aria-expanded={filtersExpanded}
					className="fa-observability-filter-toggle"
					onClick={() => setFiltersExpanded((current) => !current)}
					type="button"
				>
					{filtersExpanded
						? isChineseUi
							? "收起高级筛选"
							: "Hide advanced filters"
						: isChineseUi
							? "展开高级筛选"
							: "Show advanced filters"}
				</button>
				{filtersExpanded ? (
					<div className="fa-observability-filter-shell">
						<div className="fa-observability-filters is-compact">
							<label className="fa-observability-filter">
								<span>{isChineseUi ? "状态" : "Status"}</span>
								<select
									value={statusFilter}
									onChange={(event) =>
										setStatusFilter(event.target.value as StatusMode)
									}
								>
									<option value="failed">
										{isChineseUi ? "失败" : "Failed"}
									</option>
									<option value="all">{isChineseUi ? "全部" : "All"}</option>
									<option value="succeeded">
										{isChineseUi ? "成功" : "Succeeded"}
									</option>
								</select>
							</label>
							<label className="fa-observability-filter">
								<span>{isChineseUi ? "工具" : "Tool"}</span>
								<input
									value={toolFilter}
									onChange={(event) => setToolFilter(event.target.value)}
									placeholder="web_search"
								/>
							</label>
							<label className="fa-observability-filter">
								<span>{isChineseUi ? "线程" : "Thread"}</span>
								<input
									value={threadFilter}
									onChange={(event) => setThreadFilter(event.target.value)}
									placeholder="thread-…"
								/>
							</label>
							<label className="fa-observability-filter">
								<span>{isChineseUi ? "Request" : "Request"}</span>
								<input
									value={requestFilter}
									onChange={(event) => setRequestFilter(event.target.value)}
									placeholder="req-…"
								/>
							</label>
							<label className="fa-observability-filter">
								<span>{isChineseUi ? "Trace" : "Trace"}</span>
								<input
									value={traceFilter}
									onChange={(event) => setTraceFilter(event.target.value)}
									placeholder="trace-…"
								/>
							</label>
							<label className="fa-observability-filter">
								<span>{isChineseUi ? "模型" : "Model"}</span>
								<input
									value={modelFilter}
									onChange={(event) => setModelFilter(event.target.value)}
									placeholder="openai:gpt-4.1-mini"
								/>
							</label>
							<label className="fa-observability-filter">
								<span>{isChineseUi ? "最小延迟" : "Min latency"}</span>
								<input
									aria-invalid={hasInvalidLatency}
									value={minLatency}
									onChange={(event) => setMinLatency(event.target.value)}
									inputMode="numeric"
									pattern="[0-9]*"
									placeholder="500"
								/>
							</label>
							<label className="fa-observability-filter">
								<span>{isChineseUi ? "排序" : "Sort"}</span>
								<select
									value={sortMode}
									onChange={(event) =>
										setSortMode(event.target.value as SortMode)
									}
								>
									<option value="newest">
										{isChineseUi ? "最近" : "Newest"}
									</option>
									<option value="latency">
										{isChineseUi ? "延迟" : "Latency"}
									</option>
									<option value="tool_calls">
										{isChineseUi ? "工具数" : "Tool calls"}
									</option>
								</select>
							</label>
							<label className="fa-observability-toggle">
								<input
									checked={fallbackOnly}
									onChange={(event) => setFallbackOnly(event.target.checked)}
									type="checkbox"
								/>
								<span>{isChineseUi ? "仅看 fallback" : "Fallback only"}</span>
							</label>
							<label className="fa-observability-toggle">
								<input
									checked={hasErrorOnly}
									onChange={(event) => setHasErrorOnly(event.target.checked)}
									type="checkbox"
								/>
								<span>{isChineseUi ? "仅看错误" : "Errors only"}</span>
							</label>
						</div>

						<div className="fa-observability-command-bar">
							{hasInvalidLatency ? (
								<span className="fa-observability-filter-hint is-warning">
									{isChineseUi
										? "最小延迟需要是非负数字。"
										: "Min latency must be a non-negative number."}
								</span>
							) : null}
							<button
								className="fa-chat-toolbar-button"
								onClick={onResetFilters}
								type="button"
							>
								{isChineseUi ? "恢复默认" : "Reset"}
							</button>
						</div>
					</div>
				) : null}
			</div>
		</div>
	);
}
