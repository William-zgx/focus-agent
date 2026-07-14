export type AgentTeamSessionStatus =
	| "planning"
	| "running"
	| "awaiting_review"
	| "merging"
	| "completed"
	| "failed"
	| "cancelled";

export type AgentTeamTaskStatus =
	| "pending"
	| "queued"
	| "ready"
	| "running"
	| "blocked"
	| "done"
	| "failed"
	| "cancelled";

export type AgentTeamRole =
	| "planner"
	| "architect"
	| "backend_executor"
	| "frontend_executor"
	| "test_engineer"
	| "reviewer"
	| "verifier"
	| "writer";

export type AgentTeamFinalAnswerStatus =
	| "ready"
	| "placeholder"
	| "blocked"
	| "error"
	| "missing"
	| string;

export type AgentTeamMergeDecisionAction =
	| "merge"
	| "request_changes"
	| "split_followup"
	| "discard"
	| string;

export type AgentTeamMergeReviewStatus =
	| "draft"
	| "ready"
	| "approved"
	| "applied"
	| "rejected"
	| "conflict"
	| "error"
	| string;

export interface AgentTeamMergeDecisionRequest {
	apply?: boolean;
	next_action?: AgentTeamMergeDecisionAction;
	rationale?: string | null;
	accepted_tasks?: string[];
	rejected_tasks?: string[];
}

export interface AgentTeamMergeDecisionResponse {
	session_id?: string;
	action?: AgentTeamMergeDecisionAction;
	next_action?: AgentTeamMergeDecisionAction;
	approved?: boolean;
	apply?: boolean;
	rationale?: string | null;
	accepted_tasks?: string[];
	rejected_tasks?: string[];
	session?: AgentTeamSession;
	merge_bundle?: AgentTeamMergeBundle | null;
}

export interface AgentTeamSession {
	session_id: string;
	root_thread_id: string;
	user_id?: string;
	title: string;
	goal: string;
	status: AgentTeamSessionStatus;
	mission_id?: string | null;
	mission_goal?: string | null;
	source_conversation_id?: string | null;
	planning_source?: string | null;
	planning_rationale?: string | null;
	planner_model_id?: string | null;
	plan_generated_at?: string | null;
	plan_hash?: string | null;
	planning_error?: string | null;
	planning?: AgentTeamPlanningMetadata | null;
	skill_plan?: Record<string, unknown>;
	created_at?: string;
	updated_at?: string;
	latest_merge_bundle?: AgentTeamMergeBundle | null;
	merge_decision?:
		| AgentTeamMergeDecisionResponse
		| Record<string, unknown>
		| null;
}

export interface AgentTeamRunStatus {
	status?: string | null;
	state?: string | null;
	run_id?: string | null;
	started_at?: string | null;
	finished_at?: string | null;
	message?: string | null;
	error?: string | null;
	[key: string]: unknown;
}

export interface AgentTeamTask {
	task_id: string;
	session_id: string;
	branch_id?: string | null;
	child_thread_id?: string | null;
	role: AgentTeamRole | string;
	title?: string | null;
	goal: string;
	scope?: string[];
	dependencies?: string[];
	acceptance_criteria?: string[];
	planning_rationale?: string | null;
	sort_order?: number | null;
	task_type?: string | null;
	task_kind?: string | null;
	plan_source?: string | null;
	input_contract?: Record<string, unknown> | null;
	output_contract?: Record<string, unknown> | null;
	evidence_required?: string[];
	capability_requirements?: string[];
	risk_level?: string | null;
	write_scope?: string[];
	resource_claims?: string[];
	replan_policy?: Record<string, unknown> | null;
	context_refs?: Record<string, unknown>[];
	active_skill_ids?: string[];
	skill_resolution_events?: Record<string, unknown>[];
	status: AgentTeamTaskStatus | string;
	run_status?: AgentTeamRunStatus | string | null;
	output_artifact_ids?: string[];
	agent_run_id?: string | null;
	delegated_task_id?: string | null;
	artifact_ids?: string[];
	execution_status?: string | null;
	changed_files?: string[];
	test_evidence?: string[];
	verification_summary?: string | null;
	risk_notes?: string[];
	workspace_id?: string | null;
	workspace_branch?: string | null;
	workspace_path?: string | null;
	base_commit?: string | null;
	diff_summary?: string | null;
	workspace_status?: string | null;
	started_at?: string | null;
	finished_at?: string | null;
	last_error?: string | null;
	attempt?: number;
	max_attempts?: number;
	claim_owner?: string | null;
	claimed_until?: string | null;
	queued_at?: string | null;
	heartbeat_at?: string | null;
	execution_mode?: string | null;
	cancel_requested_at?: string | null;
	created_at?: string;
	updated_at?: string;
}

