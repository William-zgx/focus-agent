export type FocusAgentAttentionLevel = "quiet" | "notify" | "ask";

export interface FocusAgentAttentionReason {
	code: string;
	source_ids: string[];
}

export interface FocusAgentAttentionPolicy {
	level: FocusAgentAttentionLevel;
	reasons: FocusAgentAttentionReason[];
}

export interface FocusAgentAttentionItem {
	source_id: string;
	kind: string;
	status: string;
	text: string;
	previous_status?: string | null;
}

export interface FocusAgentAttentionEvidence {
	source_id: string;
	kind: string;
	thread_id: string;
	action_id?: string | null;
	run_id?: string | null;
}

export interface FocusAgentResumePacket {
	goal: string;
	decisions: FocusAgentAttentionItem[];
	open_items: FocusAgentAttentionItem[];
	next_action?: FocusAgentAttentionItem | null;
	evidence: FocusAgentAttentionEvidence[];
}

export interface FocusAgentAttentionDiff {
	first_visit: boolean;
	frontier_missing: boolean;
	new_message_count: number;
	new_outcome_count: number;
	new_failed_outcome_count: number;
	action_transition_count: number;
	highlights: FocusAgentAttentionItem[];
}

export interface FocusAgentAttentionCursor {
	version: number;
	last_message_id?: string | null;
	seen_outcome_ids: string[];
	action_statuses: Record<string, string>;
	reviewed_at?: string | null;
}

export interface FocusAgentAttentionReviewRequest {
  cursor: FocusAgentAttentionCursor;
}

export interface FocusAgentAttentionSnapshot {
	thread_id: string;
	policy: FocusAgentAttentionPolicy;
	resume: FocusAgentResumePacket;
	diff: FocusAgentAttentionDiff;
	current_cursor: FocusAgentAttentionCursor;
}
