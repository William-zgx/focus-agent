import type {
	FocusAgentStreamStep,
	FocusAgentToolCallEvent,
	FocusAgentToolEvent,
} from "@focus-agent/web-sdk";
import { useMemo } from "react";

import { toolEventLabel } from "./message-list-helpers";
import { ToolActivityCard } from "./message-list-tool-activity-card";
import type {
	ProcessingStepEntry,
	ToolActivityItem,
} from "./message-transcript";
import { normalizeText } from "./message-transcript";
import {
	formatToolDetailContent,
	summarizeToolResult,
	truncateText,
	uniqueToolNames,
} from "./message-transcript-tool-summary";

function streamStatusTitle(
	hasVisibleText: boolean,
	hasToolActivity: boolean,
	hasReasoningText: boolean,
	isChineseUi: boolean,
) {
	if (hasVisibleText) {
		return isChineseUi ? "处理过程" : "Processing";
	}
	if (hasToolActivity) {
		return isChineseUi ? "正在处理请求" : "Processing the request";
	}
	if (hasReasoningText) {
		return isChineseUi ? "正在思考" : "Thinking";
	}
	return isChineseUi ? "已收到，正在思考" : "Message received, thinking";
}

function streamStatusNote(
	hasVisibleText: boolean,
	hasToolActivity: boolean,
	hasReasoningText: boolean,
	isChineseUi: boolean,
) {
	if (hasVisibleText) {
		return isChineseUi
			? "回答已开始输出，处理步骤默认折叠保留。"
			: "The reply is visible now. Processing details stay folded here.";
	}
	if (hasToolActivity) {
		return isChineseUi
			? "工具步骤已经开始，默认折叠显示。"
			: "Tool steps are underway and folded by default.";
	}
	if (hasReasoningText) {
		return isChineseUi
			? "Agent 正在整理上下文和回答结构。"
			: "The agent is organizing context and shaping the reply.";
	}
	return isChineseUi
		? "消息已经发送成功，系统正在建立本轮响应。"
		: "Your message has been sent. The system is preparing this turn.";
}

function toneForStatus(status: FocusAgentStreamStep["status"]) {
	if (status === "failed") {
		return "danger";
	}
	if (status === "completed") {
		return "success";
	}
	if (status === "running") {
		return "warn";
	}
	return "neutral";
}

function stringifyDetailContent(value: unknown) {
	if (typeof value === "undefined" || value === null) {
		return "";
	}
	if (typeof value === "string") {
		return value;
	}
	try {
		return JSON.stringify(value, null, 2);
	} catch {
		return String(value);
	}
}

function stepFromStreamStep(step: FocusAgentStreamStep): ProcessingStepEntry {
	const detailContent =
		typeof step.result === "undefined"
			? normalizeText(step.content)
			: stringifyDetailContent(step.result);
	const detail = detailContent ? formatToolDetailContent(detailContent) : null;
	return {
		id: step.id,
		kind: step.kind,
		label: normalizeText(step.label) || normalizeText(step.name) || step.kind,
		status: step.status,
		tone: toneForStatus(step.status),
		content: truncateText(
			normalizeText(step.content) ||
				normalizeText(step.argsText) ||
				summarizeToolResult(detailContent),
			120,
		),
		detail: detail?.content
			? {
					id: `${step.id}-detail`,
					label:
						normalizeText(step.name) || normalizeText(step.label) || step.kind,
					content: detail.content,
					language: detail.language,
				}
			: undefined,
	};
}

