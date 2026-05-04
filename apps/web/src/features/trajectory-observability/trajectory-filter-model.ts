import { compactId } from "./trajectory-formatters";
import type { FilterChip, SortMode, StatusMode } from "./trajectory-types";

export function normalizeStatusFilter(value: StatusMode): string[] | undefined {
	if (value === "all") return undefined;
	return [value];
}

export function buildFilterChips(args: {
	statusFilter: StatusMode;
	toolFilter: string;
	threadFilter: string;
	requestFilter: string;
	traceFilter: string;
	modelFilter: string;
	minLatency: string;
	fallbackOnly: boolean;
	hasErrorOnly: boolean;
	sortMode: SortMode;
	clearStatus: () => void;
	clearTool: () => void;
	clearThread: () => void;
	clearRequest: () => void;
	clearTrace: () => void;
	clearModel: () => void;
	clearLatency: () => void;
	clearFallback: () => void;
	clearErrorOnly: () => void;
	clearSort: () => void;
}) {
	const chips: FilterChip[] = [];
	if (args.statusFilter !== "all") {
		chips.push({
			id: "status",
			labelZh: `状态 · ${args.statusFilter === "failed" ? "失败" : "成功"}`,
			labelEn: `Status · ${args.statusFilter === "failed" ? "Failed" : "Succeeded"}`,
			clear: args.clearStatus,
		});
	}
	if (args.toolFilter.trim()) {
		chips.push({
			id: "tool",
			labelZh: `工具 · ${args.toolFilter.trim()}`,
			labelEn: `Tool · ${args.toolFilter.trim()}`,
			clear: args.clearTool,
		});
	}
	if (args.threadFilter.trim()) {
		chips.push({
			id: "thread",
			labelZh: `线程 · ${compactId(args.threadFilter.trim())}`,
			labelEn: `Thread · ${compactId(args.threadFilter.trim())}`,
			clear: args.clearThread,
		});
	}
	if (args.requestFilter.trim()) {
		chips.push({
			id: "request",
			labelZh: `Request · ${compactId(args.requestFilter.trim())}`,
			labelEn: `Request · ${compactId(args.requestFilter.trim())}`,
			clear: args.clearRequest,
		});
	}
	if (args.traceFilter.trim()) {
		chips.push({
			id: "trace",
			labelZh: `Trace · ${compactId(args.traceFilter.trim())}`,
			labelEn: `Trace · ${compactId(args.traceFilter.trim())}`,
			clear: args.clearTrace,
		});
	}
	if (args.modelFilter.trim()) {
		chips.push({
			id: "model",
			labelZh: `模型 · ${args.modelFilter.trim()}`,
			labelEn: `Model · ${args.modelFilter.trim()}`,
			clear: args.clearModel,
		});
	}
	if (args.minLatency.trim()) {
		chips.push({
			id: "latency",
			labelZh: `延迟 ≥ ${args.minLatency.trim()}ms`,
			labelEn: `Latency ≥ ${args.minLatency.trim()}ms`,
			clear: args.clearLatency,
		});
	}
	if (args.fallbackOnly) {
		chips.push({
			id: "fallback",
			labelZh: "仅看 fallback",
			labelEn: "Fallback only",
			clear: args.clearFallback,
		});
	}
	if (args.hasErrorOnly) {
		chips.push({
			id: "error",
			labelZh: "仅看错误",
			labelEn: "Errors only",
			clear: args.clearErrorOnly,
		});
	}
	if (args.sortMode !== "newest") {
		chips.push({
			id: "sort",
			labelZh: `排序 · ${args.sortMode === "latency" ? "延迟" : "工具数"}`,
			labelEn: `Sort · ${args.sortMode === "latency" ? "Latency" : "Tool calls"}`,
			clear: args.clearSort,
		});
	}
	return chips;
}
