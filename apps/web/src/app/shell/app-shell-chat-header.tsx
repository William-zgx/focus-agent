import type {
	Dispatch,
	FocusEventHandler,
	MouseEventHandler,
	SetStateAction,
} from "react";
import { useState } from "react";

import { ConversationToolbar } from "@/features/conversations/conversation-toolbar";
import { ThreadHeaderActions } from "@/features/thread/thread-header-actions";
import { FocusAgentBrand } from "@/shared/ui/focus-agent-brand";
import { tooltipProps } from "@/shared/ui/tooltip";

type ShellStatus = {
	tone: "info" | "success" | "warn" | "danger";
	text: string;
	display?: "inline" | "chat-floating";
};

type ShellTooltipHandlers = {
	onBlur: FocusEventHandler<HTMLElement>;
	onFocus: FocusEventHandler<HTMLElement>;
	onMouseEnter: MouseEventHandler<HTMLElement>;
	onMouseLeave: MouseEventHandler<HTMLElement>;
};

type AppShellChatHeaderProps = {
	onOpenSidebar: () => void;
	onToggleSidebar: () => void;
	shellStatus: ShellStatus | null;
	sidebarCollapsed: boolean;
	sidebarToggleLabel: string;
	tooltipHandlers: ShellTooltipHandlers;
};

export type HeaderRenameScope = "conversation" | "branch" | null;
export type HeaderRenameScopeSetter = Dispatch<
	SetStateAction<HeaderRenameScope>
>;

export function AppShellChatHeader({
	onOpenSidebar,
	onToggleSidebar,
	shellStatus,
	sidebarCollapsed,
	sidebarToggleLabel,
	tooltipHandlers,
}: AppShellChatHeaderProps) {
	const [activeRenameScope, setActiveRenameScope] =
		useState<HeaderRenameScope>(null);

	return (
		<section className="fa-header-card">
			<div className="fa-chat-header-top">
				<div className="fa-chat-header-copy">
					<button
						className={`fa-chat-logo-toggle ${sidebarCollapsed ? "is-sidebar-collapsed" : ""}`}
						{...tooltipProps(sidebarToggleLabel)}
						{...tooltipHandlers}
						onClick={onToggleSidebar}
						type="button"
						aria-label={sidebarToggleLabel}
					>
						<FocusAgentBrand compact />
					</button>
					<ConversationToolbar
						activeRenameScope={activeRenameScope}
						onRenameScopeChange={setActiveRenameScope}
					/>
				</div>
				<div className="fa-chat-header-right-actions">
					<ThreadHeaderActions
						activeRenameScope={activeRenameScope}
						onRenameScopeChange={setActiveRenameScope}
						onRequestOpenSidebar={onOpenSidebar}
					/>
				</div>
			</div>
			{shellStatus && shellStatus.display !== "chat-floating" ? (
				<div className={`fa-shell-status-line is-${shellStatus.tone}`}>
					{shellStatus.text}
				</div>
			) : null}
		</section>
	);
}
