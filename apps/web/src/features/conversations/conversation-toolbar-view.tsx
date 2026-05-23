import type { FocusAgentConversationSummary } from "@focus-agent/web-sdk";
import {
	type CSSProperties,
	type FormEvent,
	type SyntheticEvent,
	useEffect,
	useId,
	useRef,
	useState,
} from "react";

import {
	ArchiveIcon,
	ArchiveRestoreIcon,
	ChatBubbleIcon,
	ConversationActionsIcon,
	NewConversationIcon,
	RenameConversationIcon,
	TokenUsageIcon,
} from "@/shared/ui/toolbar-icons";
import { tooltipProps } from "@/shared/ui/tooltip";

import {
	conversationArchiveActionLabel,
	formatTokenCount,
} from "./conversation-toolbar-helpers";

const COMPACT_CONVERSATION_ACTIONS_QUERY = "(max-width: 900px)";
const ICON_CONVERSATION_SWITCHER_QUERY = "(max-width: 520px)";
const ICON_CONVERSATION_SWITCHER_STYLES: Record<
	"icon" | "select" | "switcher" | "jump" | "svg",
	CSSProperties
> = {
	switcher: {
		display: "grid",
		gridTemplateColumns: "34px",
		width: 34,
		minWidth: 34,
		maxWidth: 34,
		flex: "0 0 34px",
	},
	jump: {
		width: 34,
		minWidth: 34,
		maxWidth: 34,
		height: 34,
		flex: "0 0 34px",
	},
	select: {
		width: 34,
		minWidth: 34,
		maxWidth: 34,
		height: 34,
		padding: 0,
		color: "transparent",
		textIndent: "100%",
	},
	icon: {
		position: "absolute",
		inset: 0,
		zIndex: 1,
		display: "inline-flex",
		alignItems: "center",
		justifyContent: "center",
		color: "color-mix(in srgb, var(--fa-accent) 84%, var(--fa-text) 16%)",
		pointerEvents: "none",
	},
	svg: {
		width: 17,
		height: 17,
	},
};

