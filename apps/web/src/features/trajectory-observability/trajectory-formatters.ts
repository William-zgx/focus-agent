import {
	type FocusAgentTrajectoryStep,
	safeVisibleText,
} from "@focus-agent/web-sdk";

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
