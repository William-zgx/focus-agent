import { looksLikeTextualToolCallArtifact } from "@focus-agent/web-sdk";

interface TranscriptDisplayMessage {
	kind: "message";
	id: string;
	type: string;
	content: string;
	totalTokens?: number;
}

interface ToolDetailEntry {
	id: string;
	label: string;
	content: string;
	language: string;
}

export interface ToolActivityItem {
	kind: "tool-activity";
	id: string;
	toolNames: string[];
	summaryText: string;
	details: ToolDetailEntry[];
}

export type TranscriptItem = TranscriptDisplayMessage | ToolActivityItem;

export function normalizeMessageType(type: unknown) {
	return String(type || "")
		.trim()
		.toLowerCase();
}

export function normalizeText(value: unknown) {
	return String(value ?? "").trim();
}

function looksLikeInternalToolMarkup(value: unknown) {
	return looksLikeTextualToolCallArtifact(normalizeText(value));
}

function looksLikeToolPlanningPayload(value: unknown) {
	const text = normalizeText(value);
	if (!text) {
		return false;
	}

	const lowered = text.toLowerCase();
	if (
		(lowered.includes('"steps"') || lowered.includes('"step"')) &&
		lowered.includes('"expected_tools"')
	) {
		return true;
	}

	const parsed = parseJsonValue(text);
	if (!parsed || typeof parsed !== "object") {
		return false;
	}

	if (!("steps" in parsed) || !Array.isArray(parsed.steps)) {
		return false;
	}

	return parsed.steps.some((step) => {
		if (!step || typeof step !== "object") {
			return false;
		}
		const record = step as Record<string, unknown>;
		return (
			Array.isArray(record.expected_tools) || typeof record.goal === "string"
		);
	});
}

export function shouldHideStreamingInternalContent(value: unknown) {
	return (
		looksLikeInternalToolMarkup(value) || looksLikeToolPlanningPayload(value)
	);
}

