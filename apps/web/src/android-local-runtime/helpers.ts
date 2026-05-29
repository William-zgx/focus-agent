import { DEFAULT_PROVIDER_BASE_URL, JSON_HEADERS } from "./constants";
import type { ContextUsageResponse, JsonRecord } from "./types";

export function nowIso(): string {
	return new Date().toISOString();
}

export function id(prefix: string, value: number): string {
	return `${prefix}-${String(value).padStart(4, "0")}`;
}

export function clone<T>(value: T): T {
	return JSON.parse(JSON.stringify(value)) as T;
}

export function isRecord(value: unknown): value is JsonRecord {
	return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function parseJsonBody(init?: RequestInit): unknown {
	const body = init?.body;
	if (!body || typeof body !== "string") return {};
	try {
		return JSON.parse(body) as unknown;
	} catch {
		return {};
	}
}

export function stringValue(value: unknown): string {
	return typeof value === "string" ? value : "";
}

export function nullableString(value: unknown): string | null {
	return typeof value === "string" && value.trim() ? value.trim() : null;
}

export function stringArray(value: unknown): string[] {
	return Array.isArray(value)
		? value.filter((item): item is string => typeof item === "string")
		: [];
}

export function searchParamNumber(
	searchParams: URLSearchParams,
	key: string,
	fallback: number,
): number {
	const value = Number(searchParams.get(key) ?? fallback);
	return Number.isFinite(value) && value >= 0 ? value : fallback;
}

export function normalizedUrl(value: string | null | undefined): string {
	const trimmedValue = value?.trim();
	if (!trimmedValue) return "";
	try {
		const url = new URL(trimmedValue);
		url.pathname = url.pathname.replace(/\/+$/, "");
		url.search = "";
		url.hash = "";
		return url.toString().replace(/\/$/, "");
	} catch {
		return "";
	}
}

export function chatCompletionsUrl(baseUrl: string): string {
	const normalized = normalizedUrl(baseUrl) || DEFAULT_PROVIDER_BASE_URL;
	return normalized.endsWith("/chat/completions")
		? normalized
		: `${normalized}/chat/completions`;
}

export function routeSegments(pathname: string): string[] {
	return pathname
		.split("/")
		.filter(Boolean)
		.map((part) => decodeURIComponent(part));
}

export function jsonResponse(data: unknown, init: ResponseInit = {}): Response {
	return new Response(JSON.stringify(data), {
		...init,
		headers: { ...JSON_HEADERS, ...init.headers },
	});
}

export function emptyResponse(init: ResponseInit = {}): Response {
	return new Response(null, init);
}

export function errorResponse(status: number, message: string): Response {
	return jsonResponse(
		{
			detail: {
				code: status,
				message,
				stable_code: status,
			},
		},
		{ status },
	);
}

export function contextUsage(
	messages: Array<Record<string, unknown>>,
): ContextUsageResponse {
	const promptChars = messages.reduce(
		(total, message) => total + String(message.content ?? "").length,
		0,
	);
	const usedTokens = Math.max(0, Math.ceil(promptChars / 4));
	const tokenLimit = 32000;
	const usedRatio = usedTokens / tokenLimit;
	return {
		used_tokens: usedTokens,
		token_limit: tokenLimit,
		remaining_tokens: Math.max(0, tokenLimit - usedTokens),
		used_ratio: usedRatio,
		status:
			usedRatio >= 1
				? "over"
				: usedRatio >= 0.85
					? "hot"
					: usedRatio >= 0.65
						? "warm"
						: "ok",
		prompt_chars: promptChars,
		prompt_budget_chars: tokenLimit * 4,
		tokenizer_mode: "local-estimate",
	};
}
