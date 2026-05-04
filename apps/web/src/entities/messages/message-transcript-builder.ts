import {
	normalizeMessageType,
	normalizeText,
} from "./message-transcript-normalize";
import type {
	ToolActivityItem,
	TranscriptItem,
} from "./message-transcript-types";
import {
	formatToolDetailContent,
	summarizeToolResult,
	totalTokensFromUsageMetadata,
	truncateText,
	uniqueToolNames,
} from "./message-transcript-tool-summary";
import {
	shouldHideStreamingInternalContent,
	visibleAssistantIndexesToHide,
} from "./message-transcript-visibility";

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
