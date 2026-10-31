import type { FocusAgentMergeQueueEntry } from "@focus-agent/web-sdk";

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
	/** Evidence per key finding (finding text -> refs), when the merge kept it. */
	findingEvidenceRefs: Record<string, string[]>;
	importedAt?: string;
	/** Body text of a legacy notice that only carried plain text. */
	legacyBody?: string;
}

export function findingEvidenceRefsValue(
	value: unknown,
): Record<string, string[]> {
	const record = recordValue(value);
	const refs: Record<string, string[]> = {};
	for (const [finding, items] of Object.entries(record ?? {})) {
		const list = stringListValue(items);
		if (normalizeText(finding) && list.length > 0) refs[finding] = list;
	}
	return refs;
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
				findingEvidenceRefs: findingEvidenceRefsValue(
					metadata.finding_evidence_refs,
				),
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
		findingEvidenceRefs: {},
		legacyBody: content.trim().slice(legacy[0].length).trim(),
	};
}

/**
 * Fills what the notice lacks from the target thread's `merge_queue` entry:
 * per-finding evidence, the child thread link, and structure for legacy text.
 */
export function withMergeQueueDetails(
	view: BranchImportView,
	mergeQueue: FocusAgentMergeQueueEntry[] | undefined,
): BranchImportView {
	const entry = [...(mergeQueue ?? [])]
		.reverse()
		.find((item) =>
			view.branchId
				? item.branch_id === view.branchId
				: item.branch_name === view.branchName,
		);
	if (!entry) return view;
	const merged: BranchImportView = {
		...view,
		branchId: view.branchId ?? entry.branch_id,
		childThreadId: view.childThreadId ?? entry.child_thread_id ?? undefined,
		findingEvidenceRefs:
			Object.keys(view.findingEvidenceRefs).length > 0
				? view.findingEvidenceRefs
				: findingEvidenceRefsValue(entry.finding_evidence_refs),
	};
	if (view.legacyBody === undefined || !normalizeText(entry.summary)) {
		return merged;
	}
	return {
		...merged,
		summary: normalizeText(entry.summary),
		keyFindings: stringListValue(entry.key_findings),
		openQuestions: stringListValue(entry.open_questions),
		evidenceRefs: stringListValue(entry.evidence_refs),
		artifacts: stringListValue(entry.artifacts),
		legacyBody: undefined,
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
