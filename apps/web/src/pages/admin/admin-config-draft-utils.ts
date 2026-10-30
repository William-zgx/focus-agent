import type {
	FocusAgentAdminConfig,
	FocusAgentAdminConfigProvider,
	FocusAgentAdminConfigValue,
	FocusAgentAdminModelConfigEntry,
	FocusAgentAdminToolConfigEntry,
	FocusAgentAdminToolProviderConfig,
	FocusAgentModelProtocol,
	FocusAgentUpdateAdminModelConfigEntry,
	FocusAgentUpdateAdminModelConfigRequest,
	FocusAgentUpdateAdminModelProviderConfig,
	FocusAgentUpdateAdminToolConfigEntry,
	FocusAgentUpdateAdminToolConfigRequest,
	FocusAgentUpdateAdminToolProviderConfig,
} from "@focus-agent/web-sdk";

export type EditableConfigSection = "models" | "policies" | "tools";
export type ConfigSection =
	| "advanced"
	| "agent"
	| "capabilities"
	| "connections"
	| "overview"
	| "security";
export type PolicyDraftValue = boolean | string;

export type ModelProviderDraft = {
	id: string;
	label: string;
	backendProvider: string;
	aliases: string;
	logoSlug: string;
	logoLetter: string;
	baseUrlEnv: string;
	baseUrlDefault: string;
	baseUrlConfigured: boolean;
	apiKeyEnv: string;
	apiKeyDefault: string;
	apiKeyConfigured: boolean;
};

export type ModelEntryDraft = {
	id: string;
	label: string;
	protocol: FocusAgentModelProtocol;
	supportsThinking: boolean;
	defaultThinkingEnabled: boolean;
	reasoningEffort: string;
	noTemperature: boolean;
	original: FocusAgentAdminModelConfigEntry;
};

export type ModelDraft = {
	reason: string;
	defaultModel: string;
	helperModel: string;
	modelChoices: string[];
	providers: ModelProviderDraft[];
	models: ModelEntryDraft[];
};

export type ToolEntryDraft = {
	name: string;
	enabled: boolean;
	label: string;
	description: string;
	original: FocusAgentAdminToolConfigEntry;
};

export type ToolProviderDraft = {
	id: string;
	enabled: boolean;
	order: string;
	overrides: string;
	metadata: Record<string, unknown>;
};

export type ToolDraft = {
	reason: string;
	tools: ToolEntryDraft[];
	providers: ToolProviderDraft[];
};

export type PolicyDraft = {
	reason: string;
	values: Record<string, PolicyDraftValue>;
};

export const EMPTY_SELECT_VALUE = "__empty__";

function textValue(value: string | null | undefined) {
	return value ?? "";
}

export function nullableText(value: string) {
	const trimmed = value.trim();
	return trimmed ? trimmed : null;
}

export function splitList(value: string) {
	return value
		.split(/[\n,]/)
		.map((item) => item.trim())
		.filter(Boolean);
}

export function uniqueList(values: Array<string | null | undefined>) {
	return Array.from(
		new Set(
			values
				.map((value) => value?.trim() ?? "")
				.filter((value) => value.length > 0),
		),
	);
}

export function unknownToText(value: unknown) {
	if (value === null || value === undefined) return "";
	if (typeof value === "string") return value;
	if (typeof value === "number" || typeof value === "boolean") {
		return String(value);
	}
	return JSON.stringify(value);
}

function unknownToBoolean(value: unknown) {
	if (typeof value === "boolean") return value;
	if (typeof value === "string") return value.toLowerCase() === "true";
	return Boolean(value);
}

function providerToDraft(
	provider: FocusAgentAdminConfigProvider,
): ModelProviderDraft {
	return {
		id: provider.id,
		label: textValue(provider.label),
		backendProvider: textValue(provider.backend_provider),
		aliases: provider.aliases.join(", "),
		logoSlug: textValue(provider.logo_slug),
		logoLetter: textValue(provider.logo_letter),
		baseUrlEnv: textValue(provider.base_url_env),
		baseUrlDefault: textValue(provider.base_url_default),
		baseUrlConfigured: provider.base_url_configured,
		apiKeyEnv: textValue(provider.api_key_env),
		apiKeyDefault: "",
		apiKeyConfigured: provider.api_key_configured,
	};
}

function modelToDraft(model: FocusAgentAdminModelConfigEntry): ModelEntryDraft {
	return {
		id: model.id,
		label: textValue(model.label),
		protocol: model.protocol === "system_one" ? "system_one" : "chat",
		supportsThinking: Boolean(model.supports_thinking),
		defaultThinkingEnabled: Boolean(model.default_thinking_enabled),
		reasoningEffort: textValue(model.reasoning_effort),
		noTemperature: Boolean(model.no_temperature),
		original: model,
	};
}

export function isChatModel(model: Pick<ModelEntryDraft, "protocol">) {
	return model.protocol !== "system_one";
}

export function updateModelEntryDraft(
	draft: ModelDraft,
	index: number,
	patch: Partial<ModelEntryDraft>,
): ModelDraft {
	const modelId = draft.models[index]?.id;
	const switchingToDecisionModel = patch.protocol === "system_one";
	return {
		...draft,
		models: draft.models.map((model, modelIndex) =>
			modelIndex === index ? { ...model, ...patch } : model,
		),
		defaultModel:
			switchingToDecisionModel && modelId === draft.defaultModel
				? ""
				: draft.defaultModel,
		helperModel:
			switchingToDecisionModel && modelId === draft.helperModel
				? ""
				: draft.helperModel,
		modelChoices: switchingToDecisionModel
			? draft.modelChoices.filter((modelChoice) => modelChoice !== modelId)
			: draft.modelChoices,
	};
}

