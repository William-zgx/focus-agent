export const DEFAULT_DRY_RUN_MESSAGE =
	"Plan the implementation, update backend and Web code, verify regression gates, and prepare release notes.";

export const DEFAULT_AVAILABLE_TOOLS =
	"search_code,read_file,git_diff,web_search,memory_search,skills_list,skill_view,write_text_artifact";

export function roleLabel(role: string) {
	return role.replaceAll("_", " ");
}

export function asRecord(value: unknown): Record<string, unknown> {
	return value && typeof value === "object" && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: {};
}

export function asArray(value: unknown): Array<Record<string, unknown>> {
	return Array.isArray(value) ? value.map(asRecord) : [];
}

export function asStringArray(value: unknown): string[] {
	return Array.isArray(value) ? value.map(String) : [];
}

export function jsonPreview(value: unknown) {
	return JSON.stringify(value, null, 2);
}

export function errorMessage(error: unknown, fallback: string) {
	return error instanceof Error ? error.message : fallback;
}

export function parseAvailableTools(value: string) {
	return value
		.split(",")
		.map((item) => item.trim())
		.filter(Boolean);
}
