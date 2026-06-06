import type {
	FocusAgentAdminSkillConfigEntry,
	FocusAgentAdminConfigSource,
	FocusAgentAdminConfigValue,
} from "@focus-agent/web-sdk";
import { useMemo, useState } from "react";

import { AdminField, AdminPanelHeader } from "./admin-page-sections";
import {
	ConfigSourceMeta,
	ReadOnlyConfigValue,
	ToggleControl,
} from "./admin-config-controls";
import type { ConfigSection } from "./admin-config-draft-utils";

type OverviewMetric = {
	caption: string;
	label: string;
	value: string;
};

type SourceEntry = {
	label: string;
	source?: FocusAgentAdminConfigSource;
};

function metricTiles(metrics: OverviewMetric[]) {
	return (
		<div className="fa-admin-config-metric-grid">
			{metrics.map((metric) => (
				<div className="fa-admin-config-metric-tile" key={metric.label}>
					<span>{metric.label}</span>
					<strong>{metric.value}</strong>
					<small>{metric.caption}</small>
				</div>
			))}
		</div>
	);
}

function sourceRows(isChineseUi: boolean, entries: SourceEntry[]) {
	return (
		<div className="fa-admin-config-source-list">
			{entries.map((entry) => (
				<div className="fa-admin-config-source-row" key={entry.label}>
					<strong>{entry.label}</strong>
					<ConfigSourceMeta isChineseUi={isChineseUi} source={entry.source} />
				</div>
			))}
		</div>
	);
}

function metadataText(
	item: FocusAgentAdminSkillConfigEntry,
	key: "path" | "prompt_mode" | "source_id",
) {
	const directValue = item[key];
	if (typeof directValue === "string" && directValue.trim()) return directValue;
	return "";
}

type SkillListField =
	| "aliases"
	| "capability_requirements"
	| "domains"
	| "intents"
	| "localized_triggers"
	| "recommended_tools"
	| "triggers"
	| "when_to_use";

function skillListValues(
	item: FocusAgentAdminSkillConfigEntry,
	key: SkillListField,
) {
	const value = item[key] as unknown;
	if (!Array.isArray(value)) return [];
	return value
		.map((entry) => String(entry ?? "").trim())
		.filter((entry) => entry.length > 0);
}

function compactSkillValues(values: string[], limit = 5) {
	const unique = Array.from(new Set(values));
	const shown = unique.slice(0, limit);
	const hiddenCount = Math.max(0, unique.length - shown.length);
	return hiddenCount ? [...shown, `+${hiddenCount}`] : shown;
}

function errorText(error: Error | null, isChineseUi: boolean) {
	if (!error) return "";
	return error.message || (isChineseUi ? "加载失败。" : "Failed to load.");
}

export function AdminConfigOverviewPanel({
	isChineseUi,
	metrics,
	onSectionChange,
	requiresRestart,
	sources,
}: {
	isChineseUi: boolean;
	metrics: OverviewMetric[];
	onSectionChange: (section: ConfigSection) => void;
	requiresRestart: boolean;
	sources: SourceEntry[];
}) {
	const actions: Array<{
		description: string;
		label: string;
		section: ConfigSection;
	}> = [
		{
			label: isChineseUi ? "配置模型连接" : "Configure connections",
			description: isChineseUi
				? "维护 Provider、API Key 状态与默认模型。"
				: "Manage providers, API key state, and defaults.",
			section: "connections",
		},
		{
			label: isChineseUi ? "管理能力" : "Manage capabilities",
			description: isChineseUi
				? "调整工具与 Skill 的可用状态。"
				: "Tune tool and skill availability.",
			section: "capabilities",
		},
		{
			label: isChineseUi ? "调整 Agent 行为" : "Tune agent behavior",
			description: isChineseUi
				? "控制路由、委派、记忆与上下文策略。"
				: "Control routing, delegation, memory, and context policies.",
			section: "agent",
		},
	];

	return (
		<section className="fa-admin-panel fa-admin-config-panel">
			<AdminPanelHeader
				eyebrow={isChineseUi ? "Overview" : "Overview"}
				status={
					requiresRestart
						? isChineseUi
							? "有变更需要重启"
							: "restart required"
						: isChineseUi
							? "运行中"
							: "active"
				}
				title={
					isChineseUi ? "设置与能力总览" : "Settings & Capability Overview"
				}
			/>
			<p className="fa-admin-config-help">
				{isChineseUi
					? "按用户意图组织高频配置：先看连接是否可用，再决定开放哪些能力，最后调整 Agent 行为。"
					: "High-frequency settings are grouped by intent: confirm connections, expose capabilities, then tune agent behavior."}
			</p>
			{metricTiles(metrics)}
			<div className="fa-admin-config-action-grid">
				{actions.map((action) => (
					<button
						className="fa-admin-config-action-tile"
						key={action.section}
						type="button"
						onClick={() => onSectionChange(action.section)}
					>
						<strong>{action.label}</strong>
						<span>{action.description}</span>
					</button>
				))}
			</div>
			<div className="fa-admin-config-section">
				<div className="fa-admin-config-section-head">
					<strong>{isChineseUi ? "配置来源" : "Config sources"}</strong>
				</div>
				{sourceRows(isChineseUi, sources)}
			</div>
		</section>
	);
}

