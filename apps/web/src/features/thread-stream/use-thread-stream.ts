import {
  createInitialStreamState,
  reduceStreamEvent,
  type FocusAgentStreamState,
  type ThreadStateResponse,
} from "@focus-agent/web-sdk";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";

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

interface ThreadStreamEntry {
  streamState: FocusAgentStreamState | null;
  pendingUserMessage: PendingUserMessage | null;
  isStreaming: boolean;
}

interface SendMessageResult {
  ok: boolean;
}

interface StreamRequestCleanup {
  clearActiveThread: boolean;
  clearPendingUserMessage: boolean;
  clearStreamState: boolean;
}

export function resolveStreamRequestCleanup(
  sendSucceeded: boolean,
  aborted: boolean,
): StreamRequestCleanup {
  if (sendSucceeded) {
    return {
      clearActiveThread: true,
      clearPendingUserMessage: true,
      clearStreamState: true,
    };
  }
  if (aborted) {
    return {
      clearActiveThread: true,
      clearPendingUserMessage: true,
      clearStreamState: false,
    };
  }
  return {
    clearActiveThread: false,
    clearPendingUserMessage: true,
    clearStreamState: false,
  };
}

export function resolveThinkingModeForRequest(
  overrides: SendMessageOverrides | undefined,
  selectedThinkingMode: string | undefined,
) {
  if (overrides && Object.prototype.hasOwnProperty.call(overrides, "thinkingMode")) {
    return overrides.thinkingMode;
  }
  return selectedThinkingMode || undefined;
}

export function createThreadStreamEntry(
  overrides?: Partial<ThreadStreamEntry>,
): ThreadStreamEntry {
  return {
    streamState: null,
    pendingUserMessage: null,
    isStreaming: false,
    ...(overrides ?? {}),
  };
}

export function nextThreadEntryMap(
  current: Record<string, ThreadStreamEntry>,
  threadId: string,
  value: ThreadStreamEntry | null,
): Record<string, ThreadStreamEntry> {
  if (!threadId) {
    return current;
  }
  if (value === null) {
    if (!Object.prototype.hasOwnProperty.call(current, threadId)) {
      return current;
    }
    const next = { ...current };
    delete next[threadId];
    return next;
  }
  return {
    ...current,
    [threadId]: value,
  };
}

export function patchThreadEntry(
  current: Record<string, ThreadStreamEntry>,
  threadId: string,
  patch: Partial<ThreadStreamEntry>,
): Record<string, ThreadStreamEntry> {
  const nextEntry = {
    ...(current[threadId] ?? createThreadStreamEntry()),
    ...patch,
  };
  if (
    nextEntry.streamState === null &&
    nextEntry.pendingUserMessage === null &&
    !nextEntry.isStreaming
  ) {
    return nextThreadEntryMap(current, threadId, null);
  }
  return nextThreadEntryMap(current, threadId, nextEntry);
}

