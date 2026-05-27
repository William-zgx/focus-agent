import { useRouterState } from "@tanstack/react-router";
import { useCallback, useEffect, useRef, useState } from "react";
import type { FocusAgentToolApprovalInterrupt } from "@focus-agent/web-sdk";

import { useShellUi } from "@/app/shell/shell-ui-context";
import {
	useCompactThreadContext,
	usePreviewThreadContext,
} from "@/features/thread/use-thread-context";
import { useThreadState } from "@/features/thread/use-thread-state";
import {
	type SendMessageOverrides,
	useThreadStream,
} from "@/features/thread-stream/use-thread-stream";

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
	const composerSelectionOverridesRef = useRef<SendMessageOverrides>({});
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
		resumeToolApproval,
		runCarriedMessageInThread,
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
	useEffect(() => {
		if (!threadId) {
			composerSelectionOverridesRef.current = {};
			return;
		}
		composerSelectionOverridesRef.current = {};
	}, [threadId]);
	useEffect(() => {
		if (!data?.selected_model && !data?.selected_thinking_mode) {
			return;
		}
		composerSelectionOverridesRef.current = {
			model: data?.selected_model || undefined,
			...(data?.selected_thinking_mode
				? { thinkingMode: data.selected_thinking_mode }
				: {}),
		};
	}, [data?.selected_model, data?.selected_thinking_mode]);
	const handleComposerSelectionChange = useCallback(
		(overrides: SendMessageOverrides) => {
			composerSelectionOverridesRef.current = overrides;
		},
		[],
	);
	const {
		branchActions,
		hasTranscriptContent,
		lastTranscriptMessage,
		streamToolCallCount,
		streamToolEventCount,
		toolApprovalInterrupts,
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
		continueCurrentBranchAction,
		dismissBranchAction,
		executeBranchAction,
	} = useThreadBranchActions(threadId, {
		onContinueCurrentBranch: ({ threadId: targetThreadId, message }) => {
			return runCarriedMessageInThread(
				targetThreadId,
				message,
				composerSelectionOverridesRef.current,
			);
		},
		onRunHandoff: ({ threadId: targetThreadId, message }) => {
			return runCarriedMessageInThread(
				targetThreadId,
				message,
				composerSelectionOverridesRef.current,
			);
		},
	});
	const { followAndScrollToBottom, stickToBottom } = useThreadAutoFollow({
		branchActionCount: branchActions.length,
		hasTranscriptContent,
		isStreaming,
		lastTranscriptMessageContent: lastTranscriptMessage?.content,
		lastTranscriptMessageId: lastTranscriptMessage?.id,
		streamFailedMessage: streamState?.failed?.message,
		streamProcessingStepSignal: streamState?.processingSteps
			.map(
				(step) =>
					`${step.kind}:${step.id}:${step.status}:${step.content ?? ""}:${step.argsText ?? ""}`,
			)
			.join("\n"),
		streamReasoningText: streamState?.reasoningText,
		streamToolCallCount,
		streamToolEventCount,
		toolApprovalInterruptCount: toolApprovalInterrupts.length,
		streamVisibleText: streamState?.visibleText,
		threadId,
		transcriptMessageCount: transcriptMessages.length,
	});
	const [toolApprovalInFlightId, setToolApprovalInFlightId] = useState<
		string | null
	>(null);
	const [toolApprovalErrorId, setToolApprovalErrorId] = useState<string | null>(
		null,
	);
	const [toolApprovalError, setToolApprovalError] = useState("");

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
		if (overrides) {
			composerSelectionOverridesRef.current = overrides;
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
		[previewThreadContextMutate, threadId, setPreviewContextUsage],
	);

	async function handleCompactContext() {
		if (!threadId || isMergedReadOnlyThread) return;
		const payload = await compactThreadContext.mutateAsync({
			trigger: "manual",
		});
		setPreviewContextUsage(payload.context_usage ?? null);
	}

	async function handleDecideToolApproval(
		interrupt: FocusAgentToolApprovalInterrupt,
		approved: boolean,
	) {
		if (isMergedReadOnlyThread) return;
		setToolApprovalInFlightId(interrupt.tool_call_id);
		setToolApprovalErrorId(null);
		setToolApprovalError("");
		followAndScrollToBottom();
		const result = await resumeToolApproval(interrupt, approved);
		if (!result.ok) {
			setToolApprovalErrorId(interrupt.tool_call_id);
			setToolApprovalError(
				isChineseUi
					? "提交工具审批结果失败。"
					: "Failed to submit the tool approval decision.",
			);
		}
		setToolApprovalInFlightId(null);
	}

	return (
		<ThreadPageContent
			assistantMessage={data?.assistant_message}
			branchActionErrors={branchActionErrors}
			branchActionInFlightId={branchActionInFlightId}
			branchActions={branchActions}
			branchDecisionSummary={data?.branch_decision_summary ?? null}
			compactContextError={compactThreadContext.error?.message}
			contextUsage={data?.context_usage ?? null}
			editDraft={editDraft}
			hasTranscriptContent={hasTranscriptContent}
			isChineseUi={isChineseUi}
			isCompactingContext={compactThreadContext.isPending}
			isContextUsageLoading={previewThreadContext.isPending}
			isLoading={isLoading}
			isMergedReadOnlyThread={isMergedReadOnlyThread}
			isStreaming={isStreaming}
			messages={transcriptMessages}
			onClearEditDraft={() => setEditDraft(null)}
			onCompactContext={handleCompactContext}
			onComposerSelectionChange={handleComposerSelectionChange}
			onDecideToolApproval={(interrupt, approved) =>
				void handleDecideToolApproval(interrupt, approved)
			}
			onContinueCurrentBranchAction={(action) =>
				void continueCurrentBranchAction(action)
			}
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
			stickToBottom={stickToBottom}
			streamState={streamState}
			threadError={error}
			threadId={threadId}
			rootThreadId={data?.root_thread_id ?? conversationId}
			toolApprovalError={toolApprovalError}
			toolApprovalErrorId={toolApprovalErrorId}
			toolApprovalInFlightId={toolApprovalInFlightId}
			toolApprovalInterrupts={toolApprovalInterrupts}
		/>
	);
}
