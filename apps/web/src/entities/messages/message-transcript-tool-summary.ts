import { normalizeText, parseJsonValue } from "./message-transcript-normalize";

export function totalTokensFromUsageMetadata(value: unknown) {
	if (!value || typeof value !== "object") {
		return 0;
	}
	const record = value as Record<string, unknown>;
	const total = Number(record.total_tokens ?? 0);
	if (Number.isFinite(total) && total > 0) {
		return Math.round(total);
	}
	const input = Number(record.input_tokens ?? 0);
	const output = Number(record.output_tokens ?? 0);
	const sum =
		(Number.isFinite(input) ? input : 0) +
		(Number.isFinite(output) ? output : 0);
	return sum > 0 ? Math.round(sum) : 0;
}

export function truncateText(text: string, maxLength = 220) {
	const normalized = normalizeText(text).replace(/\s+/g, " ");
	if (!normalized) {
		return "";
	}
	if (normalized.length <= maxLength) {
		return normalized;
	}
	return `${normalized.slice(0, maxLength - 1).trimEnd()}…`;
}

function extractToolSummaryCandidate(value: unknown): string {
	if (typeof value === "string") {
		return normalizeText(value);
	}
	if (typeof value === "number" || typeof value === "boolean") {
		return String(value);
	}
	if (Array.isArray(value)) {
		for (const item of value) {
			const candidate = extractToolSummaryCandidate(item);
			if (candidate) {
				return candidate;
			}
		}
		return "";
	}
	if (!value || typeof value !== "object") {
		return "";
	}

	const record = value as Record<string, unknown>;
	for (const key of [
		"answer",
		"summary",
		"message",
		"content",
		"result",
		"output",
		"text",
	]) {
		const candidate = extractToolSummaryCandidate(record[key]);
		if (candidate) {
			return candidate;
		}
	}

	const results = record.results;
	if (Array.isArray(results) && results.length > 0) {
		for (const item of results) {
			if (!item || typeof item !== "object") {
				continue;
			}
			const resultRecord = item as Record<string, unknown>;
			const candidate =
				extractToolSummaryCandidate(resultRecord.content) ||
				extractToolSummaryCandidate(resultRecord.snippet) ||
				extractToolSummaryCandidate(resultRecord.title);
			if (candidate) {
				return candidate;
			}
		}
	}

	return "";
}

export function summarizeToolResult(content: string) {
	const parsed = parseJsonValue(content);
	if (parsed !== null) {
		return truncateText(extractToolSummaryCandidate(parsed));
	}
	return truncateText(content);
}

export function formatToolDetailContent(content: string) {
	const parsed = parseJsonValue(content);
	if (parsed !== null) {
		return {
			content: JSON.stringify(parsed, null, 2),
			language: "json",
		};
	}
	return {
		content: normalizeText(content),
		language: "text",
	};
}

export function uniqueToolNames(toolNames: string[]) {
	return [
		...new Set(toolNames.map((item) => normalizeText(item)).filter(Boolean)),
	];
}
