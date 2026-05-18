import type { FocusAgentTokenUsageSummary } from "./common.js";
import type {
	BranchDecisionMode,
	BranchDecisionStatus,
	FocusAgentBranchDecisionDiagnostic,
} from "./branch-decision.js";

export type BranchActionKind =
	| "fork_sibling_branch"
	| "fork_child_branch"
	| "open_existing_branch"
	| "return_parent_branch";

export type BranchActionStatus =
	| "pending"
	| "executed"
	| "dismissed"
	| "failed";

export interface FocusAgentBranchActionNavigation {
	root_thread_id: string;
	thread_id: string;
}

export interface FocusAgentBranchActionProposal {
	action_id: string;
	kind: BranchActionKind;
	status: BranchActionStatus;
	root_thread_id: string;
	source_thread_id: string;
	target_parent_thread_id: string;
	suggested_branch_name?: string | null;
	branch_role: BranchRole;
	reason: string;
	created_at: string;
	executed_at?: string | null;
	dismissed_at?: string | null;
	failed_at?: string | null;
	error?: string | null;
	navigation?: FocusAgentBranchActionNavigation | null;
	source?: string | null;
	source_decision_id?: string | null;
	source_decision_status?: BranchDecisionStatus | null;
	source_decision_mode?: BranchDecisionMode | null;
	confidence?: number | null;
	rationale?: string | null;
	recommendation_user_visible?: boolean | null;
	diagnostic?: FocusAgentBranchDecisionDiagnostic | string | null;
	handoff_message?: string | null;
}

export type BranchRole =
	| "main"
	| "explore_alternatives"
	| "deep_dive"
	| "execute"
	| "verify"
	| "writeup";
export type BranchStatus =
	| "active"
	| "paused"
	| "preparing_merge_review"
	| "awaiting_merge_review"
	| "merged"
	| "discarded"
	| "closed";
export type MergeMode =
	| "none"
	| "summary_only"
	| "summary_plus_evidence"
	| "selected_artifacts";
export type MergeTarget = "return_thread" | "root_thread";

export interface BranchMeta {
	branch_id: string;
	root_thread_id: string;
	parent_thread_id: string;
	return_thread_id: string;
	branch_name: string;
	branch_role: BranchRole;
	branch_depth: number;
	branch_status: BranchStatus;
	is_archived?: boolean;
	archived_at?: string | null;
	fork_checkpoint_id?: string | null;
	fork_strategy: string;
}

export interface BranchTreeNode {
	thread_id: string;
	root_thread_id: string;
	parent_thread_id?: string | null;
	branch_id?: string | null;
	branch_name: string;
	branch_role: BranchRole;
	branch_status: BranchStatus;
	is_archived?: boolean;
	archived_at?: string | null;
	branch_depth: number;
	fork_strategy?: string | null;
	token_usage?: FocusAgentTokenUsageSummary;
	children: BranchTreeNode[];
}

export interface BranchTreeResponse {
	root: BranchTreeNode;
	archived_branches: BranchTreeNode[];
}

export interface FocusAgentMergeProposal {
	summary: string;
	key_findings: string[];
	open_questions: string[];
	evidence_refs: string[];
	artifacts: string[];
	recommended_import_mode: MergeMode;
}

export interface FocusAgentMergeProposalOverrides {
	summary?: string | null;
	key_findings?: string[] | null;
	open_questions?: string[] | null;
	evidence_refs?: string[] | null;
	artifacts?: string[] | null;
	recommended_import_mode?: MergeMode | null;
}

export interface FocusAgentImportedConclusion {
	branch_id: string;
	branch_name: string;
	mode: MergeMode;
	summary: string;
	key_findings: string[];
	evidence_refs: string[];
	artifacts: string[];
	rationale?: string | null;
}

export interface FocusAgentBranchRecord {
	branch_id: string;
	root_thread_id: string;
	parent_thread_id: string;
	child_thread_id: string;
	return_thread_id: string;
	owner_user_id: string;
	branch_name: string;
	branch_role: BranchRole;
	branch_depth: number;
	branch_status: BranchStatus;
	is_archived: boolean;
	archived_at?: string | null;
	fork_checkpoint_id?: string | null;
	fork_strategy: string;
	merge_proposal?: FocusAgentMergeProposal | null;
	merge_decision?: Record<string, unknown> | null;
}

export interface FocusAgentForkBranchRequest {
	parent_thread_id: string;
	branch_name?: string;
	name_source?: string;
	branch_role?: BranchRole;
	fork_checkpoint_id?: string;
	language?: "en" | "zh";
}

export interface FocusAgentRenameBranchRequest {
	branch_name: string;
}

export interface FocusAgentApplyMergeDecisionRequest {
	approved?: boolean;
	mode?: MergeMode;
	target?: MergeTarget;
	rationale?: string | null;
	selected_artifacts?: string[];
	proposal_overrides?: FocusAgentMergeProposalOverrides | null;
}

export interface FocusAgentApplyMergeDecisionResponse {
	imported?: FocusAgentImportedConclusion | null;
	target_thread_id?: string | null;
}
