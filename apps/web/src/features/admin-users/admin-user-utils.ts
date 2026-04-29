import type { FocusAgentUser } from "@focus-agent/web-sdk";

export const ADMIN_ROLE_OPTIONS = ["admin", "member", "viewer"] as const;
export const ADMIN_USER_STATUSES = ["active", "disabled", "invited", "deleted"] as const;

export function splitRoleDraft(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)
    .filter((item, index, all) => all.indexOf(item) === index);
}

export function metadataToDraft(value: Record<string, unknown> | null | undefined): string {
  return JSON.stringify(value ?? {}, null, 2);
}

export function parseMetadataDraft(value: string): {
  metadata: Record<string, unknown> | null;
  error: string | null;
} {
  const raw = value.trim();
  if (!raw) {
    return { metadata: {}, error: null };
  }
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return { metadata: null, error: "Metadata must be a JSON object." };
    }
    return { metadata: parsed as Record<string, unknown>, error: null };
  } catch (error: unknown) {
    return {
      metadata: null,
      error: error instanceof Error ? error.message : "Metadata JSON is invalid.",
    };
  }
}

export function formatAdminDate(value: string | null | undefined, locale: string): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(locale, {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function formatUserLabel(user: FocusAgentUser | null | undefined): string {
  if (!user) return "-";
  return user.display_name || user.email || user.user_id;
}

export function statusTone(status: string): "success" | "warning" | "danger" | "neutral" {
  if (status === "active") return "success";
  if (status === "disabled") return "warning";
  if (status === "invited") return "neutral";
  if (status === "deleted") return "danger";
  return "neutral";
}
