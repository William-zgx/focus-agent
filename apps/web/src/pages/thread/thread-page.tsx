import { useRouterState } from "@tanstack/react-router";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { useShellUi } from "@/app/shell/shell-ui-context";
import { MessageList } from "@/entities/messages/message-list";
import { MessageComposer } from "@/features/thread-stream/message-composer";
import { useThreadStream } from "@/features/thread-stream/use-thread-stream";
import { useThreadState } from "@/features/thread/use-thread-state";

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
  const historyRef = useRef<HTMLDivElement | null>(null);
  const shouldAutoFollowRef = useRef(true);
  const isMergedReadOnlyThread = data?.branch_meta?.branch_status === "merged";
  const { streamState, pendingUserMessage, isStreaming, sendMessage, stopStreaming } = useThreadStream({
    threadId,
    rootThreadId: conversationId,
    selectedModel: data?.selected_model,
    selectedThinkingMode: data?.selected_thinking_mode,
  });
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
  const hasTranscriptContent = Boolean(
    transcriptMessages.length ||
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
  }, [threadId]);

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
  ) {
    if (isMergedReadOnlyThread) {
      return;
    }
    shouldAutoFollowRef.current = true;
    scrollToBottom();
    await sendMessage(message, overrides);
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
                  isChineseUi={isChineseUi}
                  onEditMessage={setEditDraft}
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
            selectedModel={data?.selected_model}
            selectedThinkingMode={data?.selected_thinking_mode}
          />
        </section>
      </div>
    </div>
  );
}
