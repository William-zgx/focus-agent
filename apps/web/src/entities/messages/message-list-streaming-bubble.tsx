import type {
	FocusAgentToolCallEvent,
	FocusAgentToolEvent,
} from "@focus-agent/web-sdk";
import { useMemo } from "react";

import {
	processingStepsSummaryLabel,
	processingStepsToggleHint,
	toolEventLabel,
	toolEventTone,
} from "./message-list-helpers";

export function AgentRunBubble({
	isStreaming,
	reasoningText,
	toolCalls,
	toolEvents,
	visibleText,
	isChineseUi,
}: {
	isStreaming: boolean;
	reasoningText?: string;
	toolCalls?: FocusAgentToolCallEvent[];
	toolEvents?: FocusAgentToolEvent[];
	visibleText?: string;
	isChineseUi: boolean;
}) {
	const hasVisibleText = Boolean(visibleText?.trim());
	const tone = toolEventTone(toolEvents ?? []);
	const hasReasoningText = Boolean(reasoningText?.trim());
	const hasToolActivity = Boolean(
		(toolCalls?.length ?? 0) || (toolEvents?.length ?? 0),
	);
	const stageTitle = hasToolActivity
		? isChineseUi
			? "正在处理请求"
			: "Processing the request"
		: hasReasoningText
			? isChineseUi
				? "正在思考"
				: "Thinking"
			: isChineseUi
				? "已收到，正在思考"
				: "Message received, thinking";
	const stageDetail = hasToolActivity
		? isChineseUi
			? "工具步骤已经开始，默认折叠显示；展开后可以查看处理明细。"
			: "Tool steps are underway. They stay folded by default so the main reply remains calm."
		: hasReasoningText
			? isChineseUi
				? "Agent 正在整理上下文和回答结构，准备进入下一阶段。"
				: "The agent is organizing context and shaping the reply before moving on."
			: isChineseUi
				? "消息已经发送成功，系统正在建立本轮响应。"
				: "Your message has been sent. The system is preparing this turn now.";
	const steps = useMemo(() => {
		const items: Array<{ label: string; tone: "warn" | "success" | "danger" }> =
			[];
		if (reasoningText?.trim()) {
			items.push({
				label: isChineseUi ? "正在整理推理链路" : "Reasoning in progress",
				tone: "warn",
			});
		}
		for (const call of toolCalls ?? []) {
			const toolName = String(call.data.name || "tool").trim();
			items.push({
				label: isChineseUi ? `规划调用 ${toolName}` : `Planning ${toolName}`,
				tone: "warn",
			});
		}
		for (const event of toolEvents ?? []) {
			items.push({
				label: toolEventLabel(event, isChineseUi),
				tone:
					event.event === "tool.error"
						? "danger"
						: event.event === "tool.end" || event.event === "tool.result"
							? "success"
							: "warn",
			});
		}
		return items.slice(-5);
	}, [isChineseUi, reasoningText, toolCalls, toolEvents]);

	if (!isStreaming || hasVisibleText) {
		return null;
	}

	return (
		<div className="fa-message-row is-assistant assistant">
			<div className="fa-message-stack">
				<div className={`fa-agent-run-bubble is-${tone}`}>
					<div className="fa-agent-run-head">
						<div className={`fa-agent-run-pulse is-${tone}`} />
						<div className="fa-agent-run-copy">
							<div className="fa-agent-run-title">{stageTitle}</div>
							<div className="fa-agent-run-detail">{stageDetail}</div>
						</div>
					</div>
					{steps.length > 0 ? (
						<details className="fa-agent-run-steps-shell">
							<summary className="fa-agent-run-steps-summary">
								<span>
									{processingStepsSummaryLabel(steps.length, isChineseUi)}
								</span>
								<span className="fa-agent-run-steps-hint">
									{processingStepsToggleHint(isChineseUi)}
								</span>
							</summary>
							<div className="fa-agent-run-steps">
								{steps.map((step, index) => (
									<div
										key={`${step.label}-${index}`}
										className={`fa-agent-run-step is-${step.tone}`}
									>
										<span className="fa-agent-run-step-dot" />
										<span>{step.label}</span>
									</div>
								))}
							</div>
						</details>
					) : null}
				</div>
			</div>
		</div>
	);
}
