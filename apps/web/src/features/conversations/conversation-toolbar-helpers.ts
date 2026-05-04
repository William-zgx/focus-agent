import type { FocusAgentConversationSummary } from "@focus-agent/web-sdk";

export function formatTokenCount(value: number) {
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

export function totalConversationTokens(
	conversation?: FocusAgentConversationSummary,
) {
	const raw = Number(conversation?.token_usage?.total_tokens ?? 0);
	return Number.isFinite(raw) ? Math.max(0, Math.round(raw)) : 0;
}

export function conversationArchiveActionLabel(
	conversation: FocusAgentConversationSummary | null | undefined,
	isChineseUi: boolean,
) {
	if (conversation?.is_archived) {
		return isChineseUi ? "激活对话" : "Activate conversation";
	}

	return isChineseUi ? "归档对话" : "Archive conversation";
}
