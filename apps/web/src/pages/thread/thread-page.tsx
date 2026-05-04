import type {
  ContextUsageResponse,
} from "@focus-agent/web-sdk";
import { useRouterState } from "@tanstack/react-router";
import { useCallback, useEffect, useState } from "react";

import { useShellUi } from "@/app/shell/shell-ui-context";
import { MessageList } from "@/entities/messages/message-list";
import { MessageComposer } from "@/features/thread-stream/message-composer";
import { useCompactThreadContext, usePreviewThreadContext } from "@/features/thread/use-thread-context";
import { useThreadStream } from "@/features/thread-stream/use-thread-stream";
import { useThreadState } from "@/features/thread/use-thread-state";

import { useThreadAutoFollow } from "./use-thread-auto-follow";
import { useThreadBranchActions } from "./use-thread-branch-actions";
import { useThreadTranscriptViewModel } from "./thread-transcript-view-model";

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
  const [editDraft, setEditDraft] = useState<{ id: string; content: string } | null>(null);
  const [previewContextUsage, setPreviewContextUsage] = useState<ContextUsageResponse | null>(null);
  const isMergedReadOnlyThread = data?.branch_meta?.branch_status === "merged";
  const { streamState, pendingUserMessage, isStreaming, sendMessage, stopStreaming } = useThreadStream({
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

  useEffect(() => {
    setEditDraft(null);
    setPreviewContextUsage(null);
  }, [threadId]);

  useEffect(() => {
    setPreviewContextUsage(null);
  }, [data?.context_usage, threadId]);

  useEffect(() => {
    if (isMergedReadOnlyThread) {
      setEditDraft(null);
    }
  }, [isMergedReadOnlyThread]);

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
    const payload = await compactThreadContext.mutateAsync({ trigger: "manual" });
    setPreviewContextUsage(payload.context_usage ?? null);
  }

  return (
    <div className="fa-thread-layout">
      <div className="fa-transcript-panel">
        <section className="fa-chat-transcript">
          <div className="fa-chat-history" ref={historyRef}>
            <div
              className={`fa-chat-history-content ${hasTranscriptContent ? "is-populated" : ""}`.trim()}
            >
              {isLoading ? (
                <div className="fa-inline-notice">
                  {isChineseUi ? "正在加载线程状态..." : "Loading thread state..."}
                </div>
              ) : null}
              {error ? (
                <div className="fa-inline-notice is-danger">
                  {isChineseUi ? "加载线程状态失败。" : "Failed to load thread state."}
                </div>
              ) : null}
              {hasTranscriptContent ? (
                <MessageList
                  assistantMessage={data?.assistant_message}
                  isReadOnly={isMergedReadOnlyThread}
                  isStreaming={isStreaming}
                  messages={transcriptMessages}
                  branchActions={branchActions}
                  branchActionErrors={branchActionErrors}
                  branchActionInFlightId={branchActionInFlightId}
                  isChineseUi={isChineseUi}
                  onEditMessage={setEditDraft}
                  onExecuteBranchAction={(action) => void executeBranchAction(action)}
                  onDismissBranchAction={(action) => void dismissBranchAction(action)}
                  streamFailed={streamState?.failed}
                  streamToolCalls={streamState?.toolCalls}
                  streamToolEvents={streamState?.toolEvents}
                  streamVisibleText={streamState?.visibleText}
                  streamReasoningText={streamState?.reasoningText}
                />
              ) : (
                <div className="fa-chat-empty">
                  {isChineseUi
                    ? "从这里开始聊天。只要 Agent 产生分支，左侧就会显示出来。"
                    : "Start chatting here. Branches appear on the left whenever the agent forks work."}
                </div>
              )}
            </div>
          </div>
        </section>

        <section className="fa-composer-slot">
          <MessageComposer
            editDraft={editDraft}
            isReadOnly={isMergedReadOnlyThread}
            isStreaming={isStreaming}
            onClearEditDraft={() => setEditDraft(null)}
            onSendMessage={handleSendMessage}
            onStopStreaming={stopStreaming}
            contextUsage={previewContextUsage ?? data?.context_usage ?? null}
            contextUsageError={previewThreadContext.error?.message ?? compactThreadContext.error?.message ?? ""}
            isContextUsageLoading={previewThreadContext.isPending}
            isCompactingContext={compactThreadContext.isPending}
            onCompactContext={handleCompactContext}
            onPreviewContextUsage={handlePreviewContextUsage}
            selectedModel={data?.selected_model}
            selectedThinkingMode={data?.selected_thinking_mode}
          />
        </section>
      </div>
    </div>
  );
}
