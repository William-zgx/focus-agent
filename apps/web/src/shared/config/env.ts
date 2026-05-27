export const API_BASE_URL_STORAGE_KEY = "focus-agent-api-base-url";
export const LOCAL_RUNTIME_API_BASE_URL = "http://focus-agent.local";

const target = import.meta.env.VITE_FOCUS_AGENT_TARGET || "web";
const isAndroidTarget = target === "android";
const useLocalRuntime = isAndroidTarget;
const buildApiBaseUrl =
	import.meta.env.VITE_FOCUS_AGENT_API_BASE_URL?.trim() || "";

function normalizePathBase(value: string | undefined, fallback: string) {
	const rawValue = value?.trim() || fallback;
	if (rawValue === "/" || rawValue === "") return "/";
	const withLeadingSlash = rawValue.startsWith("/") ? rawValue : `/${rawValue}`;
	return withLeadingSlash.replace(/\/+$/, "") || "/";
}

function normalizeAssetBase(value: string | undefined, fallback: string) {
	const rawValue = value?.trim() || fallback;
	if (rawValue === "/" || rawValue === "") return "/";
	return rawValue.endsWith("/") ? rawValue : `${rawValue}/`;
}

function envFlag(value: string | undefined, fallback: boolean) {
	if (value === undefined || value === "") return fallback;
	const normalizedValue = value.trim().toLowerCase();
	if (["0", "false", "no", "off"].includes(normalizedValue)) return false;
	if (["1", "true", "yes", "on"].includes(normalizedValue)) return true;
	return fallback;
}

export function normalizeApiBaseUrl(value: string | null | undefined) {
	const trimmedValue = value?.trim();
	if (!trimmedValue) return "";
	try {
		const url = new URL(trimmedValue);
		if (url.protocol !== "http:" && url.protocol !== "https:") return "";
		url.pathname = url.pathname.replace(/\/+$/, "");
		url.search = "";
		url.hash = "";
		return url.toString().replace(/\/$/, "");
	} catch {
		return "";
	}
}

export function readStoredApiBaseUrl() {
	if (typeof window === "undefined") return "";
	try {
		return normalizeApiBaseUrl(
			window.localStorage.getItem(API_BASE_URL_STORAGE_KEY),
		);
	} catch {
		return "";
	}
}

export function persistApiBaseUrl(value: string) {
	if (typeof window === "undefined") return;
	try {
		if (value) {
			window.localStorage.setItem(API_BASE_URL_STORAGE_KEY, value);
		} else {
			window.localStorage.removeItem(API_BASE_URL_STORAGE_KEY);
		}
	} catch (error) {
		console.warn("Failed to persist Focus Agent API base URL", error);
	}
}

function resolveInitialApiBaseUrl() {
	if (useLocalRuntime) {
		return LOCAL_RUNTIME_API_BASE_URL;
	}
	return (
		normalizeApiBaseUrl(buildApiBaseUrl) ||
		readStoredApiBaseUrl() ||
		window.location.origin
	);
}

export const appEnv = {
	apiBaseUrl: resolveInitialApiBaseUrl(),
	apiBaseUrlRequired:
		isAndroidTarget &&
		!useLocalRuntime &&
		!normalizeApiBaseUrl(buildApiBaseUrl),
	assetBasePath: normalizeAssetBase(
		import.meta.env.VITE_FOCUS_AGENT_APP_BASE,
		isAndroidTarget ? "/" : "/app/",
	),
	demoUserId: import.meta.env.VITE_FOCUS_AGENT_DEMO_USER_ID || "researcher-1",
	demoTenantId:
		import.meta.env.VITE_FOCUS_AGENT_DEMO_TENANT_ID || "demo-tenant",
	features: {
		agentTeam: envFlag(
			import.meta.env.VITE_FOCUS_AGENT_ENABLE_AGENT_WORKBENCH,
			!isAndroidTarget,
		),
		agentGovernance: envFlag(
			import.meta.env.VITE_FOCUS_AGENT_ENABLE_AGENT_GOVERNANCE,
			true,
		),
		agentMemory: envFlag(
			import.meta.env.VITE_FOCUS_AGENT_ENABLE_AGENT_MEMORY,
			true,
		),
		observability: envFlag(
			import.meta.env.VITE_FOCUS_AGENT_ENABLE_OBSERVABILITY,
			true,
		),
		productivity: envFlag(
			import.meta.env.VITE_FOCUS_AGENT_ENABLE_PRODUCTIVITY,
			!isAndroidTarget,
		),
	},
	isAndroidTarget,
	useLocalRuntime,
	routerBasePath: normalizePathBase(
		import.meta.env.VITE_FOCUS_AGENT_ROUTER_BASE,
		isAndroidTarget ? "/" : "/app",
	),
	target,
};
