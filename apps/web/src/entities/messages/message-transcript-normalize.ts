export function normalizeMessageType(type: unknown) {
	return String(type || "")
		.trim()
		.toLowerCase();
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
