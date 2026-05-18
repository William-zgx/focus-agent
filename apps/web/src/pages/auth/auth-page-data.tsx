import {
	AdminConsoleIcon,
	AgentTeamIcon,
	BranchFocusIcon,
	ChatBubbleIcon,
	ProductivityIcon,
	TokenUsageIcon,
} from "@/shared/ui/toolbar-icons";

export const LOGIN_DESTINATIONS = [
	{
		description: "继续长上下文对话、分支探索与结论回填。",
		kicker: "Chat",
		label: "主对话",
		to: "/",
		icon: <ChatBubbleIcon className="fa-auth-entry-card-icon" />,
	},
	{
		description: "拆分复杂任务，跟踪并发执行与合并交接。",
		kicker: "Team",
		label: "Agent Team",
		to: "/agent-team",
		icon: <AgentTeamIcon className="fa-auth-entry-card-icon" />,
	},
	{
		description: "管理角色、工具路由、记忆候选与策略变更。",
		kicker: "Control",
		label: "治理台",
		to: "/agent/governance",
		icon: <BranchFocusIcon className="fa-auth-entry-card-icon" />,
	},
	{
		description: "查看运行轨迹、健康信号与复盘证据。",
		kicker: "Review",
		label: "复盘诊断",
		to: "/observability/overview",
		icon: <TokenUsageIcon className="fa-auth-entry-card-icon" />,
	},
	{
		description: "沉淀任务与笔记，把对话行动落到清单。",
		kicker: "Productivity",
		label: "效率清单",
		to: "/productivity/tasks",
		icon: <ProductivityIcon className="fa-auth-entry-card-icon" />,
	},
	{
		description: "维护用户、审计、模型与工具配置。",
		kicker: "Admin",
		label: "配置中心",
		to: "/admin/config",
		icon: <AdminConsoleIcon className="fa-auth-entry-card-icon" />,
	},
] as const;

export const LOGIN_CAPABILITIES = [
	{
		label: "会话",
		value: "上下文 / 分支 / 结论",
	},
	{
		label: "协作",
		value: "任务分工 / 并发推进",
	},
	{
		label: "治理",
		value: "角色 / 工具 / 记忆",
	},
	{
		label: "诊断",
		value: "轨迹 / 健康 / 审计",
	},
] as const;

export const ACCOUNT_ACTIONS = [
	{
		description: "管理头像、显示名等资料",
		label: "账号信息",
		to: "/account/profile",
	},
	{ description: "修改登录密码", label: "安全设置", to: "/account/security" },
	{
		description: "查看并关闭其他会话",
		label: "会话管理",
		to: "/account/sessions",
	},
] as const;

export const QUICK_START_ACTIONS = [
	{ description: "继续长上下文、分支探索与结论回填", label: "主对话", to: "/" },
	{
		description: "拆分复杂任务，跟踪并发执行与合并交接",
		label: "Agent Team",
		to: "/agent-team",
	},
	{
		description: "管理角色、工具路由、记忆候选与策略变更",
		label: "治理台",
		to: "/agent/governance",
	},
	{
		description: "查看运行轨迹、健康信号与复盘证据",
		label: "复盘诊断",
		to: "/observability/overview",
	},
	{
		description: "沉淀任务与笔记，把对话行动落到清单",
		label: "效率清单",
		to: "/productivity/tasks",
	},
] as const;

export const ADMIN_SHORTCUTS = [
	{
		description: "用户、角色与状态治理",
		label: "用户管理",
		to: "/admin/users",
	},
	{
		description: "查看审计记录与变更",
		label: "审计中心",
		to: "/admin/audit-events",
	},
	{
		description: "维护模型、工具与系统策略",
		label: "配置中心",
		to: "/admin/config",
	},
] as const;