export interface AgentTeamRunMetadata {
	execution_mode?: string | null;
	scheduled_task_ids?: string[];
	running_task_ids?: string[];
	max_parallel_runs?: number;
}

export interface AgentTeamReadiness {
	status: "ready" | "disabled" | "degraded" | string;
	ready: boolean;
	enabled: boolean;
	service_available: boolean;
	capabilities: {
		task_run_queries: boolean;
		evidence_queries: boolean;
		revision_commands: boolean;
	};
	detail?: string | null;
}

export interface AgentTeamEvidence {
	evidence_id: string;
	task_run_id?: string | null;
	task_id?: string | null;
	session_id?: string | null;
	source_type: string;
	summary: string;
	artifact_id?: string | null;
	execution_profile?: string | null;
	execution_class: string;
	evidence_level: string;
	evidence_verdict: string;
	evidence_summary?: string | null;
	sandbox_id?: string | null;
	revision_id?: string | null;
	row_version: number;
	cancel_epoch: number;
	deliverable: boolean;
	metadata: Record<string, unknown>;
	created_at: string;
}

export interface AgentTeamEvidenceListResponse {
	items: AgentTeamEvidence[];
	count: number;
}

export interface AgentTeamArtifact {
	artifact_id: string;
	task_id?: string | null;
	kind?: string | null;
	title?: string | null;
	summary?: string | null;
	content?: string | null;
	payload?: Record<string, unknown> | null;
	uri?: string | null;
	created_at?: string;
}

export interface AgentTeamTaskOutput {
	output_id: string;
	task_id: string;
	kind?: string | null;
	artifact_id?: string | null;
	summary?: string | null;
	changed_files?: string[];
	test_evidence?: string[];
	workspace_id?: string | null;
	workspace_branch?: string | null;
	workspace_path?: string | null;
	base_commit?: string | null;
	diff_summary?: string | null;
	workspace_status?: string | null;
	risk_notes?: string[];
	metadata?: Record<string, unknown>;
	created_at?: string;
}

export interface AgentTeamMergeBundle {
	session_id: string;
	summary: string;
	final_answer?: string | null;
	final_answer_status?: AgentTeamFinalAnswerStatus | null;
	final_answer_warnings?: string[];
	source_output_ids?: string[];
	accepted_tasks?: string[];
	rejected_tasks?: string[];
	key_findings?: string[];
	changed_files?: string[];
	test_evidence?: string[];
	execution_evidence?: Record<string, unknown>[];
	open_questions?: string[];
	risk_items?: string[];
	recommended_next_action?:
		| "merge"
		| "request_changes"
		| "split_followup"
		| "discard"
		| string;
}

export interface AgentTeamMergeReviewTask {
	task_id: string;
	title?: string | null;
	role?: string | null;
	selected: boolean;
	adoptable?: boolean;
	changed_files?: string[];
	diff_summary?: string | null;
	test_evidence?: string[];
	risk_items?: string[];
	workspace_status?: string | null;
	workspace_branch?: string | null;
	workspace_path?: string | null;
	output_status?: AgentTeamFinalAnswerStatus | null;
	placeholder?: boolean;
	fake?: boolean;
}

