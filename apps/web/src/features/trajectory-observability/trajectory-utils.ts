import {
	FocusAgentRequestError,
	safeVisibleText,
	type FocusAgentTrajectoryStatsRow,
	type FocusAgentTrajectoryStep,
	type FocusAgentTrajectoryTurnDetail,
	type FocusAgentTrajectoryTurnSummary,
} from "@focus-agent/web-sdk";

export type SortMode = "newest" | "latency" | "tool_calls";
export type StatusMode = "all" | "failed" | "succeeded";
export type PresetMode = "failures" | "fallback" | "latency" | "all";
export type FilterChip = {
	id: string;
	labelZh: string;
	labelEn: string;
	clear: () => void;
};
export type CorrelationSignal = {
	id: string;
	labelZh: string;
	labelEn: string;
	value: string;
	tone?: "neutral" | "accent";
};
export type EvidenceMode = "timeline" | "zero_step" | "missing_detail";
export type ReviewSummary = {
	headline: string;
	lead: string;
	status: string;
	createdAt: string;
	evidenceLabel: string;
	stats: Array<{
		id: string;
		labelZh: string;
		labelEn: string;
		value: string;
	}>;
};
export type ActionRailSection = {
	id: string;
	titleZh: string;
	titleEn: string;
	captionZh: string;
	captionEn: string;
	count?: string;
};

export function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null;
}

export function getSearchParams(search?: unknown) {
	if (search instanceof URLSearchParams) {
		return new URLSearchParams(search);
	}
	if (typeof search === "string") {
		return new URLSearchParams(search);
	}
	if (isRecord(search)) {
		const params = new URLSearchParams();
		Object.entries(search).forEach(([key, rawValue]) => {
			if (rawValue === undefined || rawValue === null) return;
			if (Array.isArray(rawValue)) {
				rawValue.forEach((item) => {
					if (item === undefined || item === null) return;
					params.append(key, String(item));
				});
				return;
			}
			params.set(key, String(rawValue));
		});
		return params;
	}
	if (typeof window === "undefined") {
		return new URLSearchParams();
	}
	return new URLSearchParams(window.location.search);
}

export function readSearchParam(key: string, search?: unknown) {
	return getSearchParams(search).get(key) ?? "";
}

export function readInitialSearchParam(key: string, search?: unknown) {
	return readSearchParam(key, search);
}

export function readSearchFlag(
	key: string,
	fallback = false,
	search?: unknown,
) {
	const value = readSearchParam(key, search);
	if (!value) return fallback;
	return value === "1" || value === "true";
}

export function readSearchStatus(search?: unknown): StatusMode {
	const value = readSearchParam("status", search);
	if (value === "all" || value === "failed" || value === "succeeded") {
		return value;
	}
	return "all";
}

export function readSearchSort(search?: unknown): SortMode {
	const value = readSearchParam("sort", search);
	if (value === "newest" || value === "latency" || value === "tool_calls") {
		return value;
	}
	return "newest";
}

export function readSearchState(search?: unknown) {
	return {
		statusFilter: readSearchStatus(search),
		toolFilter: readSearchParam("tool", search),
		threadFilter: readSearchParam("thread", search),
		requestFilter: readSearchParam("request", search),
		traceFilter: readSearchParam("trace", search),
		modelFilter: readSearchParam("model", search),
		minLatency: readSearchParam("minLatency", search),
		fallbackOnly: readSearchFlag("fallbackOnly", false, search),
		hasErrorOnly: readSearchFlag("hasErrorOnly", false, search),
		sortMode: readSearchSort(search),
		selectedTurnId: readSearchParam("turn", search),
	};
}

export function shouldExpandFiltersFromSearch(search?: unknown) {
	const state = readSearchState(search);
	return (
		Boolean(state.toolFilter) ||
		Boolean(state.threadFilter) ||
		Boolean(state.requestFilter) ||
		Boolean(state.traceFilter) ||
		Boolean(state.modelFilter) ||
		Boolean(state.minLatency) ||
		state.fallbackOnly ||
		state.hasErrorOnly ||
		state.statusFilter !== "all" ||
		state.sortMode !== "newest"
	);
}

