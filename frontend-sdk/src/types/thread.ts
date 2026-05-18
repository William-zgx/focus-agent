import type {
	ContextUsageResponse,
	FocusAgentTokenUsageSummary,
} from "./common.js";
import type {
	BranchMeta,
	BranchStatus,
	FocusAgentBranchActionNavigation,
	FocusAgentBranchActionProposal,
	FocusAgentBranchRecord,
	FocusAgentImportedConclusion,
	FocusAgentMergeProposal,
} from "./branch.js";
import type { FocusAgentBranchDecisionSummary } from "./branch-decision.js";

export interface FocusAgentConversationSummary {
	root_thread_id: string;
	title: string;
	is_archived: boolean;
	archived_at?: string | null;
	created_at?: string | null;
	updated_at?: string | null;
	token_usage?: FocusAgentTokenUsageSummary;
}

export interface FocusAgentConversationListResponse {
	conversations: FocusAgentConversationSummary[];
}

export interface FocusAgentCreateConversationRequest {
	title?: string | null;
}

export interface FocusAgentUpdateConversationRequest {
	title: string;
}

export interface ThreadResolution {
	input_thread_id: string;
	root_thread_id: string;
	source_thread_id: string;
	branch_id?: string | null;
	is_root: boolean;
	branch_status: BranchStatus;
	diagnostic: string;
}

export type FocusAgentThreadResolution = ThreadResolution;

export interface ThreadContextPreviewRequest {
	draft_message?: string | null;
}

export interface ThreadContextPreviewResponse {
	context_usage: ContextUsageResponse;
}

export interface FocusAgentToolApprovalInterrupt {
	kind: "tool_approval";
	interrupt_id: string;
	tool_name: string;
	tool_call_id: string;
	redacted_args: Record<string, unknown>;
	risk_level: string;
	policy_version: string;
	created_at: string;
}

export interface FocusAgentToolApprovalDecision {
	kind: "tool_approval";
	interrupt_id: string;
	tool_call_id: string;
	approved: boolean;
	reason?: string | null;
}

export type ThreadContextCompactTrigger =
	| "manual"
	| "auto_pre_send"
	| "auto_post_turn";

export interface ThreadContextCompactRequest {
	trigger?: ThreadContextCompactTrigger;
}

export interface ThreadStateResponse {
	thread_id: string;
	root_thread_id: string;
	assistant_message?: string | null;
	rolling_summary: string;
	selected_model: string;
	selected_thinking_mode: string;
	branch_meta?: BranchMeta | null;
	merge_proposal?: FocusAgentMergeProposal | null;
	merge_decision?: Record<string, unknown> | null;
	merge_queue: FocusAgentImportedConclusion[];
	active_skill_ids: string[];
	messages: Array<Record<string, unknown>>;
	interrupts: unknown[];
	branch_actions: FocusAgentBranchActionProposal[];
	branch_decision_summary?: FocusAgentBranchDecisionSummary | null;
	trace: Record<string, unknown>;
	context_usage?: ContextUsageResponse | null;
}

export interface ThreadContextCompactResponse extends ThreadStateResponse {}

export interface FocusAgentBranchActionExecuteResponse {
	thread_state: ThreadStateResponse;
	branch_action: FocusAgentBranchActionProposal;
	branch_record?: FocusAgentBranchRecord | null;
	navigation?: FocusAgentBranchActionNavigation | null;
}
