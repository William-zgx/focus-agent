import type { FocusAgentStreamStep } from "@focus-agent/web-sdk";
import { useMemo } from "react";

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

const PREP_TASK_NAMES = new Set([
	"bootstrap_turn",
	"retrieve_memory",
	"assemble_context",
	"role_route_dry_run",
	"delegation_governance",
	"plan",
]);

const WRAP_UP_TASK_NAMES = new Set([
	"summarize_turn",
	"extract_memories",
	"write_memories",
	"maybe_interrupt_for_merge",
]);

function streamStepSourceName(step: FocusAgentStreamStep) {
	return normalizeText(step.name) || normalizeText(step.label);
}

function streamStepLabel(step: FocusAgentStreamStep, isChineseUi: boolean) {
	const sourceName = streamStepSourceName(step);
	if (step.kind === "reasoning") {
		return isChineseUi ? "组织回答思路" : "Reasoning";
	}
	if (sourceName === "agent_loop") {
		return isChineseUi ? "生成回答" : "Generate reply";
	}
	if (sourceName === "summarize_turn") {
		return isChineseUi ? "整理本轮结果" : "Summarize turn";
	}
	if (sourceName === "extract_memories" || sourceName === "write_memories") {
		return isChineseUi ? "更新记忆" : "Update memory";
	}
	if (sourceName === "maybe_interrupt_for_merge") {
		return isChineseUi ? "检查分支切换" : "Check branch handoff";
	}
	return normalizeText(step.label) || normalizeText(step.name) || step.kind;
}

function aggregateStepStatus(steps: FocusAgentStreamStep[]) {
	if (steps.some((step) => step.status === "failed")) {
		return "failed";
	}
	if (steps.some((step) => step.status === "running")) {
		return "running";
	}
	if (steps.some((step) => step.status === "pending")) {
		return "pending";
	}
	return "completed";
}

function compactStreamProcessingSteps(
	processingSteps: FocusAgentStreamStep[] | undefined,
	isChineseUi: boolean,
) {
	const steps = processingSteps ?? [];
	const prepSteps = steps.filter(
		(step) =>
			step.kind === "task" && PREP_TASK_NAMES.has(streamStepSourceName(step)),
	);
	const wrapUpSteps = steps.filter(
		(step) =>
			step.kind === "task" &&
			WRAP_UP_TASK_NAMES.has(streamStepSourceName(step)),
	);
	if (prepSteps.length === 0 && wrapUpSteps.length === 0) {
		return steps;
	}

	const compactedPrepStep: FocusAgentStreamStep = {
		id: "stream-prep",
		kind: "task",
		label: isChineseUi ? "准备上下文" : "Prepare context",
		status: aggregateStepStatus(prepSteps),
		name: "stream_prep",
	};
	const compactedWrapUpStep: FocusAgentStreamStep = {
		id: "stream-wrap-up",
		kind: "task",
		label: isChineseUi ? "保存结果" : "Save result",
		status: aggregateStepStatus(wrapUpSteps),
		name: "stream_wrap_up",
	};

	const compactedSteps: FocusAgentStreamStep[] = [];
	let prepInserted = false;
	let wrapUpInserted = false;
	for (const step of steps) {
		const sourceName = streamStepSourceName(step);
		const isPrepStep = step.kind === "task" && PREP_TASK_NAMES.has(sourceName);
		if (isPrepStep) {
			if (!prepInserted) {
				compactedSteps.push(compactedPrepStep);
				prepInserted = true;
			}
			continue;
		}
		const isWrapUpStep =
			step.kind === "task" && WRAP_UP_TASK_NAMES.has(sourceName);
		if (isWrapUpStep) {
			if (!wrapUpInserted) {
				compactedSteps.push(compactedWrapUpStep);
				wrapUpInserted = true;
			}
			continue;
		}
		compactedSteps.push(step);
	}
	return compactedSteps;
}

function stepFromStreamStep(
	step: FocusAgentStreamStep,
	isChineseUi: boolean,
): ProcessingStepEntry {
	const detailContent =
		typeof step.result === "undefined"
			? normalizeText(step.content)
			: stringifyDetailContent(step.result);
	const detail = detailContent ? formatToolDetailContent(detailContent) : null;
	return {
		id: step.id,
		kind: step.kind,
		label: streamStepLabel(step, isChineseUi),
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

function buildStreamActivity({
	isChineseUi,
	processingSteps,
}: {
	processingSteps?: FocusAgentStreamStep[];
	isChineseUi: boolean;
}): ToolActivityItem {
	const steps = compactStreamProcessingSteps(processingSteps, isChineseUi).map(
		(step) => stepFromStreamStep(step, isChineseUi),
	);
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
		skillIds: [],
		toolNames,
		summaryText: "",
		details: steps.flatMap((step) => (step.detail ? [step.detail] : [])),
		steps,
	};
}

export function AgentRunBubble({
	isStreaming,
	reasoningText,
	processingSteps,
	visibleText,
	isChineseUi,
}: {
	isStreaming: boolean;
	reasoningText?: string;
	processingSteps?: FocusAgentStreamStep[];
	visibleText?: string;
	isChineseUi: boolean;
}) {
	const hasVisibleText = Boolean(visibleText?.trim());
	const hasReasoningText = Boolean(reasoningText?.trim());
	const hasToolActivity = Boolean(processingSteps?.length);
	const activity = useMemo(
		() =>
			buildStreamActivity({
				processingSteps,
				isChineseUi,
			}),
		[processingSteps, isChineseUi],
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
