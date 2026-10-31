import type {
	FocusAgentBranchActionProposal,
	RunFailedPayload,
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

export function branchFromMessageLabel(isChineseUi: boolean) {
	return isChineseUi ? "从这里开分支" : "Branch from here";
}

export function mergedBranchForkLabel(isChineseUi: boolean) {
	return isChineseUi
		? "已合并分支不能新建分支"
		: "Merged branches cannot create new branches";
}

const BRANCH_GOAL_QUOTE_LIMIT = 600;

/** Pre-fills the fork dialog's goal from the message the user branched on. */
export function branchGoalDraftFromMessage(
	content: string,
	isHuman: boolean,
	isChineseUi: boolean,
) {
	const text = content.trim();
	if (isHuman) return text;
	const excerpt =
		text.length > BRANCH_GOAL_QUOTE_LIMIT
			? `${text.slice(0, BRANCH_GOAL_QUOTE_LIMIT).trimEnd()}…`
			: text;
	const quote = excerpt
		.split("\n")
		.map((line) => `> ${line}`)
		.join("\n");
	return isChineseUi
		? `针对这段回答继续深入：\n${quote}\n\n`
		: `Dig deeper into this answer:\n${quote}\n\n`;
}

export function mergedBranchReadOnlyLabel(isChineseUi: boolean) {
	return isChineseUi
		? "已合并分支不允许继续对话"
		: "Merged branches are read-only";
}

export function failureText(failed: RunFailedPayload, isChineseUi: boolean) {
	const message = String(failed.message || failed.error || "").trim();
	if (!message) {
		return isChineseUi ? "本轮执行失败。" : "This turn failed.";
	}
	return isChineseUi
		? `本轮执行失败。\n\n${message}`
		: `This turn failed.\n\n${message}`;
}

export function toolActivityTitle(_toolNames: string[], isChineseUi: boolean) {
	return isChineseUi ? "本轮处理" : "Run activity";
}

export function toolActivityNote(toolNames: string[], isChineseUi: boolean) {
	if (toolNames.length > 1) {
		return isChineseUi
			? "已合并本轮工具调用，展开查看时间线和详情。"
			: "This run's tool calls are merged. Expand for timeline and details.";
	}
	return isChineseUi
		? "默认折叠，可展开查看时间线和详情。"
		: "Folded by default. Expand for timeline and details.";
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
	return isChineseUi ? "本轮" : "Run";
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

export function branchRoleLabel(
	role: FocusAgentBranchActionProposal["branch_role"],
	isChineseUi: boolean,
) {
	switch (role) {
		case "deep_dive":
			return isChineseUi ? "深入研究" : "Deep dive";
		case "execute":
			return isChineseUi ? "执行" : "Execute";
		case "explore_alternatives":
			return isChineseUi ? "探索备选" : "Explore alternatives";
		case "verify":
			return isChineseUi ? "验证" : "Verify";
		case "writeup":
			return isChineseUi ? "撰写总结" : "Write-up";
		default:
			return isChineseUi ? "主线" : "Main";
	}
}

export function branchActionReasonText(action: FocusAgentBranchActionProposal) {
	const reason = String(action.reason ?? "").trim();
	// Older actions stored the technical scorer rationale as the reason.
	if (!reason || reason.includes("route=") || reason === action.rationale) {
		return "";
	}
	return reason;
}

export function branchActionStatusText(
	action: FocusAgentBranchActionProposal,
	isChineseUi: boolean,
) {
	switch (action.status) {
		case "executed":
			return isChineseUi ? "已完成" : "Done";
		case "dismissed":
			return isChineseUi ? "已继续当前分支" : "Staying in current branch";
		case "failed":
			return isChineseUi ? "执行失败" : "Failed";
		default:
			return isChineseUi ? "等待确认" : "Pending confirmation";
	}
}