function totalTokensFromUsageMetadata(value: unknown) {
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

function truncateText(text: string, maxLength = 220) {
	const normalized = normalizeText(text).replace(/\s+/g, " ");
	if (!normalized) {
		return "";
	}
	if (normalized.length <= maxLength) {
		return normalized;
	}
	return `${normalized.slice(0, maxLength - 1).trimEnd()}…`;
}

function parseJsonValue(text: string): unknown | null {
	const candidate = normalizeText(text);
	if (!candidate) {
		return null;
	}
	try {
		return JSON.parse(candidate);
	} catch {
		return null;
	}
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

function summarizeToolResult(content: string) {
	const parsed = parseJsonValue(content);
	if (parsed !== null) {
		return truncateText(extractToolSummaryCandidate(parsed));
	}
	return truncateText(content);
}

function formatToolDetailContent(content: string) {
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

function uniqueToolNames(toolNames: string[]) {
	return [
		...new Set(toolNames.map((item) => normalizeText(item)).filter(Boolean)),
	];
}

function visibleAssistantIndexesToHide(
	messages: Array<Record<string, unknown>>,
) {
	const hidden = new Set<number>();
	let visibleIndexesInTurn: number[] = [];

	function closeTurn() {
		for (const index of visibleIndexesInTurn.slice(0, -1)) {
			hidden.add(index);
		}
		visibleIndexesInTurn = [];
	}

	for (let index = 0; index < messages.length; index += 1) {
		const message = messages[index] ?? {};
		const type = normalizeMessageType(message.type);

		if (type === "human") {
			closeTurn();
			continue;
		}

		const toolCalls = Array.isArray(message.tool_calls)
			? (message.tool_calls as Array<Record<string, unknown>>)
			: [];
		const content = String(message.content ?? "");
		if (
			type === "ai" &&
			toolCalls.length === 0 &&
			normalizeText(content) &&
			!shouldHideStreamingInternalContent(content)
		) {
			visibleIndexesInTurn.push(index);
		}
	}

	closeTurn();
	return hidden;
}

export function buildTranscriptItems(
	messages: Array<Record<string, unknown>>,
	assistantMessage?: string | null,
): TranscriptItem[] {
	const items: TranscriptItem[] = [];
	let pendingToolActivity: ToolActivityItem | null = null;
	let latestHumanIndex = -1;
	let hasVisibleAssistantAfterLatestHuman = false;
	const hiddenVisibleAssistantIndexes = visibleAssistantIndexesToHide(messages);

	for (let index = 0; index < messages.length; index += 1) {
		if (normalizeMessageType(messages[index]?.type) === "human") {
			latestHumanIndex = index;
		}
	}

	function flushToolActivity() {
		if (!pendingToolActivity) {
			return;
		}
		pendingToolActivity.toolNames = uniqueToolNames(
			pendingToolActivity.toolNames,
		);
		pendingToolActivity.summaryText = truncateText(
			pendingToolActivity.summaryText,
		);
		items.push(pendingToolActivity);
		pendingToolActivity = null;
	}

	for (let index = 0; index < messages.length; index += 1) {
		const message = messages[index] ?? {};
		const type = normalizeMessageType(message.type);
		const content = String(message.content ?? "");
		const messageId = String(message.id ?? `${type || "message"}-${index}`);
		const toolCalls = Array.isArray(message.tool_calls)
			? (message.tool_calls as Array<Record<string, unknown>>)
			: [];

		if (type === "ai" && toolCalls.length > 0) {
			flushToolActivity();
			pendingToolActivity = {
				kind: "tool-activity",
				id: `tool-activity-${messageId}`,
				toolNames: toolCalls
					.map((call) => normalizeText(call.name))
					.filter(Boolean),
				summaryText: "",
				details: [],
			};
			continue;
		}

		if (type === "tool") {
			if (!pendingToolActivity) {
				pendingToolActivity = {
					kind: "tool-activity",
					id: `tool-activity-${messageId}`,
					toolNames: [],
					summaryText: "",
					details: [],
				};
			}

			const toolName = normalizeText(message.name);
			if (toolName) {
				pendingToolActivity.toolNames.push(toolName);
			}
			if (!pendingToolActivity.summaryText) {
				pendingToolActivity.summaryText = summarizeToolResult(content);
			}
			const detail = formatToolDetailContent(content);
			if (detail.content) {
				pendingToolActivity.details.push({
					id: `${pendingToolActivity.id}-detail-${pendingToolActivity.details.length}`,
					label: toolName || `tool-${pendingToolActivity.details.length + 1}`,
					content: detail.content,
					language: detail.language,
				});
			}
			continue;
		}

		flushToolActivity();

		if (
			!normalizeText(content) ||
			shouldHideStreamingInternalContent(content)
		) {
			continue;
		}
		if (type === "ai" && hiddenVisibleAssistantIndexes.has(index)) {
			continue;
		}

		const item = {
			kind: "message",
			id: messageId,
			type: type || "message",
			content,
			totalTokens:
				type === "ai"
					? totalTokensFromUsageMetadata(message.usage_metadata)
					: 0,
		} as const;
		items.push(item);
		if (type === "ai" && index > latestHumanIndex) {
			hasVisibleAssistantAfterLatestHuman = true;
		}
	}

	flushToolActivity();

	const normalizedAssistantMessage = normalizeText(assistantMessage);
	const shouldHideAssistantFallback = shouldHideStreamingInternalContent(
		normalizedAssistantMessage,
	);
	const hasVisibleAssistantMessage = items.some(
		(item) =>
			item.kind === "message" &&
			normalizeMessageType(item.type) === "ai" &&
			normalizeText(item.content) === normalizedAssistantMessage,
	);

	if (
		normalizedAssistantMessage &&
		!hasVisibleAssistantMessage &&
		!hasVisibleAssistantAfterLatestHuman &&
		!shouldHideAssistantFallback
	) {
		items.push({
			kind: "message",
			id: "assistant-message-fallback",
			type: "ai",
			content: normalizedAssistantMessage,
			totalTokens: 0,
		});
		return items;
	}

	return items;
}