export function buildModelDraft(
	config: FocusAgentAdminConfig | undefined,
): ModelDraft {
	const modelConfig = config?.models;
	const models = (modelConfig?.models ?? []).map(modelToDraft);
	const isChatModelId = (modelId: string | null | undefined) => {
		if (!modelId) return true;
		const model = models.find((item) => item.id === modelId);
		return !model || isChatModel(model);
	};
	return {
		reason: "",
		defaultModel: isChatModelId(modelConfig?.default_model)
			? (modelConfig?.default_model ?? "")
			: "",
		helperModel: isChatModelId(modelConfig?.helper_model)
			? (modelConfig?.helper_model ?? "")
			: "",
		modelChoices: (modelConfig?.model_choices ?? []).filter(isChatModelId),
		providers: (modelConfig?.providers ?? []).map(providerToDraft),
		models,
	};
}

export function modelDraftToRequest(
	draft: ModelDraft,
	isChineseUi: boolean,
): FocusAgentUpdateAdminModelConfigRequest {
	const providers: FocusAgentUpdateAdminModelProviderConfig[] =
		draft.providers.map((provider) => {
			const id = provider.id.trim();
			if (!id) {
				throw new Error(
					isChineseUi ? "Provider ID 不能为空。" : "Provider ID is required.",
				);
			}
			return {
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
		});
	const models: FocusAgentUpdateAdminModelConfigEntry[] = draft.models.map(
		(model) => {
			const id = model.id.trim();
			if (!id) {
				throw new Error(
					isChineseUi ? "模型 ID 不能为空。" : "Model ID is required.",
				);
			}
			return {
				id,
				label: nullableText(model.label),
				protocol: model.protocol,
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
		},
	);
	return {
		reason: nullableText(draft.reason),
		default_model: nullableText(draft.defaultModel),
		helper_model: nullableText(draft.helperModel),
		model_choices: uniqueList(draft.modelChoices),
		providers,
		models,
	};
}

function toolToDraft(tool: FocusAgentAdminToolConfigEntry): ToolEntryDraft {
	return {
		name: tool.name,
		enabled: tool.enabled,
		label: tool.label,
		description: tool.description,
		original: tool,
	};
}

function toolProviderToDraft(
	provider: FocusAgentAdminToolProviderConfig,
): ToolProviderDraft {
	return {
		id: provider.id,
		enabled: provider.enabled,
		order:
			provider.order === null || provider.order === undefined
				? ""
				: String(provider.order),
		overrides: provider.overrides.join(", "),
		metadata: provider.metadata,
	};
}

export function buildToolDraft(
	config: FocusAgentAdminConfig | undefined,
): ToolDraft {
	const toolConfig = config?.tools;
	return {
		reason: "",
		tools: (toolConfig?.tools ?? []).map(toolToDraft),
		providers: (toolConfig?.providers ?? []).map(toolProviderToDraft),
	};
}

export function toolDraftToRequest(
	draft: ToolDraft,
	isChineseUi: boolean,
): FocusAgentUpdateAdminToolConfigRequest {
	const tools: FocusAgentUpdateAdminToolConfigEntry[] = draft.tools.map(
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
		draft.providers.map((provider) => {
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
	return {
		reason: nullableText(draft.reason),
		tools,
		providers,
	};
}

export function policyDraftValue(
	item: FocusAgentAdminConfigValue,
): PolicyDraftValue {
	if (item.value_type === "boolean") return unknownToBoolean(item.value);
	return unknownToText(item.value);
}

export function buildPolicyDraft(
	config: FocusAgentAdminConfig | undefined,
): PolicyDraft {
	return {
		reason: "",
		values: Object.fromEntries(
			(config?.policies.items ?? [])
				.filter((item) => item.editable)
				.map((item) => [item.key, policyDraftValue(item)]),
		),
	};
}

export function emptyModelProviderDraft(): ModelProviderDraft {
	return {
		id: "",
		label: "",
		backendProvider: "",
		aliases: "",
		logoSlug: "",
		logoLetter: "",
		baseUrlEnv: "",
		baseUrlDefault: "",
		baseUrlConfigured: false,
		apiKeyEnv: "",
		apiKeyDefault: "",
		apiKeyConfigured: false,
	};
}

export function emptyToolProviderDraft(): ToolProviderDraft {
	return {
		id: "",
		enabled: true,
		order: "",
		overrides: "",
		metadata: {},
	};
}

export function coercePolicyValue(
	item: FocusAgentAdminConfigValue,
	value: PolicyDraftValue,
	isChineseUi: boolean,
) {
	if (item.value_type === "boolean") return Boolean(value);
	const text = String(value ?? "").trim();
	if (item.value_type === "integer") {
		const parsed = Number.parseInt(text, 10);
		if (Number.isNaN(parsed)) {
			throw new Error(
				isChineseUi
					? `${item.label} 必须是整数。`
					: `${item.label} must be an integer.`,
			);
		}
		return parsed;
	}
	if (item.value_type === "float") {
		const parsed = Number.parseFloat(text);
		if (Number.isNaN(parsed)) {
			throw new Error(
				isChineseUi
					? `${item.label} 必须是数字。`
					: `${item.label} must be a number.`,
			);
		}
		return parsed;
	}
	return text;
}