export function ConnectionsSummaryPanel({
	configuredProviderCount,
	isChineseUi,
	modelProviderCount,
	toolProviderCount,
}: {
	configuredProviderCount: number;
	isChineseUi: boolean;
	modelProviderCount: number;
	toolProviderCount: number;
}) {
	return (
		<section className="fa-admin-panel fa-admin-config-panel">
			<AdminPanelHeader
				eyebrow={isChineseUi ? "Connections" : "Connections"}
				status={null}
				title={isChineseUi ? "外部连接" : "External Connections"}
			/>
			<p className="fa-admin-config-help">
				{isChineseUi
					? "模型 Provider 是当前可编辑连接；MCP Server 属于扩展连接，等后端合同接入后可在这里管理。"
					: "Model providers are editable now; MCP servers are extension connections reserved for the backend contract."}
			</p>
			{metricTiles([
				{
					label: isChineseUi ? "模型 Provider" : "Model providers",
					value: `${configuredProviderCount}/${modelProviderCount}`,
					caption: isChineseUi
						? "已配置 Key 或 Base URL"
						: "With key or base URL",
				},
				{
					label: isChineseUi ? "工具 Provider" : "Tool providers",
					value: String(toolProviderCount),
					caption: isChineseUi ? "在能力区维护" : "Managed in capabilities",
				},
				{
					label: "MCP",
					value: "-",
					caption: isChineseUi
						? "等待扩展配置合同"
						: "Awaiting extension config contract",
				},
			])}
			<div className="fa-admin-config-value-row">
				<div className="fa-admin-config-readonly-head">
					<strong>{isChineseUi ? "MCP Server" : "MCP servers"}</strong>
					<span>{isChineseUi ? "预留入口" : "reserved"}</span>
				</div>
				<p>
					{isChineseUi
						? "这里预留连接测试、启停、secret mask 与热重载状态；当前前端不伪造后端未提供的 MCP 数据。"
						: "Reserved for connection tests, enablement, secret masking, and reload state; the UI does not invent MCP data before the backend contract lands."}
				</p>
			</div>
		</section>
	);
}

function SkillMetaGroup({
	label,
	skillId,
	values,
}: {
	label: string;
	skillId: string;
	values: string[];
}) {
	if (!values.length) return null;
	return (
		<>
			<span>{label}</span>
			{values.map((value) => (
				<span key={`${label}-${skillId}-${value}`}>{value}</span>
			))}
		</>
	);
}

