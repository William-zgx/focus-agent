import type { ConfigSection } from "./admin-config-draft-utils";

export function ConfigSectionPicker({
	active,
	isChineseUi,
	onChange,
	summary,
}: {
	active: ConfigSection;
	isChineseUi: boolean;
	onChange: (section: ConfigSection) => void;
	summary: {
		defaultModel: string;
		enabledSkillCount: number;
		enabledToolCount: number;
		modelProviderCount: number;
		modelCount: number;
		configuredModelProviderCount: number;
		policyCount: number;
		securityItemCount: number;
		skillCount: number;
		sourceCount: number;
		systemCount: number;
		toolCount: number;
		toolProviderCount: number;
	};
}) {
	const options: Array<{
		ariaLabel: string;
		key: ConfigSection;
		description: string;
		label: string;
		metric: string;
	}> = [
		{
			key: "overview",
			label: isChineseUi ? "总览" : "Overview",
			metric: summary.defaultModel,
			description: isChineseUi
				? "核心连接、能力与运行状态"
				: "Core connections, capabilities, and runtime state",
			ariaLabel: isChineseUi
				? `默认 ${summary.defaultModel}`
				: `Default ${summary.defaultModel}`,
		},
		{
			key: "connections",
			label: isChineseUi ? "连接" : "Connections",
			metric: `${summary.configuredModelProviderCount}/${summary.modelProviderCount}`,
			description: isChineseUi
				? "模型 Provider、API Key 与外部扩展"
				: "Model providers, API keys, and external extensions",
			ariaLabel: isChineseUi
				? "模型 Provider 与扩展"
				: "Model providers and extensions",
		},
		{
			key: "capabilities",
			label: isChineseUi ? "能力" : "Capabilities",
			metric: `${summary.enabledToolCount}/${summary.toolCount}`,
			description: isChineseUi
				? "工具、Skill、Toolset 与运行能力"
				: "Tools, skills, toolsets, and runtime capabilities",
			ariaLabel: isChineseUi
				? `${summary.enabledSkillCount} 个 Skill 启用`
				: `${summary.enabledSkillCount} skills enabled`,
		},
		{
			key: "agent",
			label: isChineseUi ? "Agent 行为" : "Agent Behavior",
			metric: String(summary.policyCount),
			description: isChineseUi
				? "路由、委派、记忆与上下文策略"
				: "Routing, delegation, memory, and context policies",
			ariaLabel: isChineseUi ? "Agent 策略" : "Agent policies",
		},
		{
			key: "security",
			label: isChineseUi ? "安全与运行" : "Security & Runtime",
			metric: String(summary.securityItemCount),
			description: isChineseUi
				? "运行环境、审计与敏感配置"
				: "Runtime, audit, and secrets",
			ariaLabel: isChineseUi ? "运行环境与敏感项" : "Runtime and secrets",
		},
		{
			key: "advanced",
			label: isChineseUi ? "高级" : "Advanced",
			metric: String(summary.sourceCount),
			description: isChineseUi
				? "配置文件来源与低频选项"
				: "Config sources and low-frequency options",
			ariaLabel: isChineseUi
				? `${summary.sourceCount} 个配置来源`
				: `${summary.sourceCount} config sources`,
		},
	];

	return (
		<div className="fa-admin-config-section-picker" role="tablist">
			{options.map((option) => (
				<button
					aria-label={`${option.label}: ${option.ariaLabel}`}
					aria-selected={active === option.key}
					className={`fa-admin-config-section-option ${
						active === option.key ? "is-active" : ""
					}`.trim()}
					key={option.key}
					role="tab"
					type="button"
					onClick={() => onChange(option.key)}
				>
					<span>{option.label}</span>
					<strong>{option.metric}</strong>
					<small>{option.description}</small>
				</button>
			))}
		</div>
	);
}