export interface AgentTeamMergeReview {
	review_id: string;
	session_id: string;
	status: AgentTeamMergeReviewStatus;
	selected_task_ids?: string[];
	rejected_task_ids?: string[];
	task_reviews?: AgentTeamMergeReviewTask[];
	changed_files?: string[];
	diffstat?: string | null;
	diff_summary?: string | null;
	test_evidence?: string[];
	risk_items?: string[];
	conflict_files?: string[];
	apply_target?: string | null;
	last_error?: string | null;
	created_at?: string;
	updated_at?: string;
	approved_at?: string | null;
	applied_at?: string | null;
	rejected_at?: string | null;
	metadata?: Record<string, unknown> | null;
}

export interface AgentTeamMergeReviewResponse {
	review: AgentTeamMergeReview;
	events?: Array<Record<string, unknown>>;
}

export interface AgentTeamMergeReviewPreviewResponse {
	review: AgentTeamMergeReview;
	applicable: boolean;
	diff?: string | null;
	diffstat?: string | null;
	conflict_files?: string[];
	warnings?: string[];
}

export interface AgentTeamPlanningMetadata {
	source?: string | null;
	rationale?: string | null;
	planner_model_id?: string | null;
	generated_at?: string | null;
	plan_hash?: string | null;
	error?: string | null;
	task_count?: number;
}

export type AgentTeamToolApprovalStatus =
	| "pending"
	| "approved"
	| "rejected"
	| "auto_approved"
	| "timed_out"
	| string;

export interface AgentTeamToolApproval {
	request_id: string;
	session_id: string;
	agent_id: string;
	tool_name: string;
	tool_args: Record<string, unknown>;
	risk_level: string;
	status: AgentTeamToolApprovalStatus;
	submitted_at: number;
	timeout_at: number;
	decided_by?: string | null;
}

export interface AgentTeamToolApprovalListResponse {
	approvals?: AgentTeamToolApproval[];
	items?: AgentTeamToolApproval[];
	count?: number;
}

export interface AgentTeamToolApprovalDecisionRequest {
	approved: boolean;
	reason?: string | null;
}

export interface AgentTeamToolApprovalDecisionResponse {
	approval: AgentTeamToolApproval;
}

export interface AgentTeamSessionView {
	session: AgentTeamSession;
	tasks: AgentTeamTask[];
	outputs?: AgentTeamTaskOutput[];
	artifacts?: AgentTeamArtifact[];
	merge_bundle?: AgentTeamMergeBundle | null;
	planning?: AgentTeamPlanningMetadata | null;
	evidence?: string[];
	risks?: string[];
	dag?: Record<string, unknown> | null;
	merge_suggestion?: AgentTeamMergeBundle | null;
	run?: AgentTeamRunMetadata | null;
	pending_tool_approvals?: AgentTeamToolApproval[];
}

export interface AgentTeamCreateSessionRequest {
	title?: string;
	goal: string;
	root_thread_id?: string | null;
}

export interface AgentTeamListSessionsRequest {
	root_thread_id?: string;
	status?: AgentTeamSessionStatus | AgentTeamSessionStatus[];
	limit?: number;
	offset?: number;
}

export interface AgentTeamSessionListResponse {
	items: AgentTeamSession[];
	count: number;
}

export interface AgentTeamCreateTaskRequest {
	role: AgentTeamRole | string;
	goal: string;
	task_kind?: string | null;
	input_contract?: Record<string, unknown> | null;
	output_contract?: Record<string, unknown> | null;
	evidence_required?: string[];
	capability_requirements?: string[];
	risk_level?: string | null;
	write_scope?: string[];
	resource_claims?: string[];
	replan_policy?: Record<string, unknown> | null;
	scope?: string[];
	dependencies?: string[];
	acceptance_criteria?: string[];
	context_refs?: Record<string, unknown>[];
	active_skill_ids?: string[];
	skill_resolution_events?: Record<string, unknown>[];
	create_branch?: boolean;
	auto_fork_branch?: boolean | null;
	branch_name?: string | null;
	branch_id?: string | null;
	child_thread_id?: string | null;
	parent_thread_id?: string | null;
}

