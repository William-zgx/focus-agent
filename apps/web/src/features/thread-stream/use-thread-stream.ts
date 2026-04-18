import {
  createInitialStreamState,
  reduceStreamEvent,
  type FocusAgentStreamState,
  type ThreadStateResponse,
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

export function useThreadStream(options: UseThreadStreamOptions) {
  const { client } = useFocusAgent();
  const queryClient = useQueryClient();
  const abortRef = useRef<AbortController | null>(null);
  const [streamState, setStreamState] = useState<FocusAgentStreamState | null>(null);
  const [pendingUserMessage, setPendingUserMessage] = useState<{ id: string; content: string } | null>(
    null,
  );
  const [isStreaming, setIsStreaming] = useState(false);

  async function sendMessage(message: string, overrides?: SendMessageOverrides) {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setPendingUserMessage({
      id: `optimistic-user-${Date.now()}`,
      content: message,
    });
    setStreamState(createInitialStreamState());
    setIsStreaming(true);

    try {
      const stream = await client.streamTurn(
        {
          thread_id: options.threadId,
          message,
          model: overrides?.model || options.selectedModel || undefined,
          thinking_mode:
            overrides?.thinkingMode || options.selectedThinkingMode || undefined,
        },
        { signal: controller.signal },
      );

      let nextState = createInitialStreamState();
      for await (const event of stream) {
        nextState = reduceStreamEvent(nextState, event);
        setStreamState(nextState);
      }
    } finally {
      setIsStreaming(false);
      abortRef.current = null;
      await queryClient.invalidateQueries({ queryKey: queryKeys.thread(options.threadId) });
      await queryClient.invalidateQueries({ queryKey: queryKeys.branchTree(options.rootThreadId) });
      await queryClient.invalidateQueries({ queryKey: queryKeys.conversations });
      setPendingUserMessage(null);
      setStreamState(null);
    }
  }

  function stopStreaming() {
    abortRef.current?.abort();
  }

  return {
    streamState,
    pendingUserMessage,
    isStreaming,
    sendMessage,
    stopStreaming,
  };
}
