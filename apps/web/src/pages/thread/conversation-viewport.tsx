import type { ReactNode } from "react";
import type { StickToBottomInstance } from "use-stick-to-bottom";

interface ConversationViewportProps {
	children: ReactNode;
	hasTranscriptContent: boolean;
	isChineseUi: boolean;
	stickToBottom: StickToBottomInstance;
}

export function ConversationViewport({
	children,
	hasTranscriptContent,
	isChineseUi,
	stickToBottom,
}: ConversationViewportProps) {
	return (
		<div className="fa-conversation-viewport">
			<div className="fa-chat-history" ref={stickToBottom.scrollRef}>
				<div
					className={`fa-chat-history-content ${hasTranscriptContent ? "is-populated" : ""}`.trim()}
					ref={stickToBottom.contentRef}
				>
					{children}
				</div>
			</div>

			{stickToBottom.isAtBottom ? null : (
				<button
					className="fa-scroll-bottom-button"
					onClick={() =>
						void stickToBottom.scrollToBottom({
							animation: "smooth",
							ignoreEscapes: true,
						})
					}
					type="button"
				>
					{isChineseUi ? "回到底部" : "Back to bottom"}
				</button>
			)}
		</div>
	);
}