function mediaQueryMatches(query: string): boolean {
	return typeof window !== "undefined" && window.matchMedia(query).matches;
}

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
	const [usesCompactConversationActions, setUsesCompactConversationActions] =
		useState(() => mediaQueryMatches(COMPACT_CONVERSATION_ACTIONS_QUERY));
	const [usesIconConversationSwitcher, setUsesIconConversationSwitcher] =
		useState(() => mediaQueryMatches(ICON_CONVERSATION_SWITCHER_QUERY));
	const [isCompactMenuOpen, setCompactMenuOpen] = useState(false);
	const [compactMenuPosition, setCompactMenuPosition] = useState({
		right: 12,
		top: 68,
	});
	const renameInputId = useId();
	const renameInputRef = useRef<HTMLInputElement | null>(null);

	useEffect(() => {
		const actionsQuery = window.matchMedia(COMPACT_CONVERSATION_ACTIONS_QUERY);
		const switcherQuery = window.matchMedia(ICON_CONVERSATION_SWITCHER_QUERY);
		const syncViewportQueries = () => {
			setUsesCompactConversationActions(actionsQuery.matches);
			setUsesIconConversationSwitcher(switcherQuery.matches);
		};

		syncViewportQueries();
		actionsQuery.addEventListener("change", syncViewportQueries);
		switcherQuery.addEventListener("change", syncViewportQueries);
		return () => {
			actionsQuery.removeEventListener("change", syncViewportQueries);
			switcherQuery.removeEventListener("change", syncViewportQueries);
		};
	}, []);

	useEffect(() => {
		if (!usesCompactConversationActions) {
			setCompactMenuOpen(false);
		}
	}, [usesCompactConversationActions]);

	useEffect(() => {
		if (!renameTarget) return;
		renameInputRef.current?.focus();
	}, [renameTarget]);

	function closeCompactMenu() {
		setCompactMenuOpen(false);
	}

	function handleCompactMenuToggle(event: SyntheticEvent<HTMLDetailsElement>) {
		const isOpen = event.currentTarget.open;
		setCompactMenuOpen(isOpen);
		if (!isOpen) return;
		const triggerRect = event.currentTarget.getBoundingClientRect();
		setCompactMenuPosition({
			right: Math.max(12, window.innerWidth - triggerRect.right),
			top: Math.round(triggerRect.bottom + 8),
		});
	}

	function handleCompactRename() {
		closeCompactMenu();
		onRenameActiveConversation();
	}

	function handleCompactArchive(conversation: FocusAgentConversationSummary) {
		closeCompactMenu();
		onArchiveToggle(conversation);
	}

	function handleCompactCreateConversation() {
		closeCompactMenu();
		onCreateConversation();
	}

	return (
		<div className="fa-toolbar-cluster fa-conversation-toolbar">
			{renameTarget ? (
				<form
					className="fa-inline-rename-form is-conversation"
					onSubmit={onRenameSubmit}
				>
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
			) : (
				<div
					className={
						usesIconConversationSwitcher
							? "fa-conversation-switcher-icon"
							: "fa-conversation-switcher"
					}
					style={
						usesIconConversationSwitcher
							? ICON_CONVERSATION_SWITCHER_STYLES.switcher
							: undefined
					}
				>
					<label
						className="fa-conversation-jump"
						style={
							usesIconConversationSwitcher
								? ICON_CONVERSATION_SWITCHER_STYLES.jump
								: undefined
						}
						{...tooltipProps(isChineseUi ? "切换对话" : "Switch conversations")}
					>
						{usesIconConversationSwitcher ? (
							<span
								className="fa-conversation-jump-icon"
								aria-hidden="true"
								style={ICON_CONVERSATION_SWITCHER_STYLES.icon}
							>
								<ChatBubbleIcon style={ICON_CONVERSATION_SWITCHER_STYLES.svg} />
							</span>
						) : null}
						<span className="sr-only">
							{isChineseUi ? "切换对话" : "Switch conversation"}
						</span>
						<select
							aria-label={
								activeConversation
									? isChineseUi
										? `切换对话，当前：${activeConversation.title}`
										: `Switch conversation, current: ${activeConversation.title}`
									: isChineseUi
										? "切换对话"
										: "Switch conversation"
							}
							className="fa-conversation-select fa-conversation-jump-select"
							disabled={
								isLoading || isWorking || activeConversations.length === 0
							}
							onChange={(event) => onSelectConversation(event.target.value)}
							style={
								usesIconConversationSwitcher
									? ICON_CONVERSATION_SWITCHER_STYLES.select
									: undefined
							}
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
					<button
						aria-label={
							activeConversation
								? isChineseUi
									? `重命名当前对话：${activeConversation.title}`
									: `Rename current conversation: ${activeConversation.title}`
								: isChineseUi
									? "暂无当前对话"
									: "No current conversation"
						}
						className="fa-chat-toolbar-button fa-conversation-icon-button fa-conversation-rename-button"
						disabled={!activeConversation || isWorking}
						onClick={onRenameActiveConversation}
						type="button"
						{...tooltipProps(
							activeConversation
								? isChineseUi
									? "重命名当前对话"
									: "Rename this conversation"
								: isChineseUi
									? "暂无当前对话"
									: "No current conversation",
						)}
						hidden={usesCompactConversationActions}
					>
						<span className="fa-toolbar-icon" aria-hidden="true">
							<RenameConversationIcon />
						</span>
					</button>
				</div>
			)}

			{usesCompactConversationActions && !renameTarget ? (
				<details
					className="fa-agent-team-more-menu fa-conversation-actions-menu"
					onToggle={handleCompactMenuToggle}
					open={isCompactMenuOpen}
				>
					<summary
						className="fa-chat-toolbar-button fa-conversation-icon-button fa-conversation-actions-trigger"
						{...tooltipProps(isChineseUi ? "会话管理" : "Conversation actions")}
						aria-label={isChineseUi ? "会话管理" : "Conversation actions"}
					>
						<span className="fa-toolbar-icon" aria-hidden="true">
							<ConversationActionsIcon />
						</span>
					</summary>
					{isCompactMenuOpen ? (
						<div
							className="fa-agent-team-more-menu-panel fa-conversation-actions-menu-panel"
							style={{
								left: "auto",
								maxWidth: "calc(100vw - 24px)",
								position: "fixed",
								right: compactMenuPosition.right,
								top: compactMenuPosition.top,
								zIndex: "var(--fa-z-dropdown)",
							}}
						>
							{activeConversation ? (
								<button disabled type="button">
									<span className="fa-toolbar-icon" aria-hidden="true">
										<TokenUsageIcon />
									</span>
									<span>
										{isChineseUi
											? `累计 ${activeConversationTokenCount} tokens`
											: `${activeConversationTokenCount} tokens total`}
									</span>
								</button>
							) : null}
							<button
								disabled={!activeConversation || isWorking}
								onClick={handleCompactRename}
								type="button"
							>
								<span className="fa-toolbar-icon" aria-hidden="true">
									<RenameConversationIcon />
								</span>
								<span>
									{isChineseUi ? "重命名当前对话" : "Rename conversation"}
								</span>
							</button>
							<button
								disabled={isWorking || !activeConversation}
								onClick={() =>
									activeConversation && handleCompactArchive(activeConversation)
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
								<span>{archiveActionLabel}</span>
							</button>
							<button
								disabled={isWorking}
								onClick={handleCompactCreateConversation}
								type="button"
							>
								<span className="fa-toolbar-icon" aria-hidden="true">
									<NewConversationIcon />
								</span>
								<span>{isChineseUi ? "新建对话" : "New conversation"}</span>
							</button>
						</div>
					) : null}
				</details>
			) : null}

			<div
				className="fa-conversation-toolbar-actions"
				hidden={usesCompactConversationActions}
			>
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
					aria-label={isChineseUi ? "新建对话" : "New conversation"}
					disabled={isWorking}
					onClick={onCreateConversation}
					type="button"
				>
					<span className="fa-toolbar-icon" aria-hidden="true">
						<NewConversationIcon />
					</span>
					<span className="fa-toolbar-text">
						{isChineseUi ? "新建" : "New"}
					</span>
				</button>
			</div>

			{error ? (
				<div className="fa-toolbar-note is-danger">
					{isChineseUi ? "加载对话失败。" : "Failed to load conversations."}
				</div>
			) : null}
		</div>
	);
}
