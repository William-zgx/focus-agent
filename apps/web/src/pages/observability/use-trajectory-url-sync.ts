import { useEffect } from "react";

import type {
	SortMode,
	StatusMode,
} from "@/features/trajectory-observability/trajectory-utils";

type UseTrajectoryUrlSyncProps = {
	statusFilter: StatusMode;
	toolFilter: string;
	threadFilter: string;
	requestFilter: string;
	traceFilter: string;
	modelFilter: string;
	minLatency: string;
	fallbackOnly: boolean;
	hasErrorOnly: boolean;
	hasInvalidLatency: boolean;
	sortMode: SortMode;
	selectedTurnId: string;
};

const BOOLEAN_TRUE = "1";
const BOOLEAN_FALSE = "";

function normalizeDefaultValue(value: string | boolean | undefined) {
	if (typeof value === "boolean") {
		return value ? BOOLEAN_TRUE : BOOLEAN_FALSE;
	}
	if (value === undefined) return undefined;
	return value.trim();
}

function syncParam(
	params: URLSearchParams,
	key: string,
	value: string | boolean,
	defaultValue?: string | boolean,
) {
	const normalized =
		typeof value === "boolean"
			? value
				? BOOLEAN_TRUE
				: BOOLEAN_FALSE
			: value.trim();
	const normalizedDefault = normalizeDefaultValue(defaultValue);
	if (!normalized || normalized === normalizedDefault) {
		params.delete(key);
		return;
	}
	params.set(key, normalized);
}

export function useTrajectoryUrlSync({
	fallbackOnly,
	hasErrorOnly,
	hasInvalidLatency,
	minLatency,
	modelFilter,
	requestFilter,
	selectedTurnId,
	sortMode,
	statusFilter,
	threadFilter,
	toolFilter,
	traceFilter,
}: UseTrajectoryUrlSyncProps) {
	useEffect(() => {
		if (typeof window === "undefined") return;
		const url = new URL(window.location.href);
		const params = url.searchParams;
		syncParam(params, "status", statusFilter, "all");
		syncParam(params, "tool", toolFilter);
		syncParam(params, "thread", threadFilter);
		syncParam(params, "request", requestFilter);
		syncParam(params, "trace", traceFilter);
		syncParam(params, "model", modelFilter);
		syncParam(params, "minLatency", hasInvalidLatency ? "" : minLatency);
		syncParam(params, "fallbackOnly", fallbackOnly);
		syncParam(params, "hasErrorOnly", hasErrorOnly);
		syncParam(params, "sort", sortMode, "newest");
		syncParam(params, "turn", selectedTurnId);
		const query = params.toString();
		const nextHref = `${url.pathname}${query ? `?${query}` : ""}${url.hash}`;
		const currentHref = `${url.pathname}${url.search}${url.hash}`;
		if (nextHref !== currentHref) {
			window.history.replaceState({}, "", nextHref);
		}
	}, [
		fallbackOnly,
		hasInvalidLatency,
		hasErrorOnly,
		minLatency,
		modelFilter,
		requestFilter,
		selectedTurnId,
		sortMode,
		statusFilter,
		threadFilter,
		toolFilter,
		traceFilter,
	]);
}