export function parseNonNegativeNumber(value: string) {
	const text = value.trim();
	if (!text) return undefined;
	const parsed = Number(text);
	if (!Number.isFinite(parsed) || parsed < 0) return undefined;
	return parsed;
}

export function describeTrajectoryError(error: unknown, isChineseUi: boolean) {
	if (error instanceof FocusAgentRequestError) {
		if (error.status === 503) {
			return isChineseUi
				? "当前环境还没有启用 Trajectory observability 后端。请先配置 Postgres trajectory 存储，或在支持该能力的环境里打开复盘台。"
				: "Trajectory observability is not available in this environment yet. Configure the Postgres-backed trajectory store, or open this page in an environment where observability is enabled.";
		}
		if (error.status === 401 || error.status === 403) {
			return isChineseUi
				? "当前账号没有访问复盘台数据的权限。请先确认登录状态和 Bearer Token。"
				: "Your current account cannot access trajectory data. Check the active login session and bearer token first.";
		}
		return isChineseUi
			? `复盘台数据请求失败（${error.status} ${error.statusText}）。`
			: `Trajectory request failed (${error.status} ${error.statusText}).`;
	}
	return isChineseUi
		? "复盘台数据加载失败，请稍后重试。"
		: "Failed to load trajectory data. Please retry in a moment.";
}

export function formatDateTime(
	value?: string | null,
	locale: "zh-CN" | "en-US" = "en-US",
) {
	if (!value) return "—";
	const parsed = new Date(value);
	if (Number.isNaN(parsed.getTime())) return value;
	return new Intl.DateTimeFormat(locale, {
		month: "short",
		day: "numeric",
		hour: "2-digit",
		minute: "2-digit",
	}).format(parsed);
}

export function formatMetric(value: number | undefined, digits = 0) {
	if (typeof value !== "number" || Number.isNaN(value)) return "—";
	return Intl.NumberFormat(undefined, {
		maximumFractionDigits: digits,
		minimumFractionDigits: digits,
	}).format(value);
}

export function formatPercent(value: number | undefined) {
	if (typeof value !== "number" || Number.isNaN(value)) return "—";
	return `${Math.round(value * 100)}%`;
}

export function formatDuration(value?: number | null) {
	if (typeof value !== "number" || Number.isNaN(value)) return "—";
	if (value >= 1000) {
		return `${formatMetric(value / 1000, 2)}s`;
	}
	return `${formatMetric(value, 0)}ms`;
}

export function compactId(value?: string | null) {
	const text = String(value || "").trim();
	if (!text) return "—";
	if (text.length <= 18) return text;
	return `${text.slice(0, 8)}…${text.slice(-6)}`;
}

export function compactQuestion(value?: string | null) {
	const text = String(value || "")
		.replace(/\s+/g, " ")
		.trim();
	if (!text) return "—";
	if (text.length <= 54) return text;
	return `${text.slice(0, 54)}…`;
}

export function compactDetailQuestion(value?: string | null) {
	const text = String(value || "")
		.replace(/\s+/g, " ")
		.trim();
	if (!text) return "—";
	if (text.length <= 160) return text;
	return `${text.slice(0, 160)}…`;
}

function visiblePreviewText(value?: string | null) {
	const text = safeVisibleText(String(value || ""))
		.replace(/\s+/g, " ")
		.trim();
	if (!text || /\breasoning_content\b/i.test(text)) return "";
	return text;
}

export function extractStructuredSummary(value?: string | null) {
	const text = visiblePreviewText(value);
	if (!text) return "";
	return text.length > 260 ? `${text.slice(0, 260)}…` : text;
}

