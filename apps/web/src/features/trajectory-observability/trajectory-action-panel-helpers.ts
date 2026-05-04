export type RunningTrajectoryAction =
	| "replay"
	| "promote"
	| "batchReplay"
	| "batchPromote";

export interface TrajectoryActionOptions {
	answerSubstringChars: string;
	caseIdPrefix: string;
	copyAnswerSubstring: boolean;
	copyToolTrajectory: boolean;
}

export function buildTrajectoryActionRequest(options: TrajectoryActionOptions) {
	return {
		case_id_prefix: options.caseIdPrefix,
		copy_tool_trajectory: options.copyToolTrajectory,
		copy_answer_substring: options.copyAnswerSubstring,
		answer_substring_chars: Number(options.answerSubstringChars || 0),
	};
}

export function compactId(value?: string | null) {
	const text = String(value || "").trim();
	if (!text) return "—";
	if (text.length <= 18) return text;
	return `${text.slice(0, 8)}…${text.slice(-6)}`;
}

export async function copyText(value: string) {
	if (!value) return;
	try {
		await navigator.clipboard.writeText(value);
	} catch {
		// ignore clipboard failures
	}
}

export function downloadTextArtifact(name: string, body: string, mime: string) {
	const blob = new Blob([body], { type: mime });
	const url = URL.createObjectURL(blob);
	const anchor = document.createElement("a");
	anchor.href = url;
	anchor.download = name;
	anchor.click();
	URL.revokeObjectURL(url);
}

export function formatDuration(value?: number | null) {
	if (typeof value !== "number" || Number.isNaN(value)) return "—";
	if (value >= 1000) return `${(value / 1000).toFixed(2)}s`;
	return `${Math.round(value)}ms`;
}

export function formatSignedDelta(next: number, previous: number, unit = "") {
	const delta = next - previous;
	const prefix = delta > 0 ? "+" : "";
	return `${prefix}${delta.toFixed(1)}${unit}`;
}
