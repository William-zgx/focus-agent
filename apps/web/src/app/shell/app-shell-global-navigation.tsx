import { Link } from "@tanstack/react-router";

import type { ChatNavTarget } from "@/app/shell/app-shell-config";
import {
	AdminConsoleIcon,
	AgentTeamIcon,
	ChatBubbleIcon,
	ProductivityIcon,
} from "@/shared/ui/toolbar-icons";
import { appEnv } from "@/shared/config/env";
import { tooltipProps } from "@/shared/ui/tooltip";

type AppShellGlobalNavigationProps = {
	chatNavTarget: ChatNavTarget | null;
	isChatRoute: boolean;
	isChineseUi: boolean;
	isProductivityRoute: boolean;
	isAgentTeamRoute: boolean;
};

export function AppShellGlobalNavigation({
	chatNavTarget,
	isChatRoute,
	isChineseUi,
	isProductivityRoute,
	isAgentTeamRoute,
}: AppShellGlobalNavigationProps) {
	const chatNavLabel = isChineseUi ? "对话" : "Chat";
	const productivityNavLabel = isChineseUi ? "生产力" : "Productivity";
	const agentTeamNavLabel = isChineseUi ? "团队" : "Team";
	const adminNavLabel = appEnv.useLocalRuntime
		? isChineseUi
			? "设备本机设置"
			: "Device-local settings"
		: isChineseUi
			? "系统管理"
			: "Administration";
	const adminNavShortLabel = appEnv.useLocalRuntime
		? isChineseUi
			? "设备本机设置"
			: "Device settings"
		: isChineseUi
			? "系统"
			: "Admin";

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
			{appEnv.features.productivity ? (
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
			) : null}
			{appEnv.features.agentTeam ? (
				<Link
					aria-label={agentTeamNavLabel}
					className={`fa-sidebar-nav-link ${isAgentTeamRoute ? "is-active" : ""}`.trim()}
					{...tooltipProps(agentTeamNavLabel)}
					to="/agent-team"
				>
					<span className="fa-sidebar-nav-icon" aria-hidden="true">
						<AgentTeamIcon />
					</span>
					<span>{agentTeamNavLabel}</span>
				</Link>
			) : null}
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
