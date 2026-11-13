import { useCallback, useEffect } from "react";
import { useStickToBottom } from "use-stick-to-bottom";

interface UseThreadAutoFollowOptions {
	threadId: string;
}

export function useThreadAutoFollow({ threadId }: UseThreadAutoFollowOptions) {
	const stickToBottom = useStickToBottom({
		initial: "instant",
		resize: "smooth",
	});
	const { scrollToBottom: scrollStickToBottom } = stickToBottom;

	const scrollToBottom = useCallback(() => {
		void scrollStickToBottom({
			animation: "smooth",
			wait: true,
		});
	}, [scrollStickToBottom]);

	const followAndScrollToBottom = useCallback(() => {
		void scrollStickToBottom({
			animation: "smooth",
			duration: 250,
			ignoreEscapes: true,
		});
	}, [scrollStickToBottom]);

	useEffect(() => {
		void threadId;
		void scrollStickToBottom("instant");
	}, [scrollStickToBottom, threadId]);

	return {
		followAndScrollToBottom,
		scrollToBottom,
		stickToBottom,
	};
}