export function stepObservationPreview(value?: string | null) {
	const text = visiblePreviewText(value);
	if (!text) return "—";
	if (text.length <= 140) return text;
	return `${text.slice(0, 140)}…`;
}

export function compactSnippet(value?: string | null, max = 88) {
	const text = visiblePreviewText(value);
	if (!text) return "";
	if (text.length <= max) return text;
	return `${text.slice(0, max)}…`;
}

export function stringifyMetadataValue(value: unknown) {
	if (value === undefined || value === null) return "";
	if (typeof value === "string") return value.trim();
	if (typeof value === "number" || typeof value === "boolean")
		return String(value);
	try {
		const text = JSON.stringify(value);
		if (!text) return "";
		return text.length > 120 ? `${text.slice(0, 120)}…` : text;
	} catch {
		return "";
	}
}

export function findNestedMetadataValue(
	source: unknown,
	aliases: readonly string[],
	options?: { depth?: number; seen?: WeakSet<object> },
): string {
	const depth = options?.depth ?? 0;
	if (depth > 4) return "";
	if (Array.isArray(source)) {
		for (const item of source) {
			const match = findNestedMetadataValue(item, aliases, {
				depth: depth + 1,
				seen: options?.seen,
			});
			if (match) return match;
		}
		return "";
	}
	if (!isRecord(source)) return "";
	const seen = options?.seen ?? new WeakSet<object>();
	if (seen.has(source)) return "";
	seen.add(source);

	for (const alias of aliases) {
		if (alias in source) {
			const match = stringifyMetadataValue(source[alias]);
			if (match) return match;
		}
	}

	for (const value of Object.values(source)) {
		const match = findNestedMetadataValue(value, aliases, {
			depth: depth + 1,
			seen,
		});
		if (match) return match;
	}
	return "";
}

export function findMetadataAcrossSources(
	sources: unknown[],
	aliases: readonly string[],
) {
	for (const source of sources) {
		const match = findNestedMetadataValue(source, aliases);
		if (match) return match;
	}
	return "";
}

export function normalizeStatusFilter(value: StatusMode): string[] | undefined {
	if (value === "all") return undefined;
	return [value];
}

export function statusTone(status?: string | null) {
	if (status === "failed") return "danger";
	if (status === "succeeded") return "success";
	return "neutral";
}

export function severityClass(step: FocusAgentTrajectoryStep) {
	if (step.error) return "is-danger";
	if (step.fallback_used) return "is-warning";
	if (step.cache_hit) return "is-success";
	return "";
}

const BRANCH_ROLE_LABELS: Record<string, { zh: string; en: string }> = {
	main: { zh: "主线", en: "Main" },
	explore_alternatives: { zh: "备选方案", en: "Alternative path" },
	deep_dive: { zh: "深入分析", en: "Deep dive" },
	execute: { zh: "执行", en: "Execution" },
	verify: { zh: "验证", en: "Verification" },
	writeup: { zh: "整理", en: "Writeup" },
};

const SCENE_LABELS: Record<string, { zh: string; en: string }> = {
	long_dialog_research: { zh: "长对话研究", en: "Long dialog research" },
	technical_deep_dive: { zh: "技术深挖", en: "Technical deep dive" },
};

export function humanizeKey(value?: string | null) {
	const text = String(value || "").trim();
	if (!text) return "—";
	return text.replace(/[_-]+/g, " ");
}

export function labelFromMap(
	value: string | null | undefined,
	map: Record<string, { zh: string; en: string }>,
	isChineseUi: boolean,
) {
	const normalized = String(value || "").trim();
	if (!normalized) return "—";
	const mapped = map[normalized];
	if (mapped) {
		return isChineseUi ? mapped.zh : mapped.en;
	}
	return humanizeKey(normalized);
}

export function formatBranchRoleLabel(
	value: string | null | undefined,
	isChineseUi: boolean,
) {
	return labelFromMap(value, BRANCH_ROLE_LABELS, isChineseUi);
}