export interface AgentTeamDispatchRequest {
	create_branches?: boolean;
	auto_fork_branch?: boolean | null;
	parent_thread_id?: string | null;
}

export interface AgentTeamPlanSessionRequest {
	create_branches?: boolean;
	auto_fork_branch?: boolean | null;
	parent_thread_id?: string | null;
	replace_existing?: boolean;
	granularity?: "auto" | "coarse" | "balanced" | "detailed" | string;
	focus?: "auto" | "research" | "implementation" | "verification" | string;
	max_tasks?: number;
}

export interface AgentTeamRunSessionRequest {
	create_branches?: boolean;
	auto_fork_branch?: boolean | null;
	parent_thread_id?: string | null;
	task_ids?: string[];
	run_ready_only?: boolean;
	metadata?: Record<string, unknown> | null;
}

export interface AgentTeamRunTaskRequest {
	force?: boolean;
	create_branch?: boolean;
	auto_fork_branch?: boolean | null;
	parent_thread_id?: string | null;
	metadata?: Record<string, unknown> | null;
}

export type AgentTeamActionResponse =
	| AgentTeamSession
	| AgentTeamSessionView
	| AgentTeamTask
	| AgentTeamMergeBundle
	| AgentTeamMergeDecisionResponse
	| {
			session?: AgentTeamSession;
			task?: AgentTeamTask | null;
			tasks?: AgentTeamTask[];
			items?: AgentTeamTask[];
			outputs?: AgentTeamTaskOutput[];
			artifacts?: AgentTeamArtifact[];
			merge_bundle?: AgentTeamMergeBundle | null;
			merge_decision?: AgentTeamMergeDecisionResponse | null;
			bundle?: AgentTeamMergeBundle;
			decision?: AgentTeamMergeDecisionResponse;
			run?: AgentTeamRunMetadata | null;
			pending_tool_approvals?: AgentTeamToolApproval[];
			count?: number;
	  };

