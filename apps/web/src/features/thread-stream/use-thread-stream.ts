import {
  createInitialStreamState,
  reduceStreamEvent,
} from "@focus-agent/web-sdk";
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { useFocusAgent } from "@/shared/sdk/focus-agent-provider";

import {
  createOptimisticThreadStreamEntry,
  createThreadStreamEntry,
  nextThreadEntryMap,
  patchThreadEntry,
  resolveThinkingModeForRequest,
  type SendMessageOverrides,
  type SendMessageResult,
  type ThreadStreamEntry,
} from "./stream-entry-state";
import { useStreamRequestRegistry } from "./use-stream-request-registry";
import {
  applyTurnCompletedCacheUpdate,
  invalidateThreadStreamSurfaces,
} from "./use-thread-stream-cache";
import {
  createFailedStreamEntryPatch,
  isAbortError,
  resolveStreamRequestCleanup,
} from "./use-thread-stream-errors";
import { useThreadStreamNavigation } from "./use-thread-stream-navigation";

interface UseThreadStreamOptions {
  threadId: string;
  rootThreadId: string;
  selectedModel?: string;
  selectedThinkingMode?: string;
}

export {
  createOptimisticThreadStreamEntry,
  createThreadStreamEntry,
  nextThreadEntryMap,
  patchThreadEntry,
  resolveThinkingModeForRequest,
  type PendingUserMessage,
  type SendMessageOverrides,
  type SendMessageResult,
  type ThreadStreamEntry,
} from "./stream-entry-state";
export {
  createFailedStreamEntryPatch,
  isAbortError,
  messageFromStreamError,
  resolveStreamRequestCleanup,
} from "./use-thread-stream-errors";
export { navigationFromBranchActionPayload } from "./use-thread-stream-navigation";

export function useThreadStream(options: UseThreadStreamOptions) {
  const { client } = useFocusAgent();
  const queryClient = useQueryClient();
  const requestRegistry = useStreamRequestRegistry();
  const { handleBranchActionExecuted } = useThreadStreamNavigation();
  const [threadEntries, setThreadEntries] = useState<Record<string, ThreadStreamEntry>>({});

  async function sendMessage(
    message: string,
    overrides?: SendMessageOverrides,
  ): Promise<SendMessageResult> {
    const requestThreadId = options.threadId;
    const requestRootThreadId = options.rootThreadId;
    const { requestId, controller } = requestRegistry.beginStreamRequest(requestThreadId);
    setThreadEntries((current) =>
      nextThreadEntryMap(
        current,
        requestThreadId,
        createOptimisticThreadStreamEntry(requestThreadId, message),
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
        if (!requestRegistry.isCurrentStreamRequest(requestThreadId, requestId, controller)) {
          break;
        }

        nextState = reduceStreamEvent(nextState, event);

        if (event.event === "turn.completed") {
          applyTurnCompletedCacheUpdate(
            queryClient,
            requestThreadId,
            event.data.thread_state,
          );
        }

        if (event.event === "branch.action.executed") {
          handleBranchActionExecuted(event.data, requestThreadId);
        }

        if (!requestRegistry.isCurrentStreamRequest(requestThreadId, requestId, controller)) {
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
      if (isAbortError(error, controller)) {
        sendSucceeded = false;
      } else if (requestRegistry.isCurrentStreamRequest(requestThreadId, requestId, controller)) {
        setThreadEntries((current) =>
          patchThreadEntry(current, requestThreadId, createFailedStreamEntryPatch(error)),
        );
      }
    } finally {
      const isLatestRequest = requestRegistry.completeStreamRequest(requestThreadId, requestId);
      if (isLatestRequest) {
        const cleanup = resolveStreamRequestCleanup(sendSucceeded, controller.signal.aborted);
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
      void invalidateThreadStreamSurfaces(queryClient, requestRootThreadId, requestThreadId);
    }

    return { ok: sendSucceeded };
  }

  function stopStreaming() {
    requestRegistry.stopStreamRequest(options.threadId);
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
