import type {
	FocusAgentRuntimeOutcome,
	FocusAgentTrajectoryStep,
	FocusAgentTrajectoryTurnDetail,
} from "@focus-agent/web-sdk";

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

export function asRuntimeOutcome(
	value: unknown,
): FocusAgentRuntimeOutcome | null {
	return isRecord(value) ? (value as FocusAgentRuntimeOutcome) : null;
}

export function findTaskOutcome(
	turn: FocusAgentTrajectoryTurnDetail,
): FocusAgentRuntimeOutcome | null {
	const directOutcome = asRuntimeOutcome(turn.task_outcome);
	if (directOutcome) return directOutcome;
	if (isRecord(turn.plan_meta)) {
		const planOutcome = asRuntimeOutcome(turn.plan_meta.task_outcome);
		if (planOutcome) return planOutcome;
	}
	return (
		asRuntimeOutcome(turn.runtime_outcome) ??
		(isRecord(turn.plan_meta)
			? (asRuntimeOutcome(turn.plan_meta.runtime_outcome) ??
				asRuntimeOutcome(turn.plan_meta.agent_runtime_outcome))
			: null)
	);
}

export function findToolOutcomes(
	turn: FocusAgentTrajectoryTurnDetail,
): FocusAgentRuntimeOutcome[] {
	const directOutcomes = Array.isArray(turn.tool_outcomes)
		? turn.tool_outcomes
		: null;
	const planMetaOutcomes =
		isRecord(turn.plan_meta) && Array.isArray(turn.plan_meta.tool_outcomes)
			? turn.plan_meta.tool_outcomes
			: null;
	return (directOutcomes ?? planMetaOutcomes ?? []).flatMap((item) => {
		const outcome = asRuntimeOutcome(item);
		return outcome ? [outcome] : [];
	});
}

export function findStepRuntimeOutcome(
	step: FocusAgentTrajectoryStep,
): FocusAgentRuntimeOutcome | null {
	const runtime = isRecord(step.runtime) ? step.runtime : null;
	return (
		asRuntimeOutcome(step.tool_outcome) ??
		asRuntimeOutcome(step.outcome) ??
		asRuntimeOutcome(runtime?.tool_outcome) ??
		asRuntimeOutcome(runtime?.outcome) ??
		asRuntimeOutcome(runtime?.runtime_outcome)
	);
}

export function readOutcomeText(
	outcome: FocusAgentRuntimeOutcome | null | undefined,
	aliases: readonly string[],
) {
	if (!outcome) return "";
	for (const alias of aliases) {
		if (alias in outcome) {
			const text = stringifyMetadataValue(outcome[alias]);
			if (text) return text;
		}
	}
	return "";
}

export function outcomeTone(status: string) {
	const normalized = status.toLowerCase();
	if (
		normalized === "succeeded" ||
		normalized === "success" ||
		normalized === "answered" ||
		normalized === "verified"
	) {
		return "success";
	}
	if (
		normalized.includes("recover") ||
		normalized.includes("degrad") ||
		normalized.includes("fallback") ||
		normalized === "skipped"
	) {
		return "warning";
	}
	if (
		normalized.includes("fail") ||
		normalized.includes("block") ||
		normalized.includes("error")
	) {
		return "danger";
	}
	return "neutral";
}