export function SkillManagementPanel({
	disabled,
	error,
	globalEnabled,
	isChineseUi,
	items,
	loading,
	onGlobalToggle,
	onSkillToggle,
	pendingSkillId,
}: {
	disabled: boolean;
	error: Error | null;
	globalEnabled: boolean;
	isChineseUi: boolean;
	items: FocusAgentAdminSkillConfigEntry[];
	loading: boolean;
	onGlobalToggle: (enabled: boolean) => void;
	onSkillToggle: (
		skill: FocusAgentAdminSkillConfigEntry,
		enabled: boolean,
	) => void;
	pendingSkillId: string | null;
}) {
	const [query, setQuery] = useState("");
	const normalizedQuery = query.trim().toLowerCase();
	const visibleItems = useMemo(
		() =>
			normalizedQuery
				? items.filter((item) =>
						[
							item.skill_id,
							item.description ?? "",
							...skillListValues(item, "when_to_use"),
							...skillListValues(item, "triggers"),
							...skillListValues(item, "localized_triggers"),
							...skillListValues(item, "aliases"),
							...skillListValues(item, "domains"),
							...skillListValues(item, "intents"),
							...skillListValues(item, "recommended_tools"),
							...skillListValues(item, "capability_requirements"),
						]
							.join(" ")
							.toLowerCase()
							.includes(normalizedQuery),
					)
				: items,
		[items, normalizedQuery],
	);
	const enabledCount = items.filter((item) => item.enabled).length;

	return (
		<section className="fa-admin-panel fa-admin-config-panel">
			<AdminPanelHeader
				eyebrow={isChineseUi ? "Skills" : "Skills"}
				status={loading ? (isChineseUi ? "加载中" : "loading") : null}
				title={isChineseUi ? "Skill 管理" : "Skill Management"}
			/>
			<p className="fa-admin-config-help">
				{isChineseUi
					? "管理运行时 Skill catalog 的全局启用状态。目录、来源与语义匹配等低频选项保留在高级区域。"
					: "Manage global runtime skill availability. Directories, sources, and semantic matching stay in the advanced area."}
			</p>
			<div className="fa-admin-config-value-row">
				<ToggleControl
					checked={globalEnabled}
					disabled={disabled}
					label={isChineseUi ? "启用 Skill 系统" : "Enable skill system"}
					onChange={onGlobalToggle}
				/>
				<p>
					{isChineseUi
						? "关闭后，Skill 目录仍会展示，但不会自动选择、前缀触发或注入上下文。"
						: "When disabled, the catalog remains visible, but skills are not selected, prefix-triggered, or injected into context."}
				</p>
			</div>
			<div className="fa-admin-form-grid is-two">
				<AdminField label={isChineseUi ? "搜索 Skill" : "Search skills"}>
					<input
						placeholder={
							isChineseUi
								? "按名称、触发词、别名、领域、意图或工具搜索"
								: "Name, trigger, alias, domain, intent, or tool"
						}
						value={query}
						onChange={(event) => setQuery(event.target.value)}
					/>
				</AdminField>
				<div className="fa-admin-config-inline-metrics">
					<span>
						{isChineseUi ? "启用" : "Enabled"} {enabledCount}/{items.length}
					</span>
				</div>
			</div>
			{error ? (
				<div className="fa-inline-notice is-danger">
					{errorText(error, isChineseUi)}
				</div>
			) : null}
			<div className="fa-admin-config-list">
				{visibleItems.map((skill) => {
					const sourceId = metadataText(skill, "source_id");
					const promptMode = metadataText(skill, "prompt_mode");
					const path = metadataText(skill, "path");
					const isPending = pendingSkillId === skill.skill_id;
					const triggerChips = compactSkillValues([
						...skillListValues(skill, "triggers"),
						...skillListValues(skill, "localized_triggers"),
					]);
					const meaningChips = compactSkillValues([
						...skillListValues(skill, "aliases"),
						...skillListValues(skill, "intents"),
						...skillListValues(skill, "domains"),
					]);
					const runtimeChips = compactSkillValues([
						...skillListValues(skill, "recommended_tools"),
						...skillListValues(skill, "capability_requirements"),
						...(promptMode ? [promptMode] : []),
						...(path ? [path] : []),
					]);
					return (
						<div
							className="fa-admin-config-value-row fa-admin-config-skill-row"
							key={skill.skill_id}
						>
							<div className="fa-admin-config-card-head">
								<div className="fa-admin-config-title-stack">
									<strong>{skill.skill_id}</strong>
									<span>{skill.skill_id}</span>
								</div>
								<div className="fa-admin-chip-row">
									<span>
										{skill.enabled
											? isChineseUi
												? "启用"
												: "enabled"
											: isChineseUi
												? "停用"
												: "disabled"}
									</span>
									{sourceId ? <span>{sourceId}</span> : null}
								</div>
							</div>
							<p>{skill.description || skill.when_to_use.join("; ") || "-"}</p>
							<div className="fa-admin-picker-list">
								<ToggleControl
									checked={skill.enabled}
									disabled={disabled || isPending}
									label={isChineseUi ? "启用 Skill" : "Enable skill"}
									onChange={(checked) => onSkillToggle(skill, checked)}
								/>
							</div>
							<div className="fa-admin-config-skill-meta">
								<SkillMetaGroup
									label={isChineseUi ? "触发" : "Triggers"}
									skillId={skill.skill_id}
									values={triggerChips}
								/>
								<SkillMetaGroup
									label={isChineseUi ? "含义" : "Meaning"}
									skillId={skill.skill_id}
									values={meaningChips}
								/>
								<SkillMetaGroup
									label={isChineseUi ? "运行" : "Runtime"}
									skillId={skill.skill_id}
									values={runtimeChips}
								/>
							</div>
						</div>
					);
				})}
				{!visibleItems.length ? (
					<div className="fa-admin-config-value-row">
						<div className="fa-admin-config-readonly-head">
							<strong>
								{isChineseUi ? "暂无匹配 Skill" : "No matching skills"}
							</strong>
							<span>{loading ? "..." : String(items.length)}</span>
						</div>
						<p>
							{isChineseUi
								? "当前 Skill catalog 为空，或搜索条件没有命中。"
								: "The skill catalog is empty, or the current search has no matches."}
						</p>
					</div>
				) : null}
			</div>
		</section>
	);
}

