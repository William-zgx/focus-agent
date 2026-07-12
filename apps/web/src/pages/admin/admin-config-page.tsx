import type {
	FocusAgentAdminSkillConfigEntry,
	FocusAgentUpdateAdminModelConfigEntry,
	FocusAgentUpdateAdminModelConfigRequest,
	FocusAgentUpdateAdminModelProviderConfig,
	FocusAgentUpdateAdminToolConfigEntry,
	FocusAgentUpdateAdminToolConfigRequest,
	FocusAgentUpdateAdminToolProviderConfig,
} from "@focus-agent/web-sdk";
import type { FormEvent } from "react";
import { useEffect, useMemo, useState } from "react";

import { useShellUi } from "@/app/shell/shell-ui-context";
import {
	useUpdateAdminModelConfig,
	useUpdateAdminPolicyConfig,
	useUpdateAdminSkillConfig,
	useUpdateAdminToolConfig,
} from "@/features/admin-config/use-admin-config";
import { appEnv } from "@/shared/config/env";

import { AdminConsoleLayout, AdminErrorMessage } from "./admin-page-chrome";
import {
	buildModelDraft,
	buildPolicyDraft,
	buildToolDraft,
	coercePolicyValue,
	emptyModelProviderDraft,
	emptyToolProviderDraft,
	nullableText,
	splitList,
	uniqueList,
} from "./admin-config-draft-utils";
import type {
	ConfigSection,
	EditableConfigSection,
	ModelDraft,
	ModelEntryDraft,
	ModelProviderDraft,
	PolicyDraft,
	PolicyDraftValue,
	ToolDraft,
	ToolEntryDraft,
	ToolProviderDraft,
} from "./admin-config-draft-utils";
import { ModelConfigPanel } from "./admin-config-model-panel";
import { ConfigSectionPicker } from "./admin-config-section-picker";
import {
	AdvancedConfigPanel,
	AdminConfigOverviewPanel,
	ConnectionsSummaryPanel,
	SecurityRuntimePanel,
	SkillManagementPanel,
} from "./admin-config-intent-panels";
import {
	PolicyConfigPanel,
	ToolConfigPanel,
} from "./admin-config-tool-policy-panels";
import {
	configSources,
	hasConfigRestartRequirement,
	isAgentBehaviorPolicyItem,
	isSecurityPolicyItem,
	isSecuritySystemItem,
} from "./admin-config-page-utils";
import { useSelectedAdminConfigQuery } from "./admin-config-page-query";

