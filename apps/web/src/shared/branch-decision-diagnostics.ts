const DIAGNOSTIC_STATUSES = new Set(["shadowed", "skipped", "blocked"]);

type DiagnosticSource = {
	diagnostic?: unknown;
	dismiss_reason?: string | null;
	error?: string | null;
	metadata?: Record<string, unknown> | null;
	mode?: string | null;
	rationale?: string | null;
	reason?: string | null;
	recommendation_user_visible?: boolean | null;
	source_decision_mode?: string | null;
	source_decision_status?: string | null;
	status?: string | null;
};

function nonEmptyText(value: unknown): string {
	return typeof value === "string" ? value.trim() : "";
}

function diagnosticObjectText(value: Record<string, unknown>): string {
	for (const key of ["message", "reason", "detail", "summary", "code"]) {
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