export interface AgentTeamClientContract {
	createAgentTeamSession: (
		request: AgentTeamCreateSessionRequest,
	) => Promise<AgentTeamSession | AgentTeamSessionView>;
	listAgentTeamSessions?: (request?: AgentTeamListSessionsRequest) => Promise<
		| AgentTeamSessionListResponse
		| {
				sessions?: AgentTeamSession[];
				items?: AgentTeamSession[];
				count?: number;
		  }
		| AgentTeamSession[]
	>;
	getAgentTeamSession: (
		sessionId: string,
	) => Promise<AgentTeamSession | AgentTeamSessionView>;
	getAgentTeamSessionView?: (
		sessionId: string,
	) => Promise<AgentTeamSessionView>;
	getAgentTeamReadiness?: () => Promise<AgentTeamReadiness>;
	listAgentTeamEvidence?: (
		sessionId: string,
	) => Promise<AgentTeamEvidenceListResponse>;
	dispatchAgentTeamSession?: (
		sessionId: string,
		request?: AgentTeamDispatchRequest,
	) => Promise<
		| AgentTeamSessionView
		| {
				session: AgentTeamSession;
				tasks?: AgentTeamTask[];
				items?: AgentTeamTask[];
				count?: number;
		  }
	>;
	planAgentTeamSession?: (
		sessionId: string,
		request?: AgentTeamPlanSessionRequest,
	) => Promise<AgentTeamActionResponse>;
	runAgentTeamSession?: (
		sessionId: string,
		request?: AgentTeamRunSessionRequest,
	) => Promise<AgentTeamActionResponse>;
	runAgentTeamTask?: (
		taskId: string,
		request?: AgentTeamRunTaskRequest,
	) => Promise<AgentTeamActionResponse>;
	retryAgentTeamTask?: (taskId: string) => Promise<AgentTeamActionResponse>;
	cancelAgentTeamTask?: (taskId: string) => Promise<AgentTeamActionResponse>;
	cancelAgentTeamSession?: (
		sessionId: string,
	) => Promise<AgentTeamActionResponse>;
	listAgentTeamTasks?: (
		sessionId: string,
		request?: Record<string, unknown>,
	) => Promise<{ items?: AgentTeamTask[]; count?: number } | AgentTeamTask[]>;
	createAgentTeamTask?: (
		sessionId: string,
		request: AgentTeamCreateTaskRequest,
	) => Promise<AgentTeamTask | AgentTeamSessionView>;
	prepareAgentTeamMergeBundle?: (
		sessionId: string,
		request?: Record<string, unknown>,
	) => Promise<AgentTeamMergeBundle | AgentTeamSessionView>;
	createAgentTeamMergeProposal?: (
		sessionId: string,
	) => Promise<AgentTeamMergeBundle | AgentTeamSessionView>;
	recordAgentTeamMergeDecision?: (
		sessionId: string,
		request: AgentTeamMergeDecisionRequest,
	) => Promise<AgentTeamMergeDecisionResponse | AgentTeamSessionView>;
	listAgentTeamMergeReviews?: (
		sessionId: string,
	) => Promise<{ items?: AgentTeamMergeReview[]; count?: number }>;
	createAgentTeamMergeReview?: (
		sessionId: string,
		request?: {
			selected_task_ids?: string[];
			rejected_task_ids?: string[];
			metadata?: Record<string, unknown> | null;
		},
	) => Promise<AgentTeamMergeReviewResponse>;
	updateAgentTeamMergeReview?: (
		sessionId: string,
		reviewId: string,
		request: {
			status?: AgentTeamMergeReviewStatus | null;
			selected_task_ids?: string[] | null;
			rejected_task_ids?: string[] | null;
			metadata?: Record<string, unknown> | null;
		},
	) => Promise<AgentTeamMergeReviewResponse>;
	previewAgentTeamMergeReview?: (
		sessionId: string,
		reviewId: string,
		request?: {
			selected_task_ids?: string[];
			rejected_task_ids?: string[];
			max_diff_bytes?: number | null;
		},
	) => Promise<AgentTeamMergeReviewPreviewResponse>;
	applyAgentTeamMergeReview?: (
		sessionId: string,
		reviewId: string,
		request?: {
			selected_task_ids?: string[];
			rejected_task_ids?: string[];
			apply_target?: string | null;
			rationale?: string | null;
		},
	) => Promise<AgentTeamMergeReviewResponse>;
	rejectAgentTeamMergeReview?: (
		sessionId: string,
		reviewId: string,
		request?: { reason?: string | null },
	) => Promise<AgentTeamMergeReviewResponse>;
	captureAgentTeamMergeReview?: (
		sessionId: string,
		reviewId: string,
	) => Promise<Record<string, unknown>>;
	listAgentTeamToolApprovals?: (
		sessionId: string,
	) => Promise<AgentTeamToolApprovalListResponse>;
	decideAgentTeamToolApproval?: (
		sessionId: string,
		requestId: string,
		request: AgentTeamToolApprovalDecisionRequest,
	) => Promise<AgentTeamToolApprovalDecisionResponse>;
	approveAgentTeamToolApproval?: (
		sessionId: string,
		requestId: string,
		request?: Omit<AgentTeamToolApprovalDecisionRequest, "approved">,
	) => Promise<AgentTeamToolApprovalDecisionResponse>;
	rejectAgentTeamToolApproval?: (
		sessionId: string,
		requestId: string,
		request?: Omit<AgentTeamToolApprovalDecisionRequest, "approved">,
	) => Promise<AgentTeamToolApprovalDecisionResponse>;
	mergeAgentTeamSession?: (
		sessionId: string,
		request: { accepted_tasks?: string[]; rejected_tasks?: string[] },
	) => Promise<AgentTeamSessionView | AgentTeamMergeBundle>;
}