export function AdminConfigPage() {
	const { isChineseUi } = useShellUi();
	const configQuery = useSelectedAdminConfigQuery();
	const modelMutation = useUpdateAdminModelConfig();
	const toolMutation = useUpdateAdminToolConfig();
	const policyMutation = useUpdateAdminPolicyConfig();
	const skillMutation = useUpdateAdminSkillConfig();
	const [modelDraft, setModelDraft] = useState<ModelDraft>(() =>
		buildModelDraft(undefined),
	);
	const [toolDraft, setToolDraft] = useState<ToolDraft>(() =>
		buildToolDraft(undefined),
	);
	const [policyDraft, setPolicyDraft] = useState<PolicyDraft>(() =>
		buildPolicyDraft(undefined),
	);
	const [activeConfigSection, setActiveConfigSection] =
		useState<ConfigSection>("overview");
	const [formError, setFormError] = useState("");
	const [pendingSkillId, setPendingSkillId] = useState<string | null>(null);
	const config = configQuery.data;
	const skillItems = config?.skills.catalog ?? [];
	const editablePolicyItems = useMemo(
		() => (config?.policies.items ?? []).filter((item) => item.editable),
		[config?.policies.items],
	);
	const agentPolicyItems = useMemo(
		() => editablePolicyItems.filter(isAgentBehaviorPolicyItem),
		[editablePolicyItems],
	);
	const securityPolicyItems = useMemo(
		() =>
			editablePolicyItems.filter(
				(item) =>
					isSecurityPolicyItem(item) && !isAgentBehaviorPolicyItem(item),
			),
		[editablePolicyItems],
	);
	const advancedPolicyItems = useMemo(
		() =>
			editablePolicyItems.filter(
				(item) =>
					!isAgentBehaviorPolicyItem(item) && !isSecurityPolicyItem(item),
			),
		[editablePolicyItems],
	);
	const systemItems = config?.system.items ?? [];
	const securitySystemItems = useMemo(
		() => systemItems.filter(isSecuritySystemItem),
		[systemItems],
	);
	const runtimeSystemItems = useMemo(
		() => systemItems.filter((item) => !isSecuritySystemItem(item)),
		[systemItems],
	);
	const sources = useMemo(
		() => configSources(config, isChineseUi),
		[config, isChineseUi],
	);
	const pendingSection: EditableConfigSection | null = modelMutation.isPending
		? "models"
		: toolMutation.isPending
			? "tools"
			: policyMutation.isPending
				? "policies"
				: null;
	const summary = useMemo(
		() => ({
			defaultModel: config?.models?.default_model || "-",
			configuredModelProviderCount:
				config?.models?.providers?.filter(
					(provider) =>
						provider.api_key_configured || provider.base_url_configured,
				).length ?? 0,
			enabledSkillCount: skillItems.filter((skill) => skill.enabled).length,
			enabledToolCount:
				config?.tools?.tools?.filter((tool) => tool.enabled).length ?? 0,
			modelProviderCount: config?.models?.providers?.length ?? 0,
			modelCount: config?.models?.models?.length ?? 0,
			policyCount: config?.policies?.items?.length ?? 0,
			securityItemCount:
				securitySystemItems.length + securityPolicyItems.length,
			skillCount: skillItems.length,
			sourceCount: sources.filter((entry) => Boolean(entry.source)).length,
			systemCount: config?.system?.items?.length ?? 0,
			toolCount: config?.tools?.tools?.length ?? 0,
			toolProviderCount: config?.tools?.providers?.length ?? 0,
		}),
		[
			config,
			securityPolicyItems.length,
			securitySystemItems.length,
			skillItems,
			sources,
		],
	);
	const overviewMetrics = useMemo(
		() => [
			{
				label: isChineseUi ? "默认模型" : "Default model",
				value: summary.defaultModel,
				caption: isChineseUi
					? `${summary.modelCount} 个模型`
					: `${summary.modelCount} models`,
			},
			{
				label: isChineseUi ? "模型连接" : "Model connections",
				value: `${summary.configuredModelProviderCount}/${summary.modelProviderCount}`,
				caption: isChineseUi ? "Provider 已配置" : "Providers configured",
			},
			{
				label: isChineseUi ? "工具能力" : "Tool capabilities",
				value: `${summary.enabledToolCount}/${summary.toolCount}`,
				caption: isChineseUi ? "工具已启用" : "Tools enabled",
			},
			{
				label: "Skills",
				value: `${summary.enabledSkillCount}/${summary.skillCount}`,
				caption: isChineseUi ? "Skill 已启用" : "Skills enabled",
			},
			{
				label: isChineseUi ? "Agent 策略" : "Agent policies",
				value: String(agentPolicyItems.length),
				caption: isChineseUi
					? "行为开关与阈值"
					: "Behavior toggles and thresholds",
			},
			{
				label: isChineseUi ? "运行安全" : "Runtime safety",
				value: String(summary.securityItemCount),
				caption: isChineseUi ? "敏感/访问控制项" : "Secret and access items",
			},
		],
		[agentPolicyItems.length, isChineseUi, summary],
	);
	const requiresRestart = hasConfigRestartRequirement(config);

	useEffect(() => {
		if (!config) return;
		setModelDraft(buildModelDraft(config));
		setToolDraft(buildToolDraft(config));
		setPolicyDraft(buildPolicyDraft(config));
		setFormError("");
	}, [config]);

	const modelChoiceOptions = useMemo(
		() =>
			uniqueList([
				modelDraft.defaultModel,
				modelDraft.helperModel,
				...modelDraft.modelChoices,
				...modelDraft.models.map((model) => model.id),
			]),
		[
			modelDraft.defaultModel,
			modelDraft.helperModel,
			modelDraft.modelChoices,
			modelDraft.models,
		],
	);
	const disabled = Boolean(pendingSection || skillMutation.isPending);

	function updateModelChoice(modelId: string, checked: boolean) {
		setModelDraft((current) => ({
			...current,
			modelChoices: checked
				? uniqueList([...current.modelChoices, modelId])
				: current.modelChoices.filter((item) => item !== modelId),
		}));
	}

	function updateModelProvider(
		index: number,
		patch: Partial<ModelProviderDraft>,
	) {
		setModelDraft((current) => ({
			...current,
			providers: current.providers.map((provider, providerIndex) =>
				providerIndex === index ? { ...provider, ...patch } : provider,
			),
		}));
	}

	function removeModelProvider(index: number) {
		setModelDraft((current) => ({
			...current,
			providers: current.providers.filter(
				(_, providerIndex) => providerIndex !== index,
			),
		}));
	}

	function updateModelEntry(index: number, patch: Partial<ModelEntryDraft>) {
		setModelDraft((current) => ({
			...current,
			models: current.models.map((model, modelIndex) =>
				modelIndex === index ? { ...model, ...patch } : model,
			),
		}));
	}

	function updateToolEntry(index: number, patch: Partial<ToolEntryDraft>) {
		setToolDraft((current) => ({
			...current,
			tools: current.tools.map((tool, toolIndex) =>
				toolIndex === index ? { ...tool, ...patch } : tool,
			),
		}));
	}

	function updateToolProvider(
		index: number,
		patch: Partial<ToolProviderDraft>,
	) {
		setToolDraft((current) => ({
			...current,
			providers: current.providers.map((provider, providerIndex) =>
				providerIndex === index ? { ...provider, ...patch } : provider,
			),
		}));
	}

	function removeToolProvider(index: number) {
		setToolDraft((current) => ({
			...current,
			providers: current.providers.filter(
				(_, providerIndex) => providerIndex !== index,
			),
		}));
	}

	function updatePolicyValue(key: string, value: PolicyDraftValue) {
		setPolicyDraft((current) => ({
			...current,
			values: { ...current.values, [key]: value },
		}));
	}

	async function handleModelSubmit(event: FormEvent<HTMLFormElement>) {
		event.preventDefault();
		setFormError("");
		try {
			const providers: FocusAgentUpdateAdminModelProviderConfig[] =
				modelDraft.providers.map((provider) => {
					const id = provider.id.trim();
					if (!id) {
						throw new Error(
							isChineseUi
								? "Provider ID 不能为空。"
								: "Provider ID is required.",
						);
					}
					const requestProvider: FocusAgentUpdateAdminModelProviderConfig = {
						id,
						label: nullableText(provider.label),
						backend_provider: nullableText(provider.backendProvider),
						aliases: splitList(provider.aliases),
						logo_slug: nullableText(provider.logoSlug),
						logo_letter: nullableText(provider.logoLetter),
						base_url_env: nullableText(provider.baseUrlEnv),
						base_url_default: nullableText(provider.baseUrlDefault),
						api_key_env: nullableText(provider.apiKeyEnv),
					};
					if (appEnv.useLocalRuntime && provider.apiKeyDefault.trim()) {
						requestProvider.api_key_default = provider.apiKeyDefault.trim();
					}
					return requestProvider;
				});
			const models: FocusAgentUpdateAdminModelConfigEntry[] =
				modelDraft.models.map((model) => {
					const id = model.id.trim();
					if (!id) {
						throw new Error(
							isChineseUi ? "模型 ID 不能为空。" : "Model ID is required.",
						);
					}
					return {
						id,
						label: nullableText(model.label),
						supports_thinking: model.supportsThinking,
						default_thinking_enabled: model.supportsThinking
							? model.defaultThinkingEnabled
							: false,
						request_kwargs: model.original.request_kwargs,
						thinking_enabled_request_kwargs:
							model.original.thinking_enabled_request_kwargs,
						thinking_disabled_request_kwargs:
							model.original.thinking_disabled_request_kwargs,
						thinking_disabled_model_name:
							model.original.thinking_disabled_model_name,
						reasoning_effort: nullableText(model.reasoningEffort),
						no_temperature: model.noTemperature,
						thinking_enable_extra_body_type:
							model.original.thinking_enable_extra_body_type,
						thinking_disable_extra_body_type:
							model.original.thinking_disable_extra_body_type,
						thinking_disable_switch_model:
							model.original.thinking_disable_switch_model,
					};
				});
			const request: FocusAgentUpdateAdminModelConfigRequest = {
				reason: nullableText(modelDraft.reason),
				default_model: nullableText(modelDraft.defaultModel),
				helper_model: nullableText(modelDraft.helperModel),
				model_choices: uniqueList(modelDraft.modelChoices),
				providers,
				models,
			};
			await modelMutation.mutateAsync(request);
		} catch (error) {
			setFormError(
				error instanceof Error
					? error.message
					: isChineseUi
						? "保存模型配置失败。"
						: "Failed to save model config.",
			);
		}
	}

	async function handleToolSubmit(event: FormEvent<HTMLFormElement>) {
		event.preventDefault();
		setFormError("");
		try {
			const tools: FocusAgentUpdateAdminToolConfigEntry[] = toolDraft.tools.map(
				(tool) => ({
					name: tool.name,
					enabled: tool.enabled,
					label: nullableText(tool.label),
					description: nullableText(tool.description),
					settings: tool.original.settings,
					metadata: tool.original.metadata,
				}),
			);
			const providers: FocusAgentUpdateAdminToolProviderConfig[] =
				toolDraft.providers.map((provider) => {
					const id = provider.id.trim();
					if (!id) {
						throw new Error(
							isChineseUi
								? "工具 Provider ID 不能为空。"
								: "Tool provider ID is required.",
						);
					}
					const order =
						provider.order.trim().length === 0
							? null
							: Number.parseInt(provider.order, 10);
					if (Number.isNaN(order)) {
						throw new Error(
							isChineseUi
								? `${provider.id} 的顺序必须是整数。`
								: `${provider.id} order must be an integer.`,
						);
					}
					return {
						id,
						enabled: provider.enabled,
						order,
						metadata: provider.metadata,
						overrides: splitList(provider.overrides),
					};
				});
			const request: FocusAgentUpdateAdminToolConfigRequest = {
				reason: nullableText(toolDraft.reason),
				tools,
				providers,
			};
			await toolMutation.mutateAsync(request);
		} catch (error) {
			setFormError(
				error instanceof Error
					? error.message
					: isChineseUi
						? "保存工具配置失败。"
						: "Failed to save tool config.",
			);
		}
	}

	async function handlePolicySubmit(event: FormEvent<HTMLFormElement>) {
		event.preventDefault();
		setFormError("");
		try {
			const values = Object.fromEntries(
				editablePolicyItems.map((item) => [
					item.key,
					coercePolicyValue(
						item,
						policyDraft.values[item.key] ?? "",
						isChineseUi,
					),
				]),
			);
			await policyMutation.mutateAsync({
				reason: nullableText(policyDraft.reason),
				values,
			});
		} catch (error) {
			setFormError(
				error instanceof Error
					? error.message
					: isChineseUi
						? "保存策略配置失败。"
						: "Failed to save policy config.",
			);
		}
	}

	async function updateSkillConfig(
		skill: FocusAgentAdminSkillConfigEntry,
		enabled: boolean,
	) {
		setFormError("");
		setPendingSkillId(skill.skill_id);
		try {
			await skillMutation.mutateAsync({
				reason: isChineseUi
					? "管理员在能力中心更新 Skill 状态"
					: "Admin updated skill state in capability center.",
				skills: [{ skill_id: skill.skill_id, enabled }],
			});
		} catch (error) {
			setFormError(
				error instanceof Error
					? error.message
					: isChineseUi
						? "保存 Skill 配置失败。"
						: "Failed to save skill config.",
			);
		} finally {
			setPendingSkillId(null);
		}
	}

	async function updateGlobalSkillConfig(enabled: boolean) {
		setFormError("");
		setPendingSkillId("__global__");
		try {
			await skillMutation.mutateAsync({
				enabled,
				reason: isChineseUi
					? "管理员在能力中心更新 Skill 系统开关"
					: "Admin updated skill system availability in capability center.",
			});
		} catch (error) {
			setFormError(
				error instanceof Error
					? error.message
					: isChineseUi
						? "保存 Skill 配置失败。"
						: "Failed to save skill config.",
			);
		} finally {
			setPendingSkillId(null);
		}
	}

	return (
		<AdminConsoleLayout
			active="config"
			allowDeviceLocalConfiguration={appEnv.useLocalRuntime}
			title={
				appEnv.useLocalRuntime
					? isChineseUi
						? "设备本地配置"
						: "Device-local configuration"
					: isChineseUi
						? "设置中心"
						: "Settings Center"
			}
			summary={
				appEnv.useLocalRuntime
					? isChineseUi
						? "仅配置此设备上的模型、工具、Skill 和运行策略；不管理账号、角色或审计。"
						: "Configure models, tools, skills, and runtime policies on this device only; accounts, roles, and audit are unavailable."
					: isChineseUi
						? "按连接、能力、Agent 行为和运行安全管理系统配置。"
						: "Manage system settings by connections, capabilities, agent behavior, and runtime safety."
			}
			toolbar={
				<button
					className="fa-observability-preset"
					type="button"
					onClick={() => {
						void configQuery.refetch();
					}}
				>
					{isChineseUi ? "重新加载" : "Reload"}
				</button>
			}
		>
			<section
				aria-label={isChineseUi ? "配置项选择" : "Config section picker"}
				className="fa-admin-config-switchboard"
			>
				<ConfigSectionPicker
					active={activeConfigSection}
					isChineseUi={isChineseUi}
					onChange={setActiveConfigSection}
					summary={summary}
				/>
				{configQuery.error ? (
					<AdminErrorMessage
						error={configQuery.error}
						fallback="Failed to load admin config."
					/>
				) : null}
				{formError ? (
					<div className="fa-inline-notice is-danger">{formError}</div>
				) : null}
			</section>

			<div className="fa-admin-config-detail">
				{activeConfigSection === "overview" ? (
					<AdminConfigOverviewPanel
						isChineseUi={isChineseUi}
						metrics={overviewMetrics}
						onSectionChange={setActiveConfigSection}
						requiresRestart={requiresRestart}
						sources={sources}
					/>
				) : null}
				{activeConfigSection === "connections" ? (
					<>
						<ConnectionsSummaryPanel
							configuredProviderCount={summary.configuredModelProviderCount}
							isChineseUi={isChineseUi}
							modelProviderCount={summary.modelProviderCount}
							toolProviderCount={summary.toolProviderCount}
						/>
						<ModelConfigPanel
							choiceOptions={modelChoiceOptions}
							disabled={disabled}
							draft={modelDraft}
							isChineseUi={isChineseUi}
							onAddProvider={() =>
								setModelDraft((current) => ({
									...current,
									providers: [...current.providers, emptyModelProviderDraft()],
								}))
							}
							onChange={setModelDraft}
							onChoiceChange={updateModelChoice}
							onEntryChange={updateModelEntry}
							onProviderChange={updateModelProvider}
							onProviderRemove={removeModelProvider}
							onReset={() => setModelDraft(buildModelDraft(config))}
							onSubmit={(event) => void handleModelSubmit(event)}
							pending={pendingSection === "models"}
							showLocalSecrets={appEnv.useLocalRuntime}
							source={config?.models.source}
						/>
					</>
				) : null}
				{activeConfigSection === "capabilities" ? (
					<>
						<SkillManagementPanel
							disabled={disabled}
							error={null}
							globalEnabled={Boolean(config?.skills.enabled)}
							isChineseUi={isChineseUi}
							items={skillItems}
							loading={configQuery.isLoading}
							onGlobalToggle={(enabled) =>
								void updateGlobalSkillConfig(enabled)
							}
							onSkillToggle={(skill, enabled) =>
								void updateSkillConfig(skill, enabled)
							}
							pendingSkillId={pendingSkillId}
						/>
						<ToolConfigPanel
							disabled={disabled}
							draft={toolDraft}
							isChineseUi={isChineseUi}
							onAddProvider={() =>
								setToolDraft((current) => ({
									...current,
									providers: [...current.providers, emptyToolProviderDraft()],
								}))
							}
							onChange={setToolDraft}
							onProviderChange={updateToolProvider}
							onProviderRemove={removeToolProvider}
							onReset={() => setToolDraft(buildToolDraft(config))}
							onSubmit={(event) => void handleToolSubmit(event)}
							onToolChange={updateToolEntry}
							pending={pendingSection === "tools"}
							source={config?.tools.source}
						/>
					</>
				) : null}
				{activeConfigSection === "agent" ? (
					<PolicyConfigPanel
						disabled={disabled}
						draft={policyDraft}
						eyebrow={isChineseUi ? "Agent" : "Agent"}
						help={
							isChineseUi
								? "集中维护路由、委派、记忆、上下文和多 Agent 行为策略。"
								: "Tune routing, delegation, memory, context, and multi-agent behavior policies."
						}
						isChineseUi={isChineseUi}
						items={agentPolicyItems}
						onChange={setPolicyDraft}
						onReset={() => setPolicyDraft(buildPolicyDraft(config))}
						onSubmit={(event) => void handlePolicySubmit(event)}
						onValueChange={updatePolicyValue}
						pending={pendingSection === "policies"}
						source={config?.policies.source}
						title={isChineseUi ? "Agent 行为策略" : "Agent Behavior Policies"}
					/>
				) : null}
				{activeConfigSection === "security" ? (
					<>
						<SecurityRuntimePanel
							isChineseUi={isChineseUi}
							policyItems={securityPolicyItems}
							runtimeItems={runtimeSystemItems}
							securityItems={securitySystemItems}
							source={config?.system.source}
						/>
						{securityPolicyItems.length ? (
							<PolicyConfigPanel
								disabled={disabled}
								draft={policyDraft}
								eyebrow={isChineseUi ? "Security" : "Security"}
								help={
									isChineseUi
										? "维护限流、审批与安全相关的可编辑策略。"
										: "Maintain editable rate-limit, approval, and safety policies."
								}
								isChineseUi={isChineseUi}
								items={securityPolicyItems}
								onChange={setPolicyDraft}
								onReset={() => setPolicyDraft(buildPolicyDraft(config))}
								onSubmit={(event) => void handlePolicySubmit(event)}
								onValueChange={updatePolicyValue}
								pending={pendingSection === "policies"}
								source={config?.policies.source}
								title={
									isChineseUi ? "安全运行策略" : "Security Runtime Policies"
								}
							/>
						) : null}
					</>
				) : null}
				{activeConfigSection === "advanced" ? (
					<>
						<AdvancedConfigPanel
							advancedPolicyCount={advancedPolicyItems.length}
							isChineseUi={isChineseUi}
							sources={sources}
						/>
						{advancedPolicyItems.length ? (
							<PolicyConfigPanel
								disabled={disabled}
								draft={policyDraft}
								eyebrow={isChineseUi ? "Advanced" : "Advanced"}
								help={
									isChineseUi
										? "这些配置保留为高级项，避免干扰常用设置流程。"
										: "These settings remain advanced so common workflows stay focused."
								}
								isChineseUi={isChineseUi}
								items={advancedPolicyItems}
								onChange={setPolicyDraft}
								onReset={() => setPolicyDraft(buildPolicyDraft(config))}
								onSubmit={(event) => void handlePolicySubmit(event)}
								onValueChange={updatePolicyValue}
								pending={pendingSection === "policies"}
								source={config?.policies.source}
								title={isChineseUi ? "高级策略" : "Advanced Policies"}
							/>
						) : null}
					</>
				) : null}
			</div>
		</AdminConsoleLayout>
	);
}
