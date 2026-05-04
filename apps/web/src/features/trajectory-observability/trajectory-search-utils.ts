import { FocusAgentRequestError } from "@focus-agent/web-sdk";

import type { SortMode, StatusMode } from "./trajectory-types";

export function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null;
}

export function getSearchParams(search?: unknown) {
	if (search instanceof URLSearchParams) {
		return new URLSearchParams(search);
	}
	if (typeof search === "string") {
		return new URLSearchParams(search);
	}
	if (isRecord(search)) {
		const params = new URLSearchParams();
		Object.entries(search).forEach(([key, rawValue]) => {
			if (rawValue === undefined || rawValue === null) return;
			if (Array.isArray(rawValue)) {
				rawValue.forEach((item) => {
					if (item === undefined || item === null) return;
					params.append(key, String(item));
				});
				return;
			}
			params.set(key, String(rawValue));
		});
		return params;
	}
	if (typeof window === "undefined") {
		return new URLSearchParams();
	}
	return new URLSearchParams(window.location.search);
}

export function readSearchParam(key: string, search?: unknown) {
	return getSearchParams(search).get(key) ?? "";
}

export function readInitialSearchParam(key: string, search?: unknown) {
	return readSearchParam(key, search);
}

export function readSearchFlag(
	key: string,
	fallback = false,
	search?: unknown,
) {
	const value = readSearchParam(key, search);
	if (!value) return fallback;
	return value === "1" || value === "true";
}

export function readSearchStatus(search?: unknown): StatusMode {
	const value = readSearchParam("status", search);
	if (value === "all" || value === "failed" || value === "succeeded") {
		return value;
	}
	return "all";
}

export function readSearchSort(search?: unknown): SortMode {
	const value = readSearchParam("sort", search);
	if (value === "newest" || value === "latency" || value === "tool_calls") {
		return value;
	}
	return "newest";
}

export function readSearchState(search?: unknown) {
	return {
		statusFilter: readSearchStatus(search),
		toolFilter: readSearchParam("tool", search),
		threadFilter: readSearchParam("thread", search),
		requestFilter: readSearchParam("request", search),
		traceFilter: readSearchParam("trace", search),
		modelFilter: readSearchParam("model", search),
		minLatency: readSearchParam("minLatency", search),
		fallbackOnly: readSearchFlag("fallbackOnly", false, search),
		hasErrorOnly: readSearchFlag("hasErrorOnly", false, search),
		sortMode: readSearchSort(search),
		selectedTurnId: readSearchParam("turn", search),
	};
}

export function shouldExpandFiltersFromSearch(search?: unknown) {
	const state = readSearchState(search);
	return (
		Boolean(state.toolFilter) ||
		Boolean(state.threadFilter) ||
		Boolean(state.requestFilter) ||
		Boolean(state.traceFilter) ||
		Boolean(state.modelFilter) ||
		Boolean(state.minLatency) ||
		state.fallbackOnly ||
		state.hasErrorOnly ||
		state.statusFilter !== "all" ||
		state.sortMode !== "newest"
	);
}

export function parseNonNegativeNumber(value: string) {
	const text = value.trim();
	if (!text) return undefined;
	const parsed = Number(text);
	if (!Number.isFinite(parsed) || parsed < 0) return undefined;
	return parsed;
}

export function describeTrajectoryError(error: unknown, isChineseUi: boolean) {
	if (error instanceof FocusAgentRequestError) {
		if (error.status === 503) {
			return isChineseUi
				? "当前环境还没有启用 Trajectory observability 后端。请先配置 Postgres trajectory 存储，或在支持该能力的环境里打开复盘台。"
				: "Trajectory observability is not available in this environment yet. Configure the Postgres-backed trajectory store, or open this page in an environment where observability is enabled.";
		}
		if (error.status === 401 || error.status === 403) {
			return isChineseUi
				? "当前账号没有访问复盘台数据的权限。请先确认登录状态和 Bearer Token。"
				: "Your current account cannot access trajectory data. Check the active login session and bearer token first.";
		}
		return isChineseUi
			? `复盘台数据请求失败（${error.status} ${error.statusText}）。`
			: `Trajectory request failed (${error.status} ${error.statusText}).`;
	}
	return isChineseUi
		? "复盘台数据加载失败，请稍后重试。"
		: "Failed to load trajectory data. Please retry in a moment.";
}
