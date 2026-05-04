export const DEFAULT_DRY_RUN_MESSAGE =
  "Plan the implementation, update backend and Web code, verify regression gates, and prepare release notes.";

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

export function jsonPreview(value: unknown) {
  return JSON.stringify(value, null, 2);
}

export function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}
