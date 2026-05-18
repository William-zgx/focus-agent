import type {
	FocusAgentBranchActionProposal,
	FocusAgentStreamState,
	FocusAgentToolApprovalInterrupt,
	ThreadStateResponse,
} from "@focus-agent/web-sdk";
import { isToolApprovalInterrupt } from "@focus-agent/web-sdk";
import { useMemo } from "react";

import type { PendingUserMessage } from "@/features/thread-stream/use-thread-stream";

interface UseThreadTranscriptViewModelOptions {
	threadState?: ThreadStateResponse;
	pendingUserMessage: PendingUserMessage | null;
	streamState: FocusAgentStreamState | null;
	isStreaming: boolean;
}

export function useThreadTranscriptViewModel({
	threadState,
	pendingUserMessage,
	streamState,
	isStreaming,
}: UseThreadTranscriptViewModelOptions) {
	const transcriptMessages = useMemo(() => {
		const baseMessages = (
			(threadState?.messages as Array<Record<string, unknown>> | undefined) ??
			[]
		).slice();
		if (!pendingUserMessage) {
			return baseMessages;
		}

		const lastMessage = baseMessages.at(-1);
		const lastType = String(lastMessage?.type || "").toLowerCase();
		const lastContent = String(lastMessage?.content ?? "");
		if (lastType === "human" && lastContent === pendingUserMessage.content) {
			return baseMessages;
		}

		baseMessages.push({
			id: pendingUserMessage.id,
			type: "human",
			content: pendingUserMessage.content,
		});
		return baseMessages;
	}, [threadState?.messages, pendingUserMessage]);

	const branchActions = useMemo(() => {
		const byId = new Map<string, FocusAgentBranchActionProposal>();
		for (const action of threadState?.branch_actions ?? []) {
			byId.set(action.action_id, action);
		}
		for (const action of streamState?.branchActions ?? []) {
			byId.set(action.action_id, action);
		}
		return [...byId.values()];
	}, [threadState?.branch_actions, streamState?.branchActions]);

	const toolApprovalInterrupts = useMemo(() => {
		const byId = new Map<string, FocusAgentToolApprovalInterrupt>();
		for (const interrupt of threadState?.interrupts ?? []) {
			if (isToolApprovalInterrupt(interrupt)) {
				byId.set(interrupt.tool_call_id, interrupt);
			}
		}
		for (const interrupt of streamState?.interrupts ?? []) {
			if (isToolApprovalInterrupt(interrupt)) {
				byId.set(interrupt.tool_call_id, interrupt);
			}
		}
		return [...byId.values()];
	}, [threadState?.interrupts, streamState?.interrupts]);

	const hasTranscriptContent = Boolean(
		transcriptMessages.length ||
			branchActions.length ||
			toolApprovalInterrupts.length ||
			isStreaming ||
			streamState?.visibleText ||
			streamState?.reasoningText ||
			streamState?.toolCalls?.length ||
			streamState?.toolEvents?.length ||
			streamState?.failed,
	);
	const lastTranscriptMessage = transcriptMessages.at(-1);
	const streamToolCallCount = streamState?.toolCalls?.length ?? 0;
	const streamToolEventCount = streamState?.toolEvents?.length ?? 0;

	return {
		branchActions,
		hasTranscriptContent,
		lastTranscriptMessage,
		streamToolCallCount,
		streamToolEventCount,
		toolApprovalInterrupts,
		transcriptMessages,
	};
}
