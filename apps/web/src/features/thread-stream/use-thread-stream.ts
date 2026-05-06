import {
  createToolApprovalDecision,
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

const STREAM_STATE_BATCH_MS = 40;

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

  async function runStreamRequest({
    requestThreadId,
    requestRootThreadId,
    requestId,
    controller,
    streamFactory,
  }: {
    requestThreadId: string;
    requestRootThreadId: string;
    requestId: string;
    controller: AbortController;
    streamFactory: () => ReturnType<typeof client.streamTurn>;
  }): Promise<SendMessageResult> {
    setThreadEntries((current) =>
      patchThreadEntry(current, requestThreadId, {
        streamState: createInitialStreamState(),
        isStreaming: true,
      }),
    );

    let sendSucceeded = false;
    let nextState = createInitialStreamState();
    let pendingStreamState: typeof nextState | null = null;
    let scheduledFrame: number | null = null;
    let scheduledTimeout: ReturnType<typeof setTimeout> | null = null;
    const cancelPendingStreamStateFlush = () => {
      if (scheduledFrame !== null) {
        cancelAnimationFrame(scheduledFrame);
        scheduledFrame = null;
      }
      if (scheduledTimeout !== null) {
        clearTimeout(scheduledTimeout);
        scheduledTimeout = null;
      }
      pendingStreamState = null;
    };
    const flushPendingStreamState = () => {
      if (scheduledFrame !== null) {
        cancelAnimationFrame(scheduledFrame);
      }
      if (scheduledTimeout !== null) {
        clearTimeout(scheduledTimeout);
      }
      scheduledFrame = null;
      scheduledTimeout = null;
      const streamState = pendingStreamState;
      pendingStreamState = null;
      if (!streamState) return;
      if (!requestRegistry.isCurrentStreamRequest(requestThreadId, requestId, controller)) {
        return;
      }
      setThreadEntries((current) =>
        patchThreadEntry(current, requestThreadId, {
          streamState,
          isStreaming: true,
        }),
      );
    };
    const scheduleStreamStateFlush = () => {
      if (scheduledFrame !== null || scheduledTimeout !== null) return;
      if (typeof requestAnimationFrame === "function") {
        scheduledFrame = requestAnimationFrame(flushPendingStreamState);
        return;
      }
      scheduledTimeout = setTimeout(flushPendingStreamState, STREAM_STATE_BATCH_MS);
    };

    try {
      const stream = await streamFactory();

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
        pendingStreamState = nextState;
        scheduleStreamStateFlush();
      }
      sendSucceeded = !nextState.failed && !controller.signal.aborted;
    } catch (error) {
      if (isAbortError(error, controller)) {
        sendSucceeded = false;
      } else if (requestRegistry.isCurrentStreamRequest(requestThreadId, requestId, controller)) {
        cancelPendingStreamStateFlush();
        setThreadEntries((current) =>
          patchThreadEntry(current, requestThreadId, createFailedStreamEntryPatch(error)),
        );
      }
    } finally {
      if (controller.signal.aborted) {
        cancelPendingStreamStateFlush();
      } else {
        flushPendingStreamState();
      }
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

    const requestPayload = {
      thread_id: requestThreadId,
      message,
      model: overrides?.model || options.selectedModel || undefined,
      thinking_mode: resolveThinkingModeForRequest(
        overrides,
        options.selectedThinkingMode,
      ),
    };

    return runStreamRequest({
      requestThreadId,
      requestRootThreadId,
      requestId,
      controller,
      streamFactory: () =>
        client.streamTurn(requestPayload, { signal: controller.signal }),
    });
  }

  async function resumeToolApproval(approved: boolean): Promise<SendMessageResult> {
    const requestThreadId = options.threadId;
    const requestRootThreadId = options.rootThreadId;
    const { requestId, controller } = requestRegistry.beginStreamRequest(requestThreadId);

    return runStreamRequest({
      requestThreadId,
      requestRootThreadId,
      requestId,
      controller,
      streamFactory: () =>
        client.streamResume(
          {
            thread_id: requestThreadId,
            resume: createToolApprovalDecision(approved),
          },
          { signal: controller.signal },
        ),
    });
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
    resumeToolApproval,
    stopStreaming,
  };
}
