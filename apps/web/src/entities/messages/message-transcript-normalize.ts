export function normalizeMessageType(type: unknown) {
	const normalized = String(type || "")
		.trim()
		.toLowerCase();
	if (normalized === "assistant") {
		return "ai";
	}
	if (normalized === "user") {
		return "human";
	}
	return normalized;
}

export function normalizeText(value: unknown) {
	return String(value ?? "").trim();
}

export function parseJsonValue(text: string): unknown | null {
	const candidate = normalizeText(text);
	if (!candidate) {
		return null;
	}
	try {
		return JSON.parse(candidate);
	} catch {
		return null;
	}
}
