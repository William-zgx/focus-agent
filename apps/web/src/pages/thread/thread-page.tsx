import { useRouterState } from "@tanstack/react-router";
import { useEffect, useState } from "react";

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
  const isMergedReadOnlyThread = data?.branch_meta?.branch_status === "merged";
  const { streamState, isStreaming, sendMessage, stopStreaming } = useThreadStream({
    threadId,
    rootThreadId: conversationId,
    selectedModel: data?.selected_model,
    selectedThinkingMode: data?.selected_thinking_mode,
  });

  useEffect(() => {
    setEditDraft(null);
  }, [threadId]);

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
  ) {
    if (isMergedReadOnlyThread) {
      return;
    }
    await sendMessage(message, overrides);
  }

  return (
    <div className="fa-thread-layout">
      <div className="fa-transcript-panel">
        <section className="fa-chat-transcript">
          <div className="fa-chat-history">
            <div className="fa-chat-history-content">
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
              {data?.messages?.length || streamState?.visibleText || streamState?.reasoningText ? (
                <MessageList
                  isReadOnly={isMergedReadOnlyThread}
                  messages={(data?.messages as Array<Record<string, unknown>> | undefined) ?? []}
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