function stepsFromLegacyStreamEvents({
	isChineseUi,
	reasoningText,
	toolCalls,
	toolEvents,
}: {
	isChineseUi: boolean;
	reasoningText?: string;
	toolCalls?: FocusAgentToolCallEvent[];
	toolEvents?: FocusAgentToolEvent[];
}) {
	const steps = new Map<string, ProcessingStepEntry>();

	if (reasoningText?.trim()) {
		steps.set("stream-reasoning", {
			id: "stream-reasoning",
			kind: "reasoning",
			label: isChineseUi ? "整理推理链路" : "Reasoning",
			status: "running",
			tone: "warn",
			content: truncateText(reasoningText, 120),
		});
	}

	for (const [index, call] of (toolCalls ?? []).entries()) {
		const toolName = String(
			call.data.name || call.data.tool_name || "tool",
		).trim();
		const namespace = Array.isArray(call.data.namespace)
			? call.data.namespace.join("/")
			: "";
		const id = String(
			call.data.tool_call_id ||
				call.data.id ||
				(namespace && toolName ? `${namespace}:${toolName}` : "") ||
				`stream-tool-call-${index}`,
		);
		steps.set(id, {
			id,
			kind: "tool",
			label: isChineseUi ? `规划调用 ${toolName}` : `Planning ${toolName}`,
			status: "running",
			tone: "warn",
			content: truncateText(String(call.data.args_delta || ""), 120),
		});
	}

	for (const [index, event] of (toolEvents ?? []).entries()) {
		const toolName = String(event.data.tool_name || event.data.name || "tool");
		const namespace = Array.isArray(event.data.namespace)
			? event.data.namespace.join("/")
			: "";
		const id = String(
			event.data.tool_call_id ||
				event.data.id ||
				(namespace && toolName ? `${namespace}:${toolName}` : "") ||
				`stream-tool-event-${index}`,
		);
		const status =
			event.event === "tool.error"
				? "failed"
				: event.event === "tool.end" || event.event === "tool.result"
					? "completed"
					: "running";
		const output =
			typeof event.data.output === "string"
				? event.data.output
				: typeof event.data.output === "undefined"
					? String(event.data.message || "")
					: stringifyDetailContent(event.data.output);
		const detail = output ? formatToolDetailContent(output) : null;
		steps.set(id, {
			id,
			kind: "tool",
			label: toolEventLabel(event, isChineseUi),
			status,
			tone: toneForStatus(status),
			content: truncateText(
				String(event.data.message || "") || summarizeToolResult(output),
				120,
			),
			detail: detail?.content
				? {
						id: `${id}-detail`,
						label: String(
							event.data.tool_name ||
								event.data.name ||
								event.data.event ||
								"tool",
						),
						content: detail.content,
						language: detail.language,
					}
				: undefined,
		});
	}

	return [...steps.values()];
}

function buildStreamActivity({
	isChineseUi,
	processingSteps,
	reasoningText,
	toolCalls,
	toolEvents,
}: {
	isChineseUi: boolean;
	processingSteps?: FocusAgentStreamStep[];
	reasoningText?: string;
	toolCalls?: FocusAgentToolCallEvent[];
	toolEvents?: FocusAgentToolEvent[];
}): ToolActivityItem {
	const steps =
		processingSteps && processingSteps.length > 0
			? processingSteps.map(stepFromStreamStep)
			: stepsFromLegacyStreamEvents({
					isChineseUi,
					reasoningText,
					toolCalls,
					toolEvents,
				});
	const toolNames = uniqueToolNames(
		steps
			.filter((step) => step.kind === "tool")
			.map((step) =>
				step.label.replace(/^(Planning|Preparing|Running|Completed)\s+/i, ""),
			),
	);
	return {
		kind: "tool-activity",
		id: "stream-processing",
		toolNames,
		summaryText: "",
		details: steps.flatMap((step) => (step.detail ? [step.detail] : [])),
		steps,
	};
}

export function AgentRunBubble({
	isStreaming,
	reasoningText,
	toolCalls,
	toolEvents,
	processingSteps,
	visibleText,
	isChineseUi,
}: {
	isStreaming: boolean;
	reasoningText?: string;
	toolCalls?: FocusAgentToolCallEvent[];
	toolEvents?: FocusAgentToolEvent[];
	processingSteps?: FocusAgentStreamStep[];
	visibleText?: string;
	isChineseUi: boolean;
}) {
	const hasVisibleText = Boolean(visibleText?.trim());
	const hasReasoningText = Boolean(reasoningText?.trim());
	const hasToolActivity = Boolean(
		(processingSteps?.length ?? 0) ||
			(toolCalls?.length ?? 0) ||
			(toolEvents?.length ?? 0),
	);
	const activity = useMemo(
		() =>
			buildStreamActivity({
				isChineseUi,
				processingSteps,
				reasoningText,
				toolCalls,
				toolEvents,
			}),
		[isChineseUi, processingSteps, reasoningText, toolCalls, toolEvents],
	);

	if (!isStreaming && activity.steps.length === 0) {
		return null;
	}
	if (hasVisibleText && activity.steps.length === 0) {
		return null;
	}

	return (
		<ToolActivityCard
			activity={activity}
			isChineseUi={isChineseUi}
			note={streamStatusNote(
				hasVisibleText,
				hasToolActivity,
				hasReasoningText,
				isChineseUi,
			)}
			title={streamStatusTitle(
				hasVisibleText,
				hasToolActivity,
				hasReasoningText,
				isChineseUi,
			)}
		/>
	);
}
