import { Link } from "@tanstack/react-router";

import type { ChatNavTarget } from "@/app/shell/app-shell-config";
import {
	AdminConsoleIcon,
	ChatBubbleIcon,
	ProductivityIcon,
} from "@/shared/ui/toolbar-icons";
import { tooltipProps } from "@/shared/ui/tooltip";

type AppShellGlobalNavigationProps = {
	chatNavTarget: ChatNavTarget | null;
	isChatRoute: boolean;
	isChineseUi: boolean;
	isProductivityRoute: boolean;
};

export function AppShellGlobalNavigation({
	chatNavTarget,
	isChatRoute,
	isChineseUi,
	isProductivityRoute,
}: AppShellGlobalNavigationProps) {
	const chatNavLabel = isChineseUi ? "对话" : "Chat";
	const productivityNavLabel = isChineseUi ? "生产力" : "Productivity";
	const adminNavLabel = isChineseUi ? "系统管理" : "Administration";
	const adminNavShortLabel = isChineseUi ? "系统" : "Admin";

	return (
		<nav
			aria-label={isChineseUi ? "全局导航" : "Global navigation"}
			className="fa-sidebar-global-nav"
		>
			{chatNavTarget ? (
				<Link
					aria-label={chatNavLabel}
					className={`fa-sidebar-nav-link ${isChatRoute ? "is-active" : ""}`.trim()}
					params={chatNavTarget}
					{...tooltipProps(chatNavLabel)}
					to="/c/$conversationId/t/$threadId"
				>
					<span className="fa-sidebar-nav-icon" aria-hidden="true">
						<ChatBubbleIcon />
					</span>
					<span>{chatNavLabel}</span>
				</Link>
			) : (
				<Link
					aria-label={chatNavLabel}
					className={`fa-sidebar-nav-link ${isChatRoute ? "is-active" : ""}`.trim()}
					{...tooltipProps(chatNavLabel)}
					to="/"
				>
					<span className="fa-sidebar-nav-icon" aria-hidden="true">
						<ChatBubbleIcon />
					</span>
					<span>{chatNavLabel}</span>
				</Link>
			)}
			<Link
				aria-label={productivityNavLabel}
				className={`fa-sidebar-nav-link ${isProductivityRoute ? "is-active" : ""}`.trim()}
				{...tooltipProps(productivityNavLabel)}
				to="/productivity/tasks"
			>
				<span className="fa-sidebar-nav-icon" aria-hidden="true">
					<ProductivityIcon />
				</span>
				<span>{productivityNavLabel}</span>
			</Link>
			<Link
				aria-label={adminNavLabel}
				className="fa-sidebar-nav-link"
				{...tooltipProps(adminNavLabel)}
				to="/admin/config"
			>
				<span className="fa-sidebar-nav-icon" aria-hidden="true">
					<AdminConsoleIcon />
				</span>
				<span>{adminNavShortLabel}</span>
			</Link>
		</nav>
	);
}