export function SecurityRuntimePanel({
	isChineseUi,
	policyItems,
	runtimeItems,
	securityItems,
	source,
}: {
	isChineseUi: boolean;
	policyItems: FocusAgentAdminConfigValue[];
	runtimeItems: FocusAgentAdminConfigValue[];
	securityItems: FocusAgentAdminConfigValue[];
	source?: FocusAgentAdminConfigSource;
}) {
	return (
		<section className="fa-admin-panel fa-admin-config-panel">
			<AdminPanelHeader
				eyebrow={isChineseUi ? "Runtime" : "Runtime"}
				status={null}
				title={isChineseUi ? "安全与运行" : "Security & Runtime"}
			/>
			<p className="fa-admin-config-help">
				{isChineseUi
					? "敏感配置只显示是否已配置；认证、数据库、API 监听和限流类信息集中在这里。"
					: "Sensitive settings show configured state only; auth, database, API binding, and rate-limit state live here."}
			</p>
			<ConfigSourceMeta isChineseUi={isChineseUi} source={source} />
			<div className="fa-admin-config-section">
				<div className="fa-admin-config-section-head">
					<strong>{isChineseUi ? "敏感与访问控制" : "Secrets & access"}</strong>
				</div>
				<div className="fa-admin-config-list">
					{securityItems.map((item) => (
						<ReadOnlyConfigValue
							isChineseUi={isChineseUi}
							item={item}
							key={item.key}
						/>
					))}
					{!securityItems.length ? (
						<div className="fa-admin-config-value-row">
							<p>
								{isChineseUi
									? "暂无敏感配置项。"
									: "No sensitive config items."}
							</p>
						</div>
					) : null}
				</div>
			</div>
			<div className="fa-admin-config-section">
				<div className="fa-admin-config-section-head">
					<strong>{isChineseUi ? "运行环境" : "Runtime environment"}</strong>
				</div>
				<div className="fa-admin-config-list">
					{runtimeItems.map((item) => (
						<ReadOnlyConfigValue
							isChineseUi={isChineseUi}
							item={item}
							key={item.key}
						/>
					))}
				</div>
			</div>
			{policyItems.length ? (
				<div className="fa-admin-config-section">
					<div className="fa-admin-config-section-head">
						<strong>{isChineseUi ? "运行策略" : "Runtime policies"}</strong>
					</div>
					<p className="fa-admin-config-help">
						{isChineseUi
							? "可编辑的安全/限流策略会在下方表单中维护。"
							: "Editable security or rate-limit policies are managed in the form below."}
					</p>
				</div>
			) : null}
		</section>
	);
}

export function AdvancedConfigPanel({
	advancedPolicyCount,
	isChineseUi,
	sources,
}: {
	advancedPolicyCount: number;
	isChineseUi: boolean;
	sources: SourceEntry[];
}) {
	return (
		<section className="fa-admin-panel fa-admin-config-panel">
			<AdminPanelHeader
				eyebrow={isChineseUi ? "Advanced" : "Advanced"}
				status={null}
				title={isChineseUi ? "高级配置" : "Advanced Config"}
			/>
			<p className="fa-admin-config-help">
				{isChineseUi
					? "这里保留低频、工程向和难以归类的配置入口，避免污染主要用户流程。"
					: "Low-frequency and engineering-oriented settings stay here so primary workflows remain clean."}
			</p>
			{sourceRows(isChineseUi, sources)}
			<div className="fa-admin-config-value-row">
				<div className="fa-admin-config-readonly-head">
					<strong>{isChineseUi ? "低频策略" : "Low-frequency policies"}</strong>
					<span>{advancedPolicyCount}</span>
				</div>
				<p>
					{advancedPolicyCount
						? isChineseUi
							? "下方表单展示未归入 Agent 行为或安全运行的可编辑策略。"
							: "The form below contains editable policies not grouped under agent behavior or security/runtime."
						: isChineseUi
							? "暂无需要单独维护的高级策略。"
							: "No advanced policies need separate maintenance."}
				</p>
			</div>
		</section>
	);
}
