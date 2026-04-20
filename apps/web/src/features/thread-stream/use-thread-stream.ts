import {
  createInitialStreamState,
  reduceStreamEvent,
  type FocusAgentStreamState,
} from "@focus-agent/web-sdk";
import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { queryKeys } from "@/shared/query/query-keys";
import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";

interface UseThreadStreamOptions {
  threadId: string;
  rootThreadId: string;
  selectedModel?: string;
  selectedThinkingMode?: string;
}

interface SendMessageOverrides {
  model?: string;
  thinkingMode?: string;
}

interface PendingUserMessage {
  id: string;
  content: string;
  threadId: string;
}

export function useThreadStream(options: UseThreadStreamOptions) {
  const { client } = useFocusAgent();
  const queryClient = useQueryClient();
  const abortRef = useRef<AbortController | null>(null);
  const activeRequestIdRef = useRef<string | null>(null);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [streamState, setStreamState] = useState<FocusAgentStreamState | null>(null);
  const [pendingUserMessage, setPendingUserMessage] = useState<PendingUserMessage | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);

  async function sendMessage(message: string, overrides?: SendMessageOverrides) {
    abortRef.current?.abort();
    const requestId = `stream-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const requestThreadId = options.threadId;
    const requestRootThreadId = options.rootThreadId;
    const controller = new AbortController();
    abortRef.current = controller;
    activeRequestIdRef.current = requestId;
    setActiveThreadId(requestThreadId);
    setPendingUserMessage({
      id: `optimistic-user-${Date.now()}`,
      content: message,
      threadId: requestThreadId,
    });
    setStreamState(createInitialStreamState());
    setIsStreaming(true);

    try {
      const stream = await client.streamTurn(
        {
          thread_id: requestThreadId,
          message,
          model: overrides?.model || options.selectedModel || undefined,
          thinking_mode:
            overrides?.thinkingMode || options.selectedThinkingMode || undefined,
        },
        { signal: controller.signal },
      );

      let nextState = createInitialStreamState();
      for await (const event of stream) {
        if (activeRequestIdRef.current !== requestId || controller.signal.aborted) {
          break;
        }
        nextState = reduceStreamEvent(nextState, event);
        if (activeRequestIdRef.current !== requestId || controller.signal.aborted) {
          break;
        }
        setStreamState(nextState);
      }
    } finally {
      const isLatestRequest = activeRequestIdRef.current === requestId;
      if (isLatestRequest) {
        setIsStreaming(false);
        abortRef.current = null;
        activeRequestIdRef.current = null;
        setActiveThreadId(null);
        setPendingUserMessage(null);
        setStreamState(null);
      }
      await queryClient.invalidateQueries({ queryKey: queryKeys.thread(requestThreadId) });
      await queryClient.invalidateQueries({ queryKey: queryKeys.branchTree(requestRootThreadId) });
      await queryClient.invalidateQueries({ queryKey: queryKeys.conversations });
    }
  }

  function stopStreaming() {
    abortRef.current?.abort();
  }

  const isCurrentThreadActive = activeThreadId === options.threadId;

  return {
    streamState: isCurrentThreadActive ? streamState : null,
    pendingUserMessage: isCurrentThreadActive ? pendingUserMessage : null,
    isStreaming: isCurrentThreadActive ? isStreaming : false,
    sendMessage,
    stopStreaming,
  };
}
