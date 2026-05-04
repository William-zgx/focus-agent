import { compactId } from "@/features/trajectory-observability/trajectory-utils";
import type {
	SortMode,
	StatusMode,
} from "@/features/trajectory-observability/trajectory-utils";

type PivotAction = {
	id: string;
	label: string;
	caption: string;
	disabled: boolean;
	action: () => void;
};

export function buildTrajectoryPivotActions({
	focusModel,
	focusRequest,
	focusThread,
	focusTrace,
	isChineseUi,
	requestFilter,
	selectedModel,
	selectedRequestSignal,
	selectedThreadSignal,
	selectedTraceSignal,
	setFiltersExpanded,
	setHasErrorOnly,
	setRequestFilter,
	setSortMode,
	setStatusFilter,
	setTraceFilter,
	traceFilter,
}: {
	focusModel: (value: string) => void;
	focusRequest: (value: string) => void;
	focusThread: (value: string) => void;
	focusTrace: (value: string) => void;
	isChineseUi: boolean;
	requestFilter: string;
	selectedModel: string;
	selectedRequestSignal: string;
	selectedThreadSignal: string;
	selectedTraceSignal: string;
	setFiltersExpanded: (value: boolean) => void;
	setHasErrorOnly: (value: boolean) => void;
	setRequestFilter: (value: string) => void;
	setSortMode: (value: SortMode) => void;
	setStatusFilter: (value: StatusMode) => void;
	setTraceFilter: (value: string) => void;
	traceFilter: string;
}): PivotAction[] {
	return [
		{
			id: "request",
			label: isChineseUi ? "锁定同一 Request" : "Lock same request",
			caption:
				selectedRequestSignal ||
				(isChineseUi
					? "当前样本没有 request_id"
					: "No request_id on this turn"),
			disabled: !selectedRequestSignal,
			action: () => focusRequest(selectedRequestSignal),
		},
		{
			id: "trace",
			label: isChineseUi ? "锁定同一 Trace" : "Lock same trace",
			caption:
				selectedTraceSignal ||
				(isChineseUi ? "当前样本没有 trace_id" : "No trace_id on this turn"),
			disabled: !selectedTraceSignal,
			action: () => focusTrace(selectedTraceSignal),
		},
		{
			id: "thread",
			label: isChineseUi ? "只看同一线程" : "Same thread only",
			caption:
				selectedThreadSignal ||
				(isChineseUi
					? "当前样本没有线程锚点"
					: "No thread anchor on this turn"),
			disabled: !selectedThreadSignal,
			action: () => focusThread(selectedThreadSignal),
		},
		{
			id: "model",
			label: isChineseUi ? "切到同一模型" : "Same model slice",
			caption:
				selectedModel ||
				(isChineseUi
					? "当前样本没有模型信息"
					: "No model captured on this turn"),
			disabled: !selectedModel,
			action: () => focusModel(selectedModel),
		},
		{
			id: "failures",
			label: isChineseUi ? "当前范围仅看失败" : "Failures in scope",
			caption: isChineseUi
				? "保留当前 request/trace/thread 等锚点，只切失败样本"
				: "Keep active anchors, then pivot to non-succeeded turns only",
			disabled: false,
			action: () => {
				setStatusFilter("failed");
				setHasErrorOnly(true);
				setSortMode("newest");
				setFiltersExpanded(true);
			},
		},
		{
			id: "clear",
			label: isChineseUi
				? "清除 request/trace 锁定"
				: "Clear request/trace pivots",
			caption:
				requestFilter.trim() || traceFilter.trim()
					? [requestFilter.trim(), traceFilter.trim()]
							.filter(Boolean)
							.map(compactId)
							.join(" · ")
					: isChineseUi
						? "当前没有 request/trace 锁定"
						: "No request/trace pivot active",
			disabled: !requestFilter.trim() && !traceFilter.trim(),
			action: () => {
				setRequestFilter("");
				setTraceFilter("");
			},
		},
	];
}
