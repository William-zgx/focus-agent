import { useCallback, useEffect, useLayoutEffect, useRef } from "react";
import { useStickToBottom } from "use-stick-to-bottom";

interface UseThreadAutoFollowOptions {
	branchActionCount: number;
	hasTranscriptContent: boolean;
	isStreaming: boolean;
	lastTranscriptMessageContent?: unknown;
	lastTranscriptMessageId?: unknown;
	streamFailedMessage?: string;
	streamProcessingStepSignal?: string;
	streamReasoningText?: string;
	streamToolCallCount: number;
	streamToolEventCount: number;
	toolApprovalInterruptCount: number;
	askUserQuestionInterruptCount?: number;
	streamVisibleText?: string;
	threadId: string;
	transcriptMessageCount: number;
}

export function useThreadAutoFollow({
	hasTranscriptContent,
}: UseThreadAutoFollowOptions) {
	const stickToBottom = useStickToBottom({
		initial: "instant",
		resize: "smooth",
	});
	const {
		escapedFromLock,
		isNearBottom,
		scrollToBottom: scrollStickToBottom,
	} = stickToBottom;
	const shouldAutoFollowRef = useRef(true);

	const scrollToBottom = useCallback(() => {
		void scrollStickToBottom({
			animation: "smooth",
			wait: true,
		});
	}, [scrollStickToBottom]);

	const followAndScrollToBottom = useCallback(() => {
		shouldAutoFollowRef.current = true;
		void scrollStickToBottom({
			animation: "smooth",
			duration: 250,
			ignoreEscapes: true,
		});
	}, [scrollStickToBottom]);

	useEffect(() => {
		if (escapedFromLock) {
			shouldAutoFollowRef.current = false;
		}
		if (isNearBottom) {
			shouldAutoFollowRef.current = true;
		}
	}, [escapedFromLock, isNearBottom]);

	useEffect(() => {
		shouldAutoFollowRef.current = true;
		void scrollStickToBottom("instant");
	}, [scrollStickToBottom]);

	useLayoutEffect(() => {
		if (
			!hasTranscriptContent ||
			(!shouldAutoFollowRef.current && !isNearBottom)
		) {
			return;
		}
		scrollToBottom();
	}, [hasTranscriptContent, isNearBottom, scrollToBottom]);

	return {
		followAndScrollToBottom,
		scrollToBottom,
		stickToBottom,
	};
}
