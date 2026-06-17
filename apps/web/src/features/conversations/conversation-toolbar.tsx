import type { FocusAgentConversationSummary } from "@focus-agent/web-sdk";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { type FormEvent, useEffect, useMemo, useState } from "react";

import type {
	HeaderRenameScope,
	HeaderRenameScopeSetter,
} from "@/app/shell/app-shell-chat-header";
import { useShellUi } from "@/app/shell/shell-ui-context";
import { totalConversationTokens } from "@/features/conversations/conversation-toolbar-helpers";
import { ConversationToolbarView } from "@/features/conversations/conversation-toolbar-view";
import { useConversationActions } from "@/features/conversations/use-conversation-actions";
import { useConversations } from "@/features/conversations/use-conversations";

interface ConversationToolbarProps {
	activeRenameScope?: HeaderRenameScope;
	onRenameScopeChange?: HeaderRenameScopeSetter;
}

export function ConversationToolbar({
	activeRenameScope,
	onRenameScopeChange,
}: ConversationToolbarProps = {}) {
	const navigate = useNavigate();
	const { conversationId, threadId } = useRouterState({
		select: (state) => {
			const lastMatch = state.matches[state.matches.length - 1];
			const routeParams = (lastMatch?.params ?? {}) as Partial<
				Record<"conversationId" | "threadId", string>
			>;

			return {
				conversationId: String(routeParams.conversationId ?? ""),
				threadId: String(routeParams.threadId ?? ""),
			};
		},
	});
	const { data, isLoading, error } = useConversations();
	const {
		createConversation,
		renameConversation,
		archiveConversation,
		activateConversation,
	} = useConversationActions();
	const [isWorking, setIsWorking] = useState(false);
	const [renameTarget, setRenameTarget] =
		useState<FocusAgentConversationSummary | null>(null);
	const [renameDraft, setRenameDraft] = useState("");
	const conversations = data?.conversations ?? [];
	const { isChineseUi, setShellStatus } = useShellUi();
	const activeConversations = conversations.filter(
		(conversation) => !conversation.is_archived,
	);

	const activeConversation = useMemo(
		() =>
			activeConversations.find(
				(conversation) => conversation.root_thread_id === conversationId,
			) ?? activeConversations[0],
		[activeConversations, conversationId],
	);
	const activeConversationTotalTokens =
		totalConversationTokens(activeConversation);
	const canShowConversationRename =
		activeRenameScope === undefined || activeRenameScope === "conversation";
	const visibleRenameTarget = canShowConversationRename ? renameTarget : null;

	async function openConversation(rootThreadId: string) {
		await navigate({
			to: "/c/$conversationId/t/$threadId",
			params: {
				conversationId: rootThreadId,
				threadId: rootThreadId,
			},
		});
	}

	async function handleSelectConversation(nextConversationId: string) {
		if (!nextConversationId) return;
		await openConversation(nextConversationId);
	}

	async function handleCreateConversation() {
		setIsWorking(true);
		try {
			setShellStatus(
				{
					tone: "warn",
					text: isChineseUi ? "正在创建对话" : "Creating conversation",
					display: "chat-floating",
				},
				{ autoClearMs: 2200 },
			);
			const conversation = await createConversation();
			await openConversation(conversation.root_thread_id);
			setShellStatus(
				{
					tone: "success",
					text: isChineseUi ? "对话已创建" : "Conversation created",
					display: "chat-floating",
				},
				{ autoClearMs: 2200 },
			);
		} finally {
			setIsWorking(false);
		}
	}

	function startRenameConversation(
		conversation: FocusAgentConversationSummary,
	) {
		onRenameScopeChange?.("conversation");
		setRenameTarget(conversation);
		setRenameDraft(conversation.title);
	}

	function cancelRenameConversation() {
		setRenameTarget(null);
		setRenameDraft("");
		onRenameScopeChange?.((currentScope) =>
			currentScope === "conversation" ? null : currentScope,
		);
	}

	useEffect(() => {
		if (
			renameTarget &&
			activeRenameScope !== undefined &&
			activeRenameScope !== "conversation"
		) {
			setRenameTarget(null);
			setRenameDraft("");
		}
	}, [activeRenameScope, renameTarget]);

	async function handleRenameConversation(event: FormEvent<HTMLFormElement>) {
		event.preventDefault();
		if (!renameTarget) return;
		if (!canShowConversationRename) {
			cancelRenameConversation();
			return;
		}
		const title = renameDraft.trim();
		if (!title || title === renameTarget.title) {
			cancelRenameConversation();
			return;
		}
		setIsWorking(true);
		try {
			setShellStatus(
				{
					tone: "warn",
					text: isChineseUi ? "正在重命名对话" : "Renaming conversation",
					display: "chat-floating",
				},
				{ autoClearMs: 2200 },
			);
			await renameConversation(renameTarget.root_thread_id, title);
			setShellStatus(
				{
					tone: "success",
					text: isChineseUi ? "对话已重命名" : "Conversation renamed",
					display: "chat-floating",
				},
				{ autoClearMs: 2200 },
			);
			cancelRenameConversation();
		} finally {
			setIsWorking(false);
		}
	}

	async function handleArchiveToggle(
		conversation: FocusAgentConversationSummary,
	) {
		setIsWorking(true);
		try {
			if (conversation.is_archived) {
				setShellStatus(
					{
						tone: "warn",
						text: isChineseUi ? "正在恢复对话" : "Restoring conversation",
						display: "chat-floating",
					},
					{ autoClearMs: 2200 },
				);
				await activateConversation(conversation.root_thread_id);
				setShellStatus(
					{
						tone: "success",
						text: isChineseUi ? "对话已恢复" : "Conversation restored",
						display: "chat-floating",
					},
					{ autoClearMs: 2200 },
				);
			} else {
				setShellStatus(
					{
						tone: "warn",
						text: isChineseUi ? "正在归档对话" : "Archiving conversation",
						display: "chat-floating",
					},
					{ autoClearMs: 2200 },
				);
				await archiveConversation(conversation.root_thread_id);
				const nextConversation = conversations.find(
					(item) =>
						item.root_thread_id !== conversation.root_thread_id &&
						!item.is_archived,
				);

				if (nextConversation) {
					await openConversation(nextConversation.root_thread_id);
				} else if (threadId) {
					await navigate({ to: "/" });
				}
				setShellStatus(
					{
						tone: "success",
						text: isChineseUi ? "对话已归档" : "Conversation archived",
						display: "chat-floating",
					},
					{ autoClearMs: 2200 },
				);
			}
		} finally {
			setIsWorking(false);
		}
	}

	async function handleRenameActiveConversation() {
		if (!activeConversation || isWorking) return;
		startRenameConversation(activeConversation);
	}

	return (
		<ConversationToolbarView
			activeConversation={activeConversation}
			activeConversationTotalTokens={activeConversationTotalTokens}
			activeConversations={activeConversations}
			error={error}
			isChineseUi={isChineseUi}
			isLoading={isLoading}
			isWorking={isWorking}
			onArchiveToggle={(conversation) => void handleArchiveToggle(conversation)}
			onCancelRename={cancelRenameConversation}
			onCreateConversation={() => void handleCreateConversation()}
			onRenameActiveConversation={() => void handleRenameActiveConversation()}
			onRenameDraftChange={setRenameDraft}
			onRenameSubmit={(event) => void handleRenameConversation(event)}
			onSelectConversation={(rootThreadId) =>
				void handleSelectConversation(rootThreadId)
			}
			renameDraft={renameDraft}
			renameTarget={visibleRenameTarget}
		/>
	);
}
