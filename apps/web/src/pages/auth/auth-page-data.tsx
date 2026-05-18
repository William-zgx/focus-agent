import {
	AgentTeamIcon,
	BranchFocusIcon,
	TokenUsageIcon,
} from "@/shared/ui/toolbar-icons";

export const LOGIN_DESTINATIONS = [
	{
		description: "发起对话，快速进入会话工作区。",
		label: "正式对话",
		to: "/",
		icon: <BranchFocusIcon className="fa-auth-entry-card-icon" />,
	},
	{
		description: "多人协作，分工推进复杂工作。",
		label: "团队协作",
		to: "/agent-team",
		icon: <AgentTeamIcon className="fa-auth-entry-card-icon" />,
	},
	{
		description: "查看会话轨迹，追踪决策与复盘。",
		label: "复盘台",
		to: "/observability/trajectory",
		icon: <TokenUsageIcon className="fa-auth-entry-card-icon" />,
	},
] as const;

export const LOGIN_MOTION_ORBS = [
	{
		className: "fa-auth-orb-one fa-auth-orb-soft",
	},
	{
		className: "fa-auth-orb-two fa-auth-orb-soft",
	},
	{
		className: "fa-auth-orb-four fa-auth-orb-soft",
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
	{ description: "进入主会话和分支任务页", label: "正式对话", to: "/" },
	{ description: "进入团队协作工作台", label: "团队合作", to: "/agent-team" },
	{
		description: "查看轨迹与复盘",
		label: "复盘台",
		to: "/observability/trajectory",
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
] as const;
