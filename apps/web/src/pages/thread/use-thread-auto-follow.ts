import { useCallback, useEffect, useLayoutEffect, useRef } from "react";

interface UseThreadAutoFollowOptions {
  branchActionCount: number;
  hasTranscriptContent: boolean;
  isStreaming: boolean;
  lastTranscriptMessageContent?: unknown;
  lastTranscriptMessageId?: unknown;
  streamFailedMessage?: string;
  streamReasoningText?: string;
  streamToolCallCount: number;
  streamToolEventCount: number;
  toolApprovalInterruptCount: number;
  streamVisibleText?: string;
  threadId: string;
  transcriptMessageCount: number;
}

function isNearBottom(element: HTMLElement) {
  const distance = element.scrollHeight - element.clientHeight - element.scrollTop;
  return distance <= 48;
}

export function useThreadAutoFollow({
  branchActionCount,
  hasTranscriptContent,
  isStreaming,
  lastTranscriptMessageContent,
  lastTranscriptMessageId,
  streamFailedMessage,
  streamReasoningText,
  streamToolCallCount,
  streamToolEventCount,
  toolApprovalInterruptCount,
  streamVisibleText,
  threadId,
  transcriptMessageCount,
}: UseThreadAutoFollowOptions) {
  const historyRef = useRef<HTMLDivElement | null>(null);
  const shouldAutoFollowRef = useRef(true);

  const scrollToBottom = useCallback(() => {
    const history = historyRef.current;
    if (!history) return;
    history.scrollTop = history.scrollHeight;
  }, []);

  const followAndScrollToBottom = useCallback(() => {
    shouldAutoFollowRef.current = true;
    scrollToBottom();
  }, [scrollToBottom]);

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
    branchActionCount,
    hasTranscriptContent,
    isStreaming,
    lastTranscriptMessageContent,
    lastTranscriptMessageId,
    scrollToBottom,
    streamFailedMessage,
    streamReasoningText,
    streamToolCallCount,
    streamToolEventCount,
    toolApprovalInterruptCount,
    streamVisibleText,
    threadId,
    transcriptMessageCount,
  ]);

  return {
    followAndScrollToBottom,
    historyRef,
    scrollToBottom,
  };
}
