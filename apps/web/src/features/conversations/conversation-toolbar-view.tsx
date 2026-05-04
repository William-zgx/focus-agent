import type { FocusAgentConversationSummary } from "@focus-agent/web-sdk";
import { type FormEvent, useEffect, useId, useRef } from "react";

import {
	ArchiveIcon,
	ArchiveRestoreIcon,
	TokenUsageIcon,
} from "@/shared/ui/toolbar-icons";
import { tooltipProps } from "@/shared/ui/tooltip";

import {
	conversationArchiveActionLabel,
	formatTokenCount,
} from "./conversation-toolbar-helpers";

interface ConversationToolbarViewProps {
	activeConversation?: FocusAgentConversationSummary;
	activeConversationTotalTokens: number;
	activeConversations: FocusAgentConversationSummary[];
	error?: unknown;
	isChineseUi: boolean;
	isLoading: boolean;
	isWorking: boolean;
	onArchiveToggle: (conversation: FocusAgentConversationSummary) => void;
	onCancelRename: () => void;
	onCreateConversation: () => void;
	onRenameActiveConversation: () => void;
	onRenameDraftChange: (value: string) => void;
	onRenameSubmit: (event: FormEvent<HTMLFormElement>) => void;
	onSelectConversation: (rootThreadId: string) => void;
	renameDraft: string;
	renameTarget: FocusAgentConversationSummary | null;
}

export function ConversationToolbarView({
	activeConversation,
	activeConversationTotalTokens,
	activeConversations,
	error,
	isChineseUi,
	isLoading,
	isWorking,
	onArchiveToggle,
	onCancelRename,
	onCreateConversation,
	onRenameActiveConversation,
	onRenameDraftChange,
	onRenameSubmit,
	onSelectConversation,
	renameDraft,
	renameTarget,
}: ConversationToolbarViewProps) {
	const activeConversationTokenCount = formatTokenCount(
		activeConversationTotalTokens,
	);
	const archiveActionLabel = conversationArchiveActionLabel(
		activeConversation,
		isChineseUi,
	);
	const renameInputId = useId();
	const renameInputRef = useRef<HTMLInputElement | null>(null);

	useEffect(() => {
		if (!renameTarget) return;
		renameInputRef.current?.focus();
	}, [renameTarget]);

	return (
		<div className="fa-toolbar-cluster fa-conversation-toolbar">
			<label
				className="fa-conversation-switcher"
				{...tooltipProps(
					activeConversation
						? isChineseUi
							? "切换对话；双击当前名称可重命名"
							: "Switch conversations; double-click the current name to rename"
						: isChineseUi
							? "切换或新建对话"
							: "Switch or create a conversation",
				)}
				onDoubleClick={onRenameActiveConversation}
			>
				<span className="sr-only">{isChineseUi ? "对话" : "Conversation"}</span>
				<select
					aria-label={isChineseUi ? "对话" : "Conversation"}
					className="fa-conversation-select"
					disabled={isLoading || isWorking || activeConversations.length === 0}
					onChange={(event) => onSelectConversation(event.target.value)}
					onDoubleClick={onRenameActiveConversation}
					value={activeConversation?.root_thread_id ?? ""}
				>
					{isLoading ? (
						<option value="">
							{isChineseUi ? "正在加载对话..." : "Loading conversations..."}
						</option>
					) : null}
					{!isLoading && !activeConversation ? (
						<option value="">
							{isChineseUi ? "暂无对话" : "No conversations"}
						</option>
					) : null}
					{!isLoading
						? activeConversations.map((conversation) => (
								<option
									key={conversation.root_thread_id}
									value={conversation.root_thread_id}
								>
									{conversation.title}
								</option>
							))
						: null}
				</select>
			</label>

			<div className="fa-conversation-toolbar-actions">
				{activeConversation ? (
					<button
						className="fa-conversation-token-trigger"
						{...tooltipProps(
							isChineseUi
								? `对话累计消耗 ${activeConversationTokenCount} tokens`
								: `Conversation total ${activeConversationTokenCount} tokens`,
						)}
						aria-label={
							isChineseUi
								? `对话累计消耗 ${activeConversationTokenCount} tokens`
								: `Conversation total ${activeConversationTokenCount} tokens`
						}
						type="button"
					>
						<span className="fa-toolbar-icon" aria-hidden="true">
							<TokenUsageIcon />
						</span>
					</button>
				) : null}
				<button
					className="fa-chat-toolbar-button fa-conversation-icon-button"
					{...tooltipProps(archiveActionLabel)}
					aria-label={archiveActionLabel}
					disabled={isWorking || !activeConversation}
					onClick={() =>
						activeConversation && onArchiveToggle(activeConversation)
					}
					type="button"
				>
					{activeConversation?.is_archived ? (
						<span className="fa-toolbar-icon" aria-hidden="true">
							<ArchiveRestoreIcon />
						</span>
					) : (
						<span className="fa-toolbar-icon" aria-hidden="true">
							<ArchiveIcon />
						</span>
					)}
				</button>
				<button
					className="fa-chat-toolbar-button is-primary"
					{...tooltipProps(isChineseUi ? "新建对话" : "New conversation")}
					disabled={isWorking}
					onClick={onCreateConversation}
					type="button"
				>
					{isChineseUi ? "新建" : "New"}
				</button>
			</div>

			{error ? (
				<div className="fa-toolbar-note is-danger">
					{isChineseUi ? "加载对话失败。" : "Failed to load conversations."}
				</div>
			) : null}
			{renameTarget ? (
				<form className="fa-inline-rename-form" onSubmit={onRenameSubmit}>
					<label className="sr-only" htmlFor={renameInputId}>
						{isChineseUi ? "重命名对话" : "Rename conversation"}
					</label>
					<input
						id={renameInputId}
						className="fa-inline-rename-input"
						ref={renameInputRef}
						value={renameDraft}
						onChange={(event) => onRenameDraftChange(event.target.value)}
						disabled={isWorking}
					/>
					<button
						className="fa-branch-action-button is-primary"
						disabled={isWorking || !renameDraft.trim()}
						type="submit"
					>
						{isChineseUi ? "保存" : "Save"}
					</button>
					<button
						className="fa-branch-action-button"
						disabled={isWorking}
						onClick={onCancelRename}
						type="button"
					>
						{isChineseUi ? "取消" : "Cancel"}
					</button>
				</form>
			) : null}
		</div>
	);
}