export function formatSceneLabel(
	value: string | null | undefined,
	isChineseUi: boolean,
) {
	return labelFromMap(value, SCENE_LABELS, isChineseUi);
}

export function getDominantTool(trajectory: FocusAgentTrajectoryStep[]) {
	const counts = new Map<string, number>();
	trajectory.forEach((step) => {
		counts.set(step.tool, (counts.get(step.tool) ?? 0) + 1);
	});
	return (
		[...counts.entries()].sort((left, right) => right[1] - left[1])[0]?.[0] ??
		"—"
	);
}

export function getLongestStep(trajectory: FocusAgentTrajectoryStep[]) {
	if (!trajectory.length) return null;
	return trajectory.reduce((current, next) =>
		(next.duration_ms ?? 0) > (current.duration_ms ?? 0) ? next : current,
	);
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

export function topToolRows(
	byTool: FocusAgentTrajectoryStatsRow[] | undefined,
) {
	return [...(byTool ?? [])]
		.sort((left, right) => (right.turn_count ?? 0) - (left.turn_count ?? 0))
		.slice(0, 4);
}

export function topStatsRows(
	rows: FocusAgentTrajectoryStatsRow[] | undefined,
	limit = 4,
) {
	return [...(rows ?? [])]
		.sort((left, right) => {
			const leftCount = left.turn_count ?? left.step_count ?? 0;
			const rightCount = right.turn_count ?? right.step_count ?? 0;
			return rightCount - leftCount;
		})
		.slice(0, limit);
}

export function ratio(numerator?: number, denominator?: number) {
	if (
		typeof numerator !== "number" ||
		typeof denominator !== "number" ||
		denominator <= 0
	) {
		return undefined;
	}
	return numerator / denominator;
}

export function findStepRuntimeSignal(
	step: FocusAgentTrajectoryStep,
	aliases: readonly string[],
) {
	return findNestedMetadataValue(step.runtime, aliases);
}

export function buildSelectedSignals(
	selected: FocusAgentTrajectoryTurnDetail | null,
) {
	if (!selected) {
		return {
			errorSteps: 0,
			fallbackSteps: 0,
			cacheSteps: 0,
			parallelSteps: 0,
			dominantTool: "—",
			longestStep: null as FocusAgentTrajectoryStep | null,
		};
	}
	const errorSteps = selected.trajectory.filter((step) =>
		Boolean(step.error),
	).length;
	const fallbackSteps = selected.trajectory.filter(
		(step) => step.fallback_used,
	).length;
	const cacheSteps = selected.trajectory.filter(
		(step) => step.cache_hit,
	).length;
	const parallelSteps = selected.trajectory.filter((step) =>
		Boolean(step.parallel_batch_size),
	).length;
	return {
		errorSteps,
		fallbackSteps,
		cacheSteps,
		parallelSteps,
		dominantTool: getDominantTool(selected.trajectory),
		longestStep: getLongestStep(selected.trajectory),
	};
}

export function buildTurnSummary(
	item: FocusAgentTrajectoryTurnSummary,
	isChineseUi: boolean,
) {
	const errorText = compactSnippet(item?.error);
	if (errorText) {
		return isChineseUi ? `错误 · ${errorText}` : `Error · ${errorText}`;
	}
	const summaryText = compactSnippet(extractStructuredSummary(item?.answer));
	if (summaryText) return summaryText;
	return isChineseUi
		? `${formatSceneLabel(item?.scene, true)} · ${item?.branch_role ? formatBranchRoleLabel(item.branch_role, true) : "未标记角色"}`
		: `${formatSceneLabel(item?.scene, false)} · ${item?.branch_role ? formatBranchRoleLabel(item.branch_role, false) : "No branch role"}`;
}

export function buildCorrelationSignals(
	selected: FocusAgentTrajectoryTurnDetail | null,
): CorrelationSignal[] {
	if (!selected) return [];

	const runtimeSources = selected.trajectory.map((step) => step.runtime);
	const metadataSources = [
		selected.plan_meta,
		selected.metrics,
		selected.reflection,
		...runtimeSources,
	];
	const requestId =
		selected.request_id ||
		findMetadataAcrossSources(metadataSources, ["request_id", "requestId"]);
	const traceId =
		selected.trace_id ||
		findMetadataAcrossSources(metadataSources, ["trace_id", "traceId"]);
	const spanId =
		selected.root_span_id ||
		findMetadataAcrossSources(metadataSources, [
			"span_id",
			"spanId",
			"root_span_id",
			"rootSpanId",
		]);
	const environment =
		selected.environment ||
		findMetadataAcrossSources(metadataSources, ["environment", "env"]);
	const deployment =
		selected.deployment ||
		findMetadataAcrossSources(metadataSources, [
			"deployment",
			"deployment_name",
		]);
	const appVersion =
		selected.app_version ||
		findMetadataAcrossSources(metadataSources, [
			"app_version",
			"appVersion",
			"version",
		]);

	return [
		{
			id: "turn",
			labelZh: "Turn ID",
			labelEn: "Turn ID",
			value: selected.id,
			tone: "accent",
		},
		{
			id: "thread",
			labelZh: "线程",
			labelEn: "Thread",
			value: selected.thread_id,
		},
		{
			id: "root",
			labelZh: "根线程",
			labelEn: "Root thread",
			value: selected.root_thread_id,
		},
		...(selected.parent_thread_id
			? [
					{
						id: "parent",
						labelZh: "父线程",
						labelEn: "Parent thread",
						value: selected.parent_thread_id,
					} satisfies CorrelationSignal,
				]
			: []),
		...(selected.branch_id
			? [
					{
						id: "branch",
						labelZh: "分支 ID",
						labelEn: "Branch ID",
						value: selected.branch_id,
					} satisfies CorrelationSignal,
				]
			: []),
		...(requestId
			? [
					{
						id: "request",
						labelZh: "Request ID",
						labelEn: "Request ID",
						value: requestId,
						tone: "accent",
					} satisfies CorrelationSignal,
				]
			: []),
		...(traceId
			? [
					{
						id: "trace",
						labelZh: "Trace ID",
						labelEn: "Trace ID",
						value: traceId,
						tone: "accent",
					} satisfies CorrelationSignal,
				]
			: []),
		...(spanId
			? [
					{
						id: "span",
						labelZh: "Span ID",
						labelEn: "Span ID",
						value: spanId,
					} satisfies CorrelationSignal,
				]
			: []),
		...(environment
			? [
					{
						id: "env",
						labelZh: "环境",
						labelEn: "Environment",
						value: environment,
					} satisfies CorrelationSignal,
				]
			: []),
		...(deployment
			? [
					{
						id: "deployment",
						labelZh: "部署",
						labelEn: "Deployment",
						value: deployment,
					} satisfies CorrelationSignal,
				]
			: []),
		...(appVersion
			? [
					{
						id: "version",
						labelZh: "版本",
						labelEn: "App version",
						value: appVersion,
					} satisfies CorrelationSignal,
				]
			: []),
	];
}

export function findCorrelationSignalValue(
	signals: CorrelationSignal[],
	id: string,
) {
	return signals.find((signal) => signal.id === id)?.value ?? "";
}

export function orderTrajectoryItems(
	items: FocusAgentTrajectoryTurnSummary[] | undefined,
	sortMode: SortMode,
) {
	const ordered = [...(items ?? [])];
	if (sortMode === "latency") {
		ordered.sort(
			(left, right) => (right.latency_ms ?? 0) - (left.latency_ms ?? 0),
		);
		return ordered;
	}
	if (sortMode === "tool_calls") {
		ordered.sort(
			(left, right) => (right.tool_calls ?? 0) - (left.tool_calls ?? 0),
		);
		return ordered;
	}
	return ordered;
}
