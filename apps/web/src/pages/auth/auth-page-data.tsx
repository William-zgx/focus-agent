import { appEnv } from "@/shared/config/env";

function isEnabledDestination(path: string) {
	if (path.startsWith("/agent/memory")) return appEnv.features.agentMemory;
	if (path.startsWith("/observability/")) return appEnv.features.observability;
	if (path.startsWith("/productivity/")) return appEnv.features.productivity;
	return true;
}

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

const QUICK_START_ACTIONS_BASE = [
	{ description: "继续长上下文、分支探索与结论回填", label: "主对话", to: "/" },
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

export const QUICK_START_ACTIONS = QUICK_START_ACTIONS_BASE.filter((item) =>
	isEnabledDestination(item.to),
);

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
