export type BranchDecisionAction =
	| "split"
	| "conclude"
	| "merge_candidate"
	| "continue_current"
	| "fork_child_branch"
	| "fork_sibling_branch";

export type BranchDecisionRecommendationTarget =
	| "continue_current"
	| "fork_sibling_branch"
	| "fork_child_branch";

export type BranchDecisionStatus =
	| "shadowed"
	| "suggested"
	| "promoted"
	| "dismissed"
	| "skipped"
	| "blocked"
	| "error";

export type BranchDecisionMode = "shadow" | "suggest" | "execute";

export interface FocusAgentBranchDecisionSignal {
	name: string;
	value?: unknown;
	score: number;
	weight: number;
	evidence_refs: string[];
	rationale: string;
}

export interface FocusAgentBranchDecisionConfig {
	enabled: boolean;
	mode: BranchDecisionMode;
	min_confidence: number;
	split_threshold: number;
	conclude_threshold: number;
	merge_candidate_threshold: number;
	rate_limit_per_hour: number;
	recommendation_enabled: boolean;
	recommendation_mode: BranchDecisionMode;
	recommendation_min_confidence: number;
}

export interface FocusAgentBranchDecisionEvent {
	decision_id: string;
	user_id?: string | null;
	root_thread_id: string;
	source_thread_id: string;
	branch_id?: string | null;
	recommendation_target?: BranchDecisionRecommendationTarget | null;
	target_parent_thread_id?: string | null;
	suggested_branch_name?: string | null;
	confidence?: number | null;
	action: BranchDecisionAction;
	status: BranchDecisionStatus;
	mode: BranchDecisionMode;
	score: number;
	threshold: number;
	signals: FocusAgentBranchDecisionSignal[];
	rationale: string;
	idempotency_key?: string | null;
	request_id?: string | null;
	trace_id?: string | null;
	promoted_action_id?: string | null;
	dismiss_reason?: string | null;
	error?: string | null;
	metadata: Record<string, unknown>;
	created_at: string;
	updated_at: string;
	executed_at?: string | null;
}

export interface FocusAgentBranchDecisionSummary {
	latest_decision?: FocusAgentBranchDecisionEvent | null;
	actionable: boolean;
	pending_action_id?: string | null;
	dismissed_count: number;
}

export interface FocusAgentBranchDecisionListResponse {
	items: FocusAgentBranchDecisionEvent[];
	count: number;
}

export interface FocusAgentBranchDecisionDismissRequest {
	reason?: string | null;
}
