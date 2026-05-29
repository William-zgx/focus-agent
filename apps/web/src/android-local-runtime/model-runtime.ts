import type {
	FocusAgentAdminConfig,
	FocusAgentModelsResponse,
	ThreadStateResponse,
} from "@focus-agent/web-sdk";
import {
	DEFAULT_MODEL_ID,
	DEFAULT_PROVIDER_BASE_URL,
	DEFAULT_PROVIDER_ID,
} from "./constants";
import { clone, normalizedUrl } from "./helpers";
import type { LocalFocusAgentRuntime } from "./local-focus-agent-runtime";
import { modelOption } from "./state";
import type {
	ChatCompletionMessage,
	LocalToolExecution,
	LocalWebFetchResult,
	LocalWebSearchResult,
	ResolvedLocalModelProvider,
} from "./types";

export function adminConfigResponse(
	ctx: LocalFocusAgentRuntime,
): FocusAgentAdminConfig {
	const config = clone(ctx.state.adminConfig);
	config.models.providers = config.models.providers.map((provider) => ({
		...provider,
		api_key_configured: Boolean(ctx.modelSecrets[provider.id]?.apiKey?.trim()),
		base_url_configured: Boolean(
			normalizedUrl(provider.base_url_default) || provider.base_url_env,
		),
	}));
	return config;
}

export function providerMatchesModelPrefix(
	_ctx: LocalFocusAgentRuntime,
	provider: FocusAgentAdminConfig["models"]["providers"][number],
	modelProviderPrefix: string,
): boolean {
	const normalizedPrefix = modelProviderPrefix.trim().toLowerCase();
	if (!normalizedPrefix) return false;
	return (
		provider.id.toLowerCase() === normalizedPrefix ||
		provider.aliases.some(
			(alias) => alias.trim().toLowerCase() === normalizedPrefix,
		)
	);
}

export function providerConfigForModel(
	ctx: LocalFocusAgentRuntime,
	selectedModel: string,
): {
	model: string;
	provider: FocusAgentAdminConfig["models"]["providers"][number] | null;
} | null {
	const model = selectedModel.trim() || DEFAULT_MODEL_ID;
	const providerSeparatorIndex = model.indexOf(":");
	if (providerSeparatorIndex > 0 && providerSeparatorIndex < model.length - 1) {
		const providerPrefix = model.slice(0, providerSeparatorIndex);
		const modelName = model.slice(providerSeparatorIndex + 1);
		const provider =
			ctx.state.adminConfig.models.providers.find((item) =>
				ctx.providerMatchesModelPrefix(item, providerPrefix),
			) ?? null;
		return { model: modelName, provider };
	}
	if (providerSeparatorIndex > 0) return null;
	const [provider] = ctx.state.adminConfig.models.providers;
	return provider ? { model, provider } : null;
}

export function modelProvider(
	ctx: LocalFocusAgentRuntime,
	selectedModel: string,
): ResolvedLocalModelProvider | null {
	const resolved = ctx.providerConfigForModel(selectedModel);
	if (!resolved?.provider) return null;
	const provider = resolved.provider;
	const apiKey = ctx.modelSecrets[provider.id]?.apiKey?.trim() ?? "";
	if (!apiKey) return null;
	return {
		model: resolved.model,
		provider: {
			id: provider.id,
			label: provider.label ?? provider.id,
			baseUrl:
				normalizedUrl(provider.base_url_default) || DEFAULT_PROVIDER_BASE_URL,
			apiKey,
		},
	};
}

export function modelProviderLabel(
	ctx: LocalFocusAgentRuntime,
	selectedModel: string,
): string {
	const resolved = ctx.providerConfigForModel(selectedModel);
	const [fallbackProvider] = ctx.state.adminConfig.models.providers;
	const provider = resolved?.provider ?? fallbackProvider;
	return provider?.label ?? provider?.id ?? "DeepSeek";
}

export function chatMessages(
	ctx: LocalFocusAgentRuntime,
	thread: ThreadStateResponse,
	webSearchResult?: LocalWebSearchResult | null,
	webFetchResult?: LocalWebFetchResult | null,
	localToolExecutions: LocalToolExecution[] = [],
): ChatCompletionMessage[] {
	const history = ctx.threadMessagesForProvider(thread).slice(-24);
	const toolContext: ChatCompletionMessage[] = [];
	if (webSearchResult) {
		toolContext.push({
			role: "system",
			content: [
				"The Android local runtime already executed web_search for this turn.",
				"Use these search results as current external evidence and cite URLs when useful.",
				JSON.stringify(webSearchResult),
			].join("\n"),
		});
	}
	if (webFetchResult) {
		toolContext.push({
			role: "system",
			content: [
				"The Android local runtime already executed web_fetch for this turn.",
				"Use the fetched page content as external evidence and cite the URL when useful.",
				JSON.stringify(webFetchResult),
			].join("\n"),
		});
	}
	for (const execution of localToolExecutions) {
		toolContext.push({
			role: "system",
			content: [
				`The Android local runtime already executed ${execution.name} for this turn.`,
				"Use this app-local tool output when answering.",
				JSON.stringify(execution.output),
			].join("\n"),
		});
	}
	return [
		{
			role: "system",
			content:
				"You are Focus Agent running inside an Android app-local runtime. Keep answers concise, useful, and do not claim access to a Focus Agent backend.",
		},
		...history,
		...toolContext,
	];
}

export function threadMessagesForProvider(
	_ctx: LocalFocusAgentRuntime,
	thread: ThreadStateResponse,
): ChatCompletionMessage[] {
	const messages: ChatCompletionMessage[] = [];
	for (const message of thread.messages) {
		const content = String(message.content ?? "").trim();
		if (!content) continue;
		const type = String(message.type ?? "");
		if (type === "human") {
			messages.push({ role: "user", content });
		} else if (type === "ai") {
			messages.push({ role: "assistant", content });
		}
	}
	return messages;
}

export function modelsResponse(
	ctx: LocalFocusAgentRuntime,
): FocusAgentModelsResponse {
	const defaultModel =
		ctx.state.adminConfig.models.default_model || DEFAULT_MODEL_ID;
	const configuredModels = ctx.state.adminConfig.models.models;
	const providers = ctx.adminConfigResponse().models.providers;
	const fallbackProvider = providers[0];
	const models =
		configuredModels.length > 0
			? configuredModels.map((item) => {
					const provider =
						ctx.providerConfigForModel(item.id)?.provider ?? fallbackProvider;
					return {
						id: item.id,
						provider: provider?.id ?? DEFAULT_PROVIDER_ID,
						provider_label: provider?.label ?? "DeepSeek",
						provider_logo_slug: provider?.logo_slug ?? null,
						provider_logo_letter: provider?.logo_letter ?? "O",
						name: item.label ?? item.id,
						label: item.label ?? item.id,
						is_default: item.id === defaultModel,
						supports_thinking: Boolean(item.supports_thinking),
						default_thinking_enabled: Boolean(item.default_thinking_enabled),
					};
				})
			: [modelOption()];
	return { default_model: defaultModel, models };
}
