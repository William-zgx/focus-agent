import { safeVisibleText } from "@focus-agent/web-sdk";

import {
	normalizeMessageType,
	normalizeText,
} from "./message-transcript-normalize";
import type {
	ProcessingStepEntry,
	ToolActivityItem,
	ToolDetailEntry,
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

	function createToolActivity(id: string): ToolActivityItem {
		return {
			kind: "tool-activity",
			id,
			toolNames: [],
			summaryText: "",
			details: [],
			steps: [],
		};
	}

	function toolCallId(call: Record<string, unknown>, fallback: string) {
		return (
			normalizeText(call.id) || normalizeText(call.tool_call_id) || fallback
		);
	}

	function toolCallName(call: Record<string, unknown>) {
		return (
			normalizeText(call.name) ||
			normalizeText(
				(call.function as Record<string, unknown> | undefined)?.name,
			)
		);
	}

	function toolCallArgsText(call: Record<string, unknown>) {
		const args =
			call.args ??
			(call.function as Record<string, unknown> | undefined)?.arguments ??
			call.arguments;
		if (typeof args === "string") {
			return normalizeText(args);
		}
		if (args && typeof args === "object") {
			return JSON.stringify(args, null, 2);
		}
		return "";
	}

	function upsertToolStep(
		activity: ToolActivityItem,
		step: ProcessingStepEntry,
	) {
		const existingIndex = activity.steps.findIndex(
			(item) => item.id === step.id,
		);
		if (existingIndex >= 0) {
			activity.steps[existingIndex] = {
				...activity.steps[existingIndex],
				...step,
			};
			return;
		}
		activity.steps.push(step);
	}

	function completeMatchingToolStep(
		activity: ToolActivityItem,
		toolCallId: string,
		toolName: string,
		detail: ToolDetailEntry | null,
		content: string,
		hasFailed: boolean,
	) {
		const existingIndex = activity.steps.findIndex(
			(step) =>
				step.id === toolCallId ||
				(step.kind === "tool" &&
					step.label === toolName &&
					step.status !== "completed"),
		);
		const label = toolName || `tool-${activity.steps.length + 1}`;
		const step: ProcessingStepEntry = {
			id: toolCallId || `${activity.id}-step-${activity.steps.length}`,
			kind: "tool",
			label,
			status: hasFailed ? "failed" : "completed",
			tone: hasFailed ? "danger" : "success",
			content: summarizeToolResult(content),
			detail: detail ?? undefined,
		};
		if (existingIndex >= 0) {
			const existingStep = activity.steps[existingIndex];
			activity.steps[existingIndex] = {
				...existingStep,
				...step,
				id: existingStep.id,
				label: toolName || existingStep.label || step.label,
			};
			return;
		}
		activity.steps.push(step);
	}

	for (let index = 0; index < messages.length; index += 1) {
		const message = messages[index] ?? {};
		const type = normalizeMessageType(message.type);
		const rawContent = String(message.content ?? "");
		const content = type === "tool" ? rawContent : safeVisibleText(rawContent);
		const messageId = String(message.id ?? `${type || "message"}-${index}`);
		const toolCalls = Array.isArray(message.tool_calls)
			? (message.tool_calls as Array<Record<string, unknown>>)
			: [];

		if (type === "ai" && toolCalls.length > 0) {
			flushToolActivity();
			pendingToolActivity = createToolActivity(`tool-activity-${messageId}`);
			for (const [callIndex, call] of toolCalls.entries()) {
				const toolName = toolCallName(call);
				if (toolName) {
					pendingToolActivity.toolNames.push(toolName);
				}
				const argsText = toolCallArgsText(call);
				upsertToolStep(pendingToolActivity, {
					id: toolCallId(call, `${pendingToolActivity.id}-call-${callIndex}`),
					kind: "tool",
					label: toolName || `tool-${callIndex + 1}`,
					status: "running",
					tone: "warn",
					content: argsText,
				});
			}
			continue;
		}

		if (type === "tool") {
			if (!pendingToolActivity) {
				pendingToolActivity = createToolActivity(`tool-activity-${messageId}`);
			}

			const toolName = normalizeText(message.name);
			const toolCallId = normalizeText(message.tool_call_id) || messageId;
			const hasFailed = ["error", "failed"].includes(
				normalizeText(message.status).toLowerCase(),
			);
			if (toolName) {
				pendingToolActivity.toolNames.push(toolName);
			}
			if (!pendingToolActivity.summaryText) {
				pendingToolActivity.summaryText = summarizeToolResult(content);
			}
			const matchedStep = pendingToolActivity.steps.find(
				(step) =>
					step.id === toolCallId ||
					(Boolean(toolName) &&
						step.kind === "tool" &&
						step.label === toolName &&
						step.status !== "completed"),
			);
			const detail = formatToolDetailContent(content);
			let detailEntry: ToolDetailEntry | null = null;
			if (detail.content) {
				detailEntry = {
					id: `${pendingToolActivity.id}-detail-${pendingToolActivity.details.length}`,
					label:
						toolName ||
						matchedStep?.label ||
						`tool-${pendingToolActivity.details.length + 1}`,
					content: detail.content,
					language: detail.language,
				};
				pendingToolActivity.details.push(detailEntry);
			}
			completeMatchingToolStep(
				pendingToolActivity,
				toolCallId,
				toolName,
				detailEntry,
				content,
				hasFailed,
			);
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

	const normalizedAssistantMessage = normalizeText(
		safeVisibleText(assistantMessage ?? ""),
	);
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
