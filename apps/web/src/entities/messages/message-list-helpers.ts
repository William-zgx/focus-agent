import type {
	FocusAgentBranchActionProposal,
	FocusAgentToolEvent,
	TurnFailedPayload,
} from "@focus-agent/web-sdk";

import { normalizeMessageType } from "./message-transcript";

export function roleLabel(type: unknown, isChineseUi = false) {
	const normalized = normalizeMessageType(type);
	if (normalized === "human") return isChineseUi ? "你" : "You";
	if (normalized === "ai") return "Focus Agent";
	if (normalized === "system") return isChineseUi ? "系统" : "System";
	return normalized || (isChineseUi ? "消息" : "Message");
}

export function bubbleClass(type: unknown) {
	const normalized = normalizeMessageType(type);
	if (normalized === "human") {
		return "fa-message-bubble is-user";
	}
	if (normalized === "system") {
		return "fa-message-bubble is-system";
	}
	return "fa-message-bubble is-assistant";
}

export function messageLayoutClass(type: unknown) {
	const normalized = normalizeMessageType(type);
	if (normalized === "human") {
		return "fa-message-row is-user user";
	}
	if (normalized === "system") {
		return "fa-message-row is-system system";
	}
	return "fa-message-row is-assistant assistant";
}

export function roleClass(type: unknown) {
	const normalized = normalizeMessageType(type);
	if (normalized === "human") {
		return "fa-message-role fa-message-meta is-user";
	}
	if (normalized === "system") {
		return "fa-message-role fa-message-meta is-system";
	}
	return "fa-message-role fa-message-meta";
}

function formatTokenCount(value: number) {
	const normalized = Math.max(0, Number(value) || 0);
	if (normalized >= 1_000_000) {
		const millions = normalized / 1_000_000;
		return `${millions >= 10 ? millions.toFixed(0) : millions.toFixed(1).replace(/\.0$/, "")}M`;
	}
	if (normalized >= 1_000) {
		const thousands = normalized / 1_000;
		return `${thousands >= 10 ? thousands.toFixed(0) : thousands.toFixed(1).replace(/\.0$/, "")}K`;
	}
	return new Intl.NumberFormat("en-US").format(Math.round(normalized));
}

export function tokenUsageLabel(totalTokens: number, isChineseUi: boolean) {
	if (totalTokens <= 0) {
		return "";
	}
	return isChineseUi
		? `本次回复 · ${formatTokenCount(totalTokens)} tokens`
		: `Reply · ${formatTokenCount(totalTokens)} tokens`;
}

export function toolEventLabel(
	event: FocusAgentToolEvent,
	isChineseUi: boolean,
) {
	const toolName = String(
		event.data.tool_name || event.data.event || "tool",
	).trim();
	switch (event.event) {
		case "tool.requested":
			return isChineseUi ? `准备调用 ${toolName}` : `Preparing ${toolName}`;
		case "tool.start":
			return isChineseUi ? `正在执行 ${toolName}` : `Running ${toolName}`;
		case "tool.result":
		case "tool.end":
			return isChineseUi ? `已完成 ${toolName}` : `Completed ${toolName}`;
		case "tool.error":
			return isChineseUi ? `${toolName} 执行失败` : `${toolName} failed`;
		case "tool.delta":
			return isChineseUi ? `${toolName} 返回中` : `${toolName} streaming`;
		default:
			return toolName;
	}
}

export function toolEventTone(events: FocusAgentToolEvent[]) {
	if (events.some((event) => event.event === "tool.error")) {
		return "danger";
	}
	if (
		events.length > 0 &&
		events.every(
			(event) => event.event === "tool.end" || event.event === "tool.result",
		)
	) {
		return "success";
	}
	return "warn";
}

export function codeCopyLabel(isChineseUi: boolean, copied: boolean) {
	if (copied) {
		return isChineseUi ? "已复制" : "Copied";
	}
	return isChineseUi ? "复制代码" : "Copy code";
}

export function messageCopyLabel(isChineseUi: boolean, copied: boolean) {
	if (copied) {
		return isChineseUi ? "已复制" : "Copied";
	}
	return isChineseUi ? "复制消息" : "Copy message";
}

export function editMessageLabel(isChineseUi: boolean) {
	return isChineseUi ? "编辑并重发" : "Edit and resend";
}

export function mergedBranchReadOnlyLabel(isChineseUi: boolean) {
	return isChineseUi
		? "已合并分支不允许继续对话"
		: "Merged branches are read-only";
}

export function failureText(failed: TurnFailedPayload, isChineseUi: boolean) {
	const message = String(failed.message || failed.error || "").trim();
	if (!message) {
		return isChineseUi ? "本轮执行失败。" : "This turn failed.";
	}
	return isChineseUi
		? `本轮执行失败。\n\n${message}`
		: `This turn failed.\n\n${message}`;
}

export function toolActivityTitle(toolNames: string[], isChineseUi: boolean) {
	if (toolNames.length === 0) {
		return isChineseUi ? "处理过程" : "Processing";
	}
	if (toolNames.length === 1) {
		return isChineseUi ? `已调用 ${toolNames[0]}` : `Used ${toolNames[0]}`;
	}
	return isChineseUi
		? `已调用 ${toolNames.length} 个工具`
		: `Used ${toolNames.length} tools`;
}

export function toolActivityNote(toolNames: string[], isChineseUi: boolean) {
	if (toolNames.length > 1) {
		return toolNames.join(" · ");
	}
	return isChineseUi
		? "默认折叠，可展开查看处理步骤。"
		: "Folded by default. Expand for processing details.";
}

export function toolDetailsToggleLabel(isChineseUi: boolean, isOpen: boolean) {
	if (isOpen) {
		return isChineseUi ? "收起详情" : "Hide details";
	}
	return isChineseUi ? "查看详情" : "View details";
}

export function toolSummaryLabel(isChineseUi: boolean) {
	return isChineseUi ? "结果摘要" : "Result summary";
}

export function toolLabel(isChineseUi: boolean) {
	return isChineseUi ? "工具" : "Tool";
}

export function processingStepsSummaryLabel(
	count: number,
	isChineseUi: boolean,
) {
	if (isChineseUi) {
		return `处理步骤（${count}）`;
	}
	return `Processing details (${count})`;
}

export function processingStepsToggleHint(isChineseUi: boolean) {
	return isChineseUi ? "展开查看" : "Expand";
}

export function branchActionTitle(
	action: FocusAgentBranchActionProposal,
	isChineseUi: boolean,
) {
	if (action.kind === "fork_sibling_branch") {
		return isChineseUi ? "切换到同级分支" : "Switch to sibling branch";
	}
	if (action.kind === "fork_child_branch") {
		return isChineseUi ? "创建子分支" : "Create child branch";
	}
	if (action.kind === "return_parent_branch") {
		return isChineseUi ? "返回上一层分支" : "Return to parent branch";
	}
	return isChineseUi ? "打开已有分支" : "Open existing branch";
}

export function branchActionStatusText(
	action: FocusAgentBranchActionProposal,
	isChineseUi: boolean,
) {
	switch (action.status) {
		case "executed":
			return isChineseUi ? "已完成" : "Done";
		case "dismissed":
			return isChineseUi ? "已取消" : "Dismissed";
		case "failed":
			return isChineseUi ? "执行失败" : "Failed";
		default:
			return isChineseUi ? "等待确认" : "Pending confirmation";
	}
}
