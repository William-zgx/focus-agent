const DIAGNOSTIC_STATUSES = new Set(["shadowed", "skipped", "blocked"]);
const SEMANTIC_DIAGNOSTIC_KEYS = [
	"semantic_relatedness",
	"semantic_relationship",
	"semantic_reason",
	"semantic_classifier_status",
] as const;

type DiagnosticSource = {
	diagnostic?: unknown;
	dismiss_reason?: string | null;
	error?: string | null;
	metadata?: Record<string, unknown> | null;
	mode?: string | null;
	rationale?: string | null;
	reason?: string | null;
	recommendation_user_visible?: boolean | null;
	semantic_classifier_status?: string | null;
	semantic_reason?: string | null;
	semantic_relatedness?: number | string | null;
	semantic_relationship?: string | null;
	source_decision_mode?: string | null;
	source_decision_status?: string | null;
	status?: string | null;
};

type SemanticDiagnosticEntry = {
	key: (typeof SEMANTIC_DIAGNOSTIC_KEYS)[number];
	label: string;
	value: string;
};

function nonEmptyText(value: unknown): string {
	return typeof value === "string" ? value.trim() : "";
}

function diagnosticObjectText(value: Record<string, unknown>): string {
	for (const key of [
		"gate_reason",
		"blocked_reason",
		"skipped_reason",
		"skip_reason",
		"shadow_reason",
		"message",
		"reason",
		"detail",
		"summary",
		"code",
	]) {
		const text = nonEmptyText(value[key]);
		if (text) return text;
	}
	for (const nested of Object.values(value)) {
		const text = diagnosticText(nested);
		if (text) return text;
	}
	return "";
}

function metadataDiagnosticText(
	metadata: Record<string, unknown> | null | undefined,
) {
	if (!metadata) return "";
	for (const key of [
		"diagnostic",
		"diagnostic_reason",
		"blocked_reason",
		"skipped_reason",
		"skip_reason",
		"shadow_reason",
		"reason",
	]) {
		const value = metadata[key];
		const text = diagnosticText(value);
		if (text) return text;
	}
	return "";
}

function recordValue(source: unknown): Record<string, unknown> | null {
	return source && typeof source === "object" && !Array.isArray(source)
		? (source as Record<string, unknown>)
		: null;
}

function semanticValue(
	source: DiagnosticSource,
	key: SemanticDiagnosticEntry["key"],
): unknown {
	const direct = source[key];
	if (direct !== undefined && direct !== null) return direct;

	const metadata = recordValue(source.metadata);
	if (metadata && metadata[key] !== undefined && metadata[key] !== null) {
		return metadata[key];
	}

	const diagnostic = recordValue(source.diagnostic);
	if (diagnostic && diagnostic[key] !== undefined && diagnostic[key] !== null) {
		return diagnostic[key];
	}

	const details = recordValue(diagnostic?.details);
	if (details && details[key] !== undefined && details[key] !== null) {
		return details[key];
	}

	return undefined;
}

function semanticDisplayText(value: unknown): string {
	if (typeof value === "number" && Number.isFinite(value)) {
		return value >= 0 && value <= 1
			? `${Math.round(value * 100)}%`
			: String(value);
	}
	return nonEmptyText(value);
}

export function diagnosticText(value: unknown): string {
	const direct = nonEmptyText(value);
	if (direct) return direct;
	if (value && typeof value === "object" && !Array.isArray(value)) {
		return diagnosticObjectText(value as Record<string, unknown>);
	}
	return "";
}

export function branchDecisionDiagnosticText(source: DiagnosticSource): string {
	return (
		diagnosticText(source.diagnostic) ||
		metadataDiagnosticText(source.metadata) ||
		nonEmptyText(source.error) ||
		nonEmptyText(source.dismiss_reason) ||
		nonEmptyText(source.reason)
	);
}

export function isBranchHandoffDecision(source: DiagnosticSource): boolean {
	const metadata = recordValue(source.metadata);
	if (!metadata) return false;
	return (
		nonEmptyText(metadata.source) === "branch_handoff" &&
		metadata.branch_handoff_auto_run === true
	);
}

export function branchHandoffRunStatus(source: DiagnosticSource): string {
	const metadata = recordValue(source.metadata);
	return nonEmptyText(metadata?.handoff_run_status).toLowerCase();
}

export function branchDecisionSemanticDiagnosticEntries(
	source: DiagnosticSource,
): SemanticDiagnosticEntry[] {
	const labels: Record<SemanticDiagnosticEntry["key"], string> = {
		semantic_classifier_status: "semantic_classifier_status",
		semantic_reason: "semantic_reason",
		semantic_relatedness: "semantic_relatedness",
		semantic_relationship: "semantic_relationship",
	};
	const statusText = semanticDisplayText(
		semanticValue(source, "semantic_classifier_status"),
	).toLowerCase();
	if (statusText === "not_run") return [];
	return SEMANTIC_DIAGNOSTIC_KEYS.flatMap((key) => {
		const value = semanticDisplayText(semanticValue(source, key));
		return value ? [{ key, label: labels[key], value }] : [];
	});
}

export function shouldShowBranchDecisionDiagnostic(
	status: string | null | undefined,
) {
	return DIAGNOSTIC_STATUSES.has(String(status ?? ""));
}

export function branchDecisionAuditOnlyText(isChineseUi: boolean) {
	return isChineseUi
		? "当前为 shadow，仅审计不展示推荐卡。"
		: "Currently shadow-only: audit is recorded, but no recommendation card is shown.";
}
