import { useRouterState } from "@tanstack/react-router";
import { useCallback } from "react";

import { useShellUi } from "@/app/shell/shell-ui-context";
import {
	useCompactThreadContext,
	usePreviewThreadContext,
} from "@/features/thread/use-thread-context";
import { useThreadState } from "@/features/thread/use-thread-state";
import { useThreadStream } from "@/features/thread-stream/use-thread-stream";

import { ThreadPageContent } from "./thread-page-content";
import { useThreadTranscriptViewModel } from "./thread-transcript-view-model";
import { useThreadAutoFollow } from "./use-thread-auto-follow";
import { useThreadBranchActions } from "./use-thread-branch-actions";
import { useThreadPageDraftState } from "./use-thread-page-draft-state";

export function ThreadPage() {
	const { threadId, conversationId } = useRouterState({
		select: (state) => {
			const routeParams = (state.matches.at(-1)?.params ?? {}) as Partial<
				Record<"conversationId" | "threadId", string>
			>;
			return {
				conversationId: String(routeParams.conversationId ?? ""),
				threadId: String(routeParams.threadId ?? ""),
			};
		},
	});
	const { data, isLoading, error } = useThreadState(threadId);
	const { isChineseUi } = useShellUi();
	const isMergedReadOnlyThread = data?.branch_meta?.branch_status === "merged";
	const {
		editDraft,
		previewContextUsage,
		setEditDraft,
		setPreviewContextUsage,
	} = useThreadPageDraftState({
		contextUsage: data?.context_usage,
		isMergedReadOnlyThread,
		threadId,
	});
	const {
		streamState,
		pendingUserMessage,
		isStreaming,
		sendMessage,
		stopStreaming,
	} = useThreadStream({
		threadId,
		rootThreadId: conversationId,
		selectedModel: data?.selected_model,
		selectedThinkingMode: data?.selected_thinking_mode,
	});
	const previewThreadContext = usePreviewThreadContext(threadId);
	const compactThreadContext = useCompactThreadContext(threadId);
	const previewThreadContextMutate = previewThreadContext.mutate;
	const {
		branchActions,
		hasTranscriptContent,
		lastTranscriptMessage,
		streamToolCallCount,
		streamToolEventCount,
		transcriptMessages,
	} = useThreadTranscriptViewModel({
		threadState: data,
		pendingUserMessage,
		streamState,
		isStreaming,
	});
	const {
		branchActionErrors,
		branchActionInFlightId,
		dismissBranchAction,
		executeBranchAction,
	} = useThreadBranchActions(threadId);
	const { followAndScrollToBottom, historyRef } = useThreadAutoFollow({
		branchActionCount: branchActions.length,
		hasTranscriptContent,
		isStreaming,
		lastTranscriptMessageContent: lastTranscriptMessage?.content,
		lastTranscriptMessageId: lastTranscriptMessage?.id,
		streamFailedMessage: streamState?.failed?.message,
		streamReasoningText: streamState?.reasoningText,
		streamToolCallCount,
		streamToolEventCount,
		streamVisibleText: streamState?.visibleText,
		threadId,
		transcriptMessageCount: transcriptMessages.length,
	});

	async function handleSendMessage(
		message: string,
		overrides?: {
			model?: string;
			thinkingMode?: string;
		},
	): Promise<{ ok: boolean }> {
		if (isMergedReadOnlyThread) {
			return { ok: false };
		}
		followAndScrollToBottom();
		return sendMessage(message, overrides);
	}

	const handlePreviewContextUsage = useCallback(
		(draftMessage: string) => {
			if (!threadId) return;
			previewThreadContextMutate(
				{ draft_message: draftMessage || null },
				{
					onSuccess: (payload) => setPreviewContextUsage(payload.context_usage),
				},
			);
		},
		[previewThreadContextMutate, threadId],
	);

	async function handleCompactContext() {
		if (!threadId || isMergedReadOnlyThread) return;
		const payload = await compactThreadContext.mutateAsync({
			trigger: "manual",
		});
		setPreviewContextUsage(payload.context_usage ?? null);
	}

	return (
		<ThreadPageContent
			assistantMessage={data?.assistant_message}
			branchActionErrors={branchActionErrors}
			branchActionInFlightId={branchActionInFlightId}
			branchActions={branchActions}
			compactContextError={compactThreadContext.error?.message}
			contextUsage={data?.context_usage ?? null}
			editDraft={editDraft}
			hasTranscriptContent={hasTranscriptContent}
			historyRef={historyRef}
			isChineseUi={isChineseUi}
			isCompactingContext={compactThreadContext.isPending}
			isContextUsageLoading={previewThreadContext.isPending}
			isLoading={isLoading}
			isMergedReadOnlyThread={isMergedReadOnlyThread}
			isStreaming={isStreaming}
			messages={transcriptMessages}
			onClearEditDraft={() => setEditDraft(null)}
			onCompactContext={handleCompactContext}
			onDismissBranchAction={(action) => void dismissBranchAction(action)}
			onEditMessage={setEditDraft}
			onExecuteBranchAction={(action) => void executeBranchAction(action)}
			onPreviewContextUsage={handlePreviewContextUsage}
			onSendMessage={handleSendMessage}
			onStopStreaming={stopStreaming}
			previewContextError={previewThreadContext.error?.message}
			previewContextUsage={previewContextUsage}
			selectedModel={data?.selected_model}
			selectedThinkingMode={data?.selected_thinking_mode}
			streamState={streamState}
			threadError={error}
		/>
	);
}