export function useThreadStream(options: UseThreadStreamOptions) {
  const { client } = useFocusAgent();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const abortControllersRef = useRef<Map<string, AbortController>>(new Map());
  const activeRequestIdsRef = useRef<Map<string, string>>(new Map());
  const [threadEntries, setThreadEntries] = useState<Record<string, ThreadStreamEntry>>({});

  useEffect(() => {
    return () => {
      for (const controller of abortControllersRef.current.values()) {
        controller.abort();
      }
      abortControllersRef.current.clear();
      activeRequestIdsRef.current.clear();
    };
  }, []);

  async function sendMessage(
    message: string,
    overrides?: SendMessageOverrides,
  ): Promise<SendMessageResult> {
    const requestId = `stream-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const requestThreadId = options.threadId;
    const requestRootThreadId = options.rootThreadId;
    abortControllersRef.current.get(requestThreadId)?.abort();
    const controller = new AbortController();
    abortControllersRef.current.set(requestThreadId, controller);
    activeRequestIdsRef.current.set(requestThreadId, requestId);
    setThreadEntries((current) =>
      nextThreadEntryMap(
        current,
        requestThreadId,
        createThreadStreamEntry({
          pendingUserMessage: {
            id: `optimistic-user-${Date.now()}`,
            content: message,
            threadId: requestThreadId,
          },
          streamState: createInitialStreamState(),
          isStreaming: true,
        }),
      ),
    );

    let sendSucceeded = false;
    try {
      const requestPayload = {
        thread_id: requestThreadId,
        message,
        model: overrides?.model || options.selectedModel || undefined,
        thinking_mode: resolveThinkingModeForRequest(
          overrides,
          options.selectedThinkingMode,
        ),
      };

      const stream = await client.streamTurn(
        requestPayload,
        { signal: controller.signal },
      );

      let nextState = createInitialStreamState();
      for await (const event of stream) {
        if (
          activeRequestIdsRef.current.get(requestThreadId) !== requestId ||
          controller.signal.aborted
        ) {
          break;
        }
        nextState = reduceStreamEvent(nextState, event);
        if (event.event === "turn.completed") {
          const threadState = event.data.thread_state;
          if (threadState && typeof threadState === "object") {
            queryClient.setQueryData(
              queryKeys.thread(requestThreadId),
              threadState as unknown as ThreadStateResponse,
            );
          }
        }
        if (event.event === "branch.action.executed") {
          const navigation = event.data.navigation ?? event.data.branch_action?.navigation;
          if (
            navigation &&
            typeof navigation.root_thread_id === "string" &&
            typeof navigation.thread_id === "string"
          ) {
            void queryClient.invalidateQueries({ queryKey: queryKeys.conversations });
            void queryClient.invalidateQueries({ queryKey: queryKeys.branchTree(navigation.root_thread_id) });
            void queryClient.invalidateQueries({ queryKey: queryKeys.thread(requestThreadId) });
            void queryClient.invalidateQueries({ queryKey: queryKeys.thread(navigation.thread_id) });
            void navigate({
              to: "/c/$conversationId/t/$threadId",
              params: {
                conversationId: navigation.root_thread_id,
                threadId: navigation.thread_id,
              },
            });
          }
        }
        if (
          activeRequestIdsRef.current.get(requestThreadId) !== requestId ||
          controller.signal.aborted
        ) {
          break;
        }
        setThreadEntries((current) =>
          patchThreadEntry(current, requestThreadId, {
            streamState: nextState,
            isStreaming: true,
          }),
        );
      }
      sendSucceeded = !nextState.failed && !controller.signal.aborted;
    } catch (error) {
      if (
        controller.signal.aborted ||
        (error instanceof Error && error.name === "AbortError")
      ) {
        sendSucceeded = false;
      } else if (
        activeRequestIdsRef.current.get(requestThreadId) === requestId &&
        !controller.signal.aborted
      ) {
        const message =
          error instanceof Error
            ? error.message
            : "Failed to send message.";
        setThreadEntries((current) =>
          patchThreadEntry(current, requestThreadId, {
            streamState: {
              ...createInitialStreamState(),
              failed: {
                error: "request_failed",
                message,
              },
              isClosed: true,
            },
          }),
        );
      }
    } finally {
      const isLatestRequest = activeRequestIdsRef.current.get(requestThreadId) === requestId;
      if (isLatestRequest) {
        const cleanup = resolveStreamRequestCleanup(sendSucceeded, controller.signal.aborted);
        abortControllersRef.current.delete(requestThreadId);
        activeRequestIdsRef.current.delete(requestThreadId);
        setThreadEntries((current) =>
          patchThreadEntry(current, requestThreadId, {
            isStreaming: false,
            pendingUserMessage: cleanup.clearPendingUserMessage
              ? null
              : current[requestThreadId]?.pendingUserMessage ?? null,
            streamState: cleanup.clearStreamState
              ? null
              : current[requestThreadId]?.streamState ?? null,
          }),
        );
      }
      void Promise.allSettled([
        queryClient.invalidateQueries({ queryKey: queryKeys.thread(requestThreadId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.branchTree(requestRootThreadId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.conversations }),
      ]);
    }

    return { ok: sendSucceeded };
  }

  function stopStreaming() {
    abortControllersRef.current.get(options.threadId)?.abort();
  }

  const currentEntry = threadEntries[options.threadId] ?? createThreadStreamEntry();

  return {
    streamState: currentEntry.streamState,
    pendingUserMessage: currentEntry.pendingUserMessage,
    isStreaming: currentEntry.isStreaming,
    sendMessage,
    stopStreaming,
  };
}
