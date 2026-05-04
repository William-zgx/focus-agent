import type { FocusAgentTrajectoryStep } from "@focus-agent/web-sdk";

import { isRecord } from "./trajectory-search-utils";

export function stringifyMetadataValue(value: unknown) {
	if (value === undefined || value === null) return "";
	if (typeof value === "string") return value.trim();
	if (typeof value === "number" || typeof value === "boolean")
		return String(value);
	try {
		const text = JSON.stringify(value);
		if (!text) return "";
		return text.length > 120 ? `${text.slice(0, 120)}…` : text;
	} catch {
		return "";
	}
}

export function findNestedMetadataValue(
	source: unknown,
	aliases: readonly string[],
	options?: { depth?: number; seen?: WeakSet<object> },
): string {
	const depth = options?.depth ?? 0;
	if (depth > 4) return "";
	if (Array.isArray(source)) {
		for (const item of source) {
			const match = findNestedMetadataValue(item, aliases, {
				depth: depth + 1,
				seen: options?.seen,
			});
			if (match) return match;
		}
		return "";
	}
	if (!isRecord(source)) return "";
	const seen = options?.seen ?? new WeakSet<object>();
	if (seen.has(source)) return "";
	seen.add(source);

	for (const alias of aliases) {
		if (alias in source) {
			const match = stringifyMetadataValue(source[alias]);
			if (match) return match;
		}
	}

	for (const value of Object.values(source)) {
		const match = findNestedMetadataValue(value, aliases, {
			depth: depth + 1,
			seen,
		});
		if (match) return match;
	}
	return "";
}

export function findMetadataAcrossSources(
	sources: unknown[],
	aliases: readonly string[],
) {
	for (const source of sources) {
		const match = findNestedMetadataValue(source, aliases);
		if (match) return match;
	}
	return "";
}

export function findStepRuntimeSignal(
	step: FocusAgentTrajectoryStep,
	aliases: readonly string[],
) {
	return findNestedMetadataValue(step.runtime, aliases);
}
