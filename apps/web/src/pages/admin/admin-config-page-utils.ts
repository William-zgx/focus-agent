import type {
	FocusAgentAdminConfig,
	FocusAgentAdminConfigValue,
} from "@focus-agent/web-sdk";

export function isAgentBehaviorPolicyItem(item: FocusAgentAdminConfigValue) {
	return ["agent_", "branch_", "context_", "multi_agent_", "trajectory_"].some(
		(prefix) => item.key.startsWith(prefix),
	);
}

export function isSecurityPolicyItem(item: FocusAgentAdminConfigValue) {
	return (
		item.key.startsWith("rate_limit_") ||
		item.key.startsWith("auth_") ||
		item.key.includes("approval")
	);
}

export function isSecuritySystemItem(item: FocusAgentAdminConfigValue) {
	return (
		item.sensitive ||
		item.key.startsWith("auth_") ||
		item.key.startsWith("database_") ||
		item.key.startsWith("rate_limit_") ||
		item.key.includes("jwt")
	);
}

export function configSources(
	config: FocusAgentAdminConfig | undefined,
	isChineseUi: boolean,
) {
	return [
		{
			label: isChineseUi ? "模型" : "Models",
			source: config?.models.source,
		},
		{
			label: isChineseUi ? "工具" : "Tools",
			source: config?.tools.source,
		},
		{
			label: "Skills",
			source: config?.skills.source,
		},
		{
			label: isChineseUi ? "策略" : "Policies",
			source: config?.policies.source,
		},
		{
			label: isChineseUi ? "系统" : "System",
			source: config?.system.source,
		},
	];
}

export function hasConfigRestartRequirement(
	config: FocusAgentAdminConfig | undefined,
) {
	return Boolean(
		config?.models.requires_restart ||
			config?.tools.requires_restart ||
			config?.skills.requires_restart ||
			config?.policies.requires_restart,
	);
}
