import {
	Capacitor,
	CapacitorHttp,
	type HttpHeaders,
	registerPlugin,
} from "@capacitor/core";

import { SECRET_STORAGE_FALLBACK_KEY, SECRET_STORAGE_KEY } from "./constants";
import { chatCompletionsUrl, isRecord } from "./helpers";
import type {
	ChatCompletionMessage,
	FocusAgentSecureStoragePlugin,
	LocalModelProvider,
} from "./types";

const focusAgentSecureStorage = registerPlugin<FocusAgentSecureStoragePlugin>(
	"FocusAgentSecureStorage",
);

export function providerErrorMessage(
	error: unknown,
	isChinese: boolean,
): string {
	const detail = error instanceof Error ? error.message : String(error);
	return isChinese
		? `模型供应商请求失败：${detail}`
		: `The model provider request failed: ${detail}`;
}

export function missingProviderKeyReply(
	providerLabel: string,
	isChinese: boolean,
): string {
	return isChinese
		? [
				"Android 本地运行时已启动，但还没有配置模型 API Key。",
				"",
				`请在管理栏 -> 配置中心 -> 模型 Provider 中为 ${providerLabel} 填入 API Key 后保存。`,
				"",
				"当前 App 不会连接 Focus Agent 后端；配置会保存在本机 App 数据里。",
			].join("\n")
		: [
				"The Android local runtime is active, but no model API key is configured yet.",
				"",
				`Open Admin -> Config Center -> Model providers and save an API key for ${providerLabel}.`,
				"",
				"This app does not connect to a Focus Agent backend; config is stored in local app data.",
			].join("\n");
}

export function contentPartToText(part: unknown): string {
	if (typeof part === "string") return part;
	if (!isRecord(part)) return "";
	if (typeof part.text === "string") return part.text;
	if (typeof part.content === "string") return part.content;
	return "";
}

export function extractAssistantContent(data: unknown): string {
	if (!isRecord(data)) return "";
	const choices = Array.isArray(data.choices) ? data.choices : [];
	const [firstChoice] = choices;
	if (!isRecord(firstChoice) || !isRecord(firstChoice.message)) return "";
	const content = firstChoice.message.content;
	if (typeof content === "string") return content;
	if (Array.isArray(content)) {
		return content.map(contentPartToText).join("").trim();
	}
	return "";
}

export function abortIfRequested(signal?: AbortSignal): void {
	if (signal?.aborted) {
		throw signal.reason ?? new DOMException("Aborted", "AbortError");
	}
}

export function parseModelSecrets(
	value: string | null | undefined,
): Record<string, { apiKey?: string }> {
	if (!value?.trim()) return {};
	try {
		const parsed = JSON.parse(value) as unknown;
		if (!isRecord(parsed)) return {};
		const secrets: Record<string, { apiKey?: string }> = {};
		for (const [providerId, secret] of Object.entries(parsed)) {
			if (!isRecord(secret) || typeof secret.apiKey !== "string") continue;
			secrets[providerId] = { apiKey: secret.apiKey };
		}
		return secrets;
	} catch {
		return {};
	}
}

export async function readSecureModelSecrets(): Promise<
	Record<string, { apiKey?: string }>
> {
	if (
		Capacitor.isNativePlatform() &&
		Capacitor.isPluginAvailable("FocusAgentSecureStorage")
	) {
		const result = await focusAgentSecureStorage.get({
			key: SECRET_STORAGE_KEY,
		});
		return parseModelSecrets(result.value);
	}
	if (Capacitor.isNativePlatform()) return {};
	try {
		return parseModelSecrets(
			window.localStorage.getItem(SECRET_STORAGE_FALLBACK_KEY),
		);
	} catch {
		return {};
	}
}

export async function writeSecureModelSecrets(
	secrets: Record<string, { apiKey?: string }>,
): Promise<void> {
	const serialized = JSON.stringify(secrets);
	if (
		Capacitor.isNativePlatform() &&
		Capacitor.isPluginAvailable("FocusAgentSecureStorage")
	) {
		await focusAgentSecureStorage.set({
			key: SECRET_STORAGE_KEY,
			value: serialized,
		});
		return;
	}
	if (Capacitor.isNativePlatform()) {
		throw new Error("Focus Agent secure storage plugin is unavailable.");
	}
	try {
		window.localStorage.setItem(SECRET_STORAGE_FALLBACK_KEY, serialized);
	} catch (error) {
		console.warn(
			"Failed to persist Android local runtime model secrets",
			error,
		);
	}
}

export async function postOpenAiCompatibleChatCompletion({
	messages,
	model,
	provider,
	signal,
}: {
	messages: ChatCompletionMessage[];
	model: string;
	provider: LocalModelProvider;
	signal?: AbortSignal;
}): Promise<string> {
	abortIfRequested(signal);
	const url = chatCompletionsUrl(provider.baseUrl);
	const headers: HttpHeaders = {
		Authorization: `Bearer ${provider.apiKey}`,
		"Content-Type": "application/json",
	};
	const data = {
		model,
		messages,
		stream: false,
	};
	if (
		Capacitor.isNativePlatform() &&
		Capacitor.isPluginAvailable("CapacitorHttp")
	) {
		const response = await CapacitorHttp.post({
			url,
			headers,
			data,
			responseType: "json",
			connectTimeout: 30000,
			readTimeout: 120000,
		});
		abortIfRequested(signal);
		if (response.status < 200 || response.status >= 300) {
			throw new Error(`HTTP ${response.status}`);
		}
		const content = extractAssistantContent(response.data);
		if (!content) throw new Error("Provider returned an empty response.");
		return content;
	}

	const response = await fetch(url, {
		body: JSON.stringify(data),
		headers,
		method: "POST",
		signal,
	});
	abortIfRequested(signal);
	const responseBody = (await response.json().catch(() => ({}))) as unknown;
	if (!response.ok) {
		const detail =
			isRecord(responseBody) && typeof responseBody.error === "object"
				? JSON.stringify(responseBody.error)
				: response.statusText;
		throw new Error(`HTTP ${response.status}: ${detail}`);
	}
	const content = extractAssistantContent(responseBody);
	if (!content) throw new Error("Provider returned an empty response.");
	return content;
}
