import type {
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
	useAdminConfig,
	useUpdateAdminModelConfig,
	useUpdateAdminPolicyConfig,
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
	PolicyConfigPanel,
	SystemConfigPanel,
	ToolConfigPanel,
} from "./admin-config-tool-policy-panels";

export function AdminConfigPage() {
	const { isChineseUi } = useShellUi();
	const configQuery = useAdminConfig();
	const modelMutation = useUpdateAdminModelConfig();
	const toolMutation = useUpdateAdminToolConfig();
	const policyMutation = useUpdateAdminPolicyConfig();
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
		useState<ConfigSection>("models");
	const [formError, setFormError] = useState("");
	const config = configQuery.data;
	const editablePolicyItems = useMemo(
		() => (config?.policies.items ?? []).filter((item) => item.editable),
		[config?.policies.items],
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
			modelCount: config?.models?.models?.length ?? 0,
			policyCount: config?.policies?.items?.length ?? 0,
			systemCount: config?.system?.items?.length ?? 0,
			toolCount: config?.tools?.tools?.length ?? 0,
			toolProviderCount: config?.tools?.providers?.length ?? 0,
		}),
		[config],
	);

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
	const disabled = Boolean(pendingSection);

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

	return (
		<AdminConsoleLayout
			active="config"
			title={isChineseUi ? "配置中心" : "Config Center"}
			summary={
				isChineseUi
					? "集中查看和更新模型、工具与策略配置。"
					: "Review and update model, tool, and policy configuration."
			}
			toolbar={
				<button
					className="fa-observability-preset"
					type="button"
					onClick={() => void configQuery.refetch()}
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
				{activeConfigSection === "models" ? (
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
				) : null}
				{activeConfigSection === "tools" ? (
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
				) : null}
				{activeConfigSection === "policies" ? (
					<PolicyConfigPanel
						disabled={disabled}
						draft={policyDraft}
						isChineseUi={isChineseUi}
						items={editablePolicyItems}
						onChange={setPolicyDraft}
						onReset={() => setPolicyDraft(buildPolicyDraft(config))}
						onSubmit={(event) => void handlePolicySubmit(event)}
						onValueChange={updatePolicyValue}
						pending={pendingSection === "policies"}
						source={config?.policies.source}
					/>
				) : null}
				{activeConfigSection === "system" ? (
					<SystemConfigPanel
						isChineseUi={isChineseUi}
						items={config?.system.items ?? []}
						source={config?.system.source}
					/>
				) : null}
			</div>
		</AdminConsoleLayout>
	);
}
