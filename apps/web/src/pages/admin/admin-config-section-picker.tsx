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
		modelCount: number;
		policyCount: number;
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
			key: "models",
			label: isChineseUi ? "模型" : "Models",
			metric: String(summary.modelCount),
			description: isChineseUi
				? "默认模型、助手模型与模型提供方"
				: "Default model, assistant model, and providers.",
			ariaLabel: isChineseUi
				? `默认 ${summary.defaultModel}`
				: `Default ${summary.defaultModel}`,
		},
		{
			key: "tools",
			label: isChineseUi ? "工具" : "Tools",
			metric: `${summary.toolCount} / ${summary.toolProviderCount}`,
			description: isChineseUi
				? "工具能力、可用列表与 Provider"
				: "Tool capabilities, catalog, and providers",
			ariaLabel: isChineseUi ? "工具与 Provider" : "Tools and providers",
		},
		{
			key: "policies",
			label: isChineseUi ? "策略" : "Policies",
			metric: String(summary.policyCount),
			description: isChineseUi
				? "分支推荐策略与路由治理规则"
				: "Branch recommendation and routing policies",
			ariaLabel: isChineseUi
				? "分支推荐、路由与治理"
				: "Branching, routing, and governance",
		},
		{
			key: "system",
			label: isChineseUi ? "系统" : "System",
			metric: String(summary.systemCount),
			description: isChineseUi
				? "运行环境、审计与敏感配置"
				: "Runtime, audit, and secrets",
			ariaLabel: isChineseUi ? "运行环境与敏感项" : "Runtime and secrets",
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
