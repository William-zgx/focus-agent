import { useNavigate } from "@tanstack/react-router";
import { useEffect } from "react";

import { useShellUi } from "@/app/shell/shell-ui-context";
import { useConversations } from "@/features/conversations/use-conversations";
import { EmptyState, Toast } from "@/shared/ui/primitives";

export function HomePage() {
	const navigate = useNavigate();
	const { isChineseUi } = useShellUi();
	const { data, isLoading } = useConversations();
	const conversations = data?.conversations ?? [];
	const firstActiveConversation =
		conversations.find((item) => !item.is_archived) ?? conversations[0];

	useEffect(() => {
		if (isLoading || !firstActiveConversation) return;
		void navigate({
			to: "/c/$conversationId/t/$threadId",
			params: {
				conversationId: firstActiveConversation.root_thread_id,
				threadId: firstActiveConversation.root_thread_id,
			},
			replace: true,
		});
	}, [firstActiveConversation, isLoading, navigate]);

	return (
		<div className="fa-thread-layout">
			<section className="fa-chat-transcript">
				<div className="fa-chat-history">
					<div className="fa-chat-history-content">
						<EmptyState
							className="fa-chat-empty"
							title={
								isChineseUi
									? "从这里开始聊天。只要 Agent 产生分支，左侧就会显示出来。"
									: "Start chatting here. Branches appear on the left whenever the agent forks work."
							}
						/>
					</div>
				</div>
			</section>

			<section className="fa-composer-slot">
				<Toast className="fa-inline-notice" tone="info">
					{isChineseUi
						? "在这里发送第一条消息。需要探索另一条路径时，再新建分支。"
						: "Send the first message here. Create a branch only when you want to explore a separate path."}
				</Toast>
			</section>
		</div>
	);
}
