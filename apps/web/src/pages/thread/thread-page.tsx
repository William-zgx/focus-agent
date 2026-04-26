import type {
  ContextUsageResponse,
  FocusAgentBranchActionExecuteResponse,
  FocusAgentBranchActionNavigation,
  FocusAgentBranchActionProposal,
} from "@focus-agent/web-sdk";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { useShellUi } from "@/app/shell/shell-ui-context";
import { MessageList } from "@/entities/messages/message-list";
import { MessageComposer } from "@/features/thread-stream/message-composer";
import { useCompactThreadContext, usePreviewThreadContext } from "@/features/thread/use-thread-context";
import { useThreadStream } from "@/features/thread-stream/use-thread-stream";
import { useThreadState } from "@/features/thread/use-thread-state";
import { queryKeys } from "@/shared/query/query-keys";
import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";

function navigationFromBranchActionResult(
  result: FocusAgentBranchActionExecuteResponse,
): FocusAgentBranchActionNavigation | null {
  if (result.navigation) {
    return result.navigation;
  }
  if (result.branch_action.navigation) {
    return result.branch_action.navigation;
  }
  if (result.branch_record) {
    return {
      root_thread_id: result.branch_record.root_thread_id,
      thread_id: result.branch_record.child_thread_id,
    };
  }
  return null;
}

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
  const { client } = useFocusAgent();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { isChineseUi } = useShellUi();
  const [editDraft, setEditDraft] = useState<{ id: string; content: string } | null>(null);
  const [previewContextUsage, setPreviewContextUsage] = useState<ContextUsageResponse | null>(null);
  const [branchActionInFlightId, setBranchActionInFlightId] = useState<string | null>(null);
  const [branchActionErrors, setBranchActionErrors] = useState<Record<string, string>>({});
  const branchActionInFlightRef = useRef<string | null>(null);
  const historyRef = useRef<HTMLDivElement | null>(null);
  const shouldAutoFollowRef = useRef(true);
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
  const transcriptMessages = useMemo(() => {
    const baseMessages = ((data?.messages as Array<Record<string, unknown>> | undefined) ?? []).slice();
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
  }, [data?.messages, pendingUserMessage]);
  const branchActions = useMemo(() => {
    const byId = new Map<string, FocusAgentBranchActionProposal>();
    for (const action of data?.branch_actions ?? []) {
      byId.set(action.action_id, action);
    }
    for (const action of streamState?.branchActions ?? []) {
      byId.set(action.action_id, action);
    }
    return [...byId.values()];
  }, [data?.branch_actions, streamState?.branchActions]);
  const refreshBranchActionSurfaces = useCallback(
    async (rootThreadId: string, currentThreadId: string) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.conversations }),
        queryClient.invalidateQueries({ queryKey: queryKeys.branchTree(rootThreadId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.thread(currentThreadId) }),
      ]);
    },
    [queryClient],
  );
  const beginBranchActionRequest = useCallback((actionId: string) => {
    if (branchActionInFlightRef.current) {
      return false;
    }
    branchActionInFlightRef.current = actionId;
    setBranchActionInFlightId(actionId);
    setBranchActionErrors((current) => {
      const next = { ...current };
      delete next[actionId];
      return next;
    });
    return true;
  }, []);
  const endBranchActionRequest = useCallback((actionId: string) => {
    if (branchActionInFlightRef.current === actionId) {
      branchActionInFlightRef.current = null;
      setBranchActionInFlightId(null);
    }
  }, []);
  const refreshThreadAfterBranchActionFailure = useCallback(
    async (actionId: string, error: unknown) => {
      const message = error instanceof Error ? error.message : String(error || "");
      setBranchActionErrors((current) => ({
        ...current,
        [actionId]: message || (isChineseUi ? "分支操作失败。" : "Branch action failed."),
      }));
      const threadState = await client.getThreadState(threadId);
      queryClient.setQueryData(queryKeys.thread(threadId), threadState);
      await refreshBranchActionSurfaces(threadState.root_thread_id, threadId);
    },
    [client, isChineseUi, queryClient, refreshBranchActionSurfaces, threadId],
  );
  const executeBranchAction = useCallback(
    async (action: FocusAgentBranchActionProposal) => {
      if (!beginBranchActionRequest(action.action_id)) {
        return;
      }
      try {
        const result = await client.executeBranchAction(threadId, action.action_id);
        queryClient.setQueryData(queryKeys.thread(threadId), result.thread_state);
        await refreshBranchActionSurfaces(result.thread_state.root_thread_id, threadId);
        const navigation = navigationFromBranchActionResult(result);
        if (navigation) {
          await queryClient.invalidateQueries({ queryKey: queryKeys.thread(navigation.thread_id) });
          await navigate({
            to: "/c/$conversationId/t/$threadId",
            params: {
              conversationId: navigation.root_thread_id,
              threadId: navigation.thread_id,
            },
          });
        }
      } catch (error) {
        console.error("Failed to execute branch action", error);
        await refreshThreadAfterBranchActionFailure(action.action_id, error);
      } finally {
        endBranchActionRequest(action.action_id);
      }
    },
    [
      beginBranchActionRequest,
      client,
      endBranchActionRequest,
      navigate,
      queryClient,
      refreshBranchActionSurfaces,
      refreshThreadAfterBranchActionFailure,
      threadId,
    ],
  );
  const dismissBranchAction = useCallback(
    async (action: FocusAgentBranchActionProposal) => {
      if (!beginBranchActionRequest(action.action_id)) {
        return;
      }
      try {
        const threadState = await client.dismissBranchAction(threadId, action.action_id);
        queryClient.setQueryData(queryKeys.thread(threadId), threadState);
        await refreshBranchActionSurfaces(threadState.root_thread_id, threadId);
      } catch (error) {
        console.error("Failed to dismiss branch action", error);
        await refreshThreadAfterBranchActionFailure(action.action_id, error);
      } finally {
        endBranchActionRequest(action.action_id);
      }
    },
    [
      beginBranchActionRequest,
      client,
      endBranchActionRequest,
      queryClient,
      refreshBranchActionSurfaces,
      refreshThreadAfterBranchActionFailure,
      threadId,
    ],
  );
  const hasTranscriptContent = Boolean(
    transcriptMessages.length ||
      branchActions.length ||
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

  function isNearBottom(element: HTMLElement) {
    const distance = element.scrollHeight - element.clientHeight - element.scrollTop;
    return distance <= 48;
  }

  function scrollToBottom() {
    const history = historyRef.current;
    if (!history) return;
    history.scrollTop = history.scrollHeight;
  }

  useEffect(() => {
    setEditDraft(null);
    setPreviewContextUsage(null);
    setBranchActionInFlightId(null);
    setBranchActionErrors({});
    branchActionInFlightRef.current = null;
  }, [threadId]);

  useEffect(() => {
    setPreviewContextUsage(null);
  }, [data?.context_usage, threadId]);

  useEffect(() => {
    if (isMergedReadOnlyThread) {
      setEditDraft(null);
    }
  }, [isMergedReadOnlyThread]);

  useEffect(() => {
    const history = historyRef.current;
    if (!history) return;

    const handleScroll = () => {
      shouldAutoFollowRef.current = isNearBottom(history);
    };

    handleScroll();
    history.addEventListener("scroll", handleScroll, { passive: true });
    return () => {
      history.removeEventListener("scroll", handleScroll);
    };
  }, [threadId]);

  useEffect(() => {
    shouldAutoFollowRef.current = true;
  }, [threadId]);

  useLayoutEffect(() => {
    if (!hasTranscriptContent || !shouldAutoFollowRef.current) {
      return;
    }
    scrollToBottom();
  }, [
    threadId,
    hasTranscriptContent,
    isStreaming,
    transcriptMessages.length,
    lastTranscriptMessage?.id,
    lastTranscriptMessage?.content,
    streamState?.visibleText,
    streamState?.reasoningText,
    branchActions.length,
    streamToolCallCount,
    streamToolEventCount,
    streamState?.failed?.message,
  ]);

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
    shouldAutoFollowRef.current = true;
    scrollToBottom();
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
