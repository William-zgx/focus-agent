import { normalizeText } from "./message-transcript-normalize";
import { recordValue, stringListValue } from "./message-transcript-tool-calls";

/** Normalized view of a merged-branch conclusion, from metadata or legacy text. */
export interface BranchImportView {
	branchId?: string;
	branchName: string;
	childThreadId?: string;
	summary: string;
	keyFindings: string[];
	openQuestions: string[];
	evidenceRefs: string[];
	artifacts: string[];
	importedAt?: string;
	/** Body text of a legacy notice that only carried plain text. */
	legacyBody?: string;
}

export function branchImportFromMessage(
	message: Record<string, unknown>,
	content: string,
): BranchImportView | null {
	const metadata = recordValue(recordValue(message.metadata)?.branch_import);
	if (metadata) {
		const branchName = normalizeText(metadata.branch_name);
		const summary = normalizeText(metadata.summary);
		if (branchName || summary) {
			return {
				branchId: normalizeText(metadata.branch_id) || undefined,
				branchName,
				childThreadId: normalizeText(metadata.child_thread_id) || undefined,
				summary,
				keyFindings: stringListValue(metadata.key_findings),
				openQuestions: stringListValue(metadata.open_questions),
				evidenceRefs: stringListValue(metadata.evidence_refs),
				artifacts: stringListValue(metadata.artifacts),
				importedAt: normalizeText(metadata.imported_at) || undefined,
			};
		}
	}
	// Notices written before branch_import metadata existed only carry text.
	const legacy = /^Imported conclusion from branch '(.+?)':\s*\n?/.exec(
		content.trim(),
	);
	if (!legacy) return null;
	return {
		branchName: legacy[1],
		summary: "",
		keyFindings: [],
		openQuestions: [],
		evidenceRefs: [],
		artifacts: [],
		legacyBody: content.trim().slice(legacy[0].length).trim(),
	};
}

/* Lets the merge review ask the next transcript render to reveal its import. */
type HighlightRequest = { branchId?: string; branchName: string };

const HIGHLIGHT_REQUEST_TTL_MS = 30_000;
let pendingHighlight: (HighlightRequest & { requestedAt: number }) | null =
	null;

export function requestBranchImportHighlight(request: HighlightRequest) {
	pendingHighlight = { ...request, requestedAt: Date.now() };
}

export function matchPendingBranchImportHighlight(view: BranchImportView) {
	const request = pendingHighlight;
	if (!request) return false;
	if (Date.now() - request.requestedAt > HIGHLIGHT_REQUEST_TTL_MS) {
		pendingHighlight = null;
		return false;
	}
	if (request.branchId && view.branchId) {
		return request.branchId === view.branchId;
	}
	return request.branchName === view.branchName;
}

export function clearPendingBranchImportHighlight() {
	pendingHighlight = null;
}
