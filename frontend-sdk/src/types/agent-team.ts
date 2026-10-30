export type FocusAgentAgentTeamSessionStatus =
  | "planning"
  | "running"
  | "awaiting_review"
  | "merging"
  | "completed"
  | "failed"
  | "cancelled";

export type FocusAgentAgentTeamTaskRole =
  | "planner"
  | "architect"
  | "backend_executor"
  | "frontend_executor"
  | "test_engineer"
  | "reviewer"
  | "verifier"
  | "writer";

export type FocusAgentAgentTeamTaskStatus =
  | "pending"
  | "queued"
  | "running"
  | "blocked"
  | "done"
  | "failed"
  | "cancelled";

export type FocusAgentAgentTeamArtifactKind =
  | "plan"
  | "patch_summary"
  | "test_report"
  | "review_report"
  | "risk_report"
  | "handoff"
  | "merge_summary";

export type FocusAgentAgentTeamMergeNextAction =
  | "merge"
  | "request_changes"
  | "split_followup"
  | "discard";

export type FocusAgentAgentTeamFinalAnswerStatus = "ready" | "placeholder" | "blocked" | "error" | string;

export type FocusAgentAgentTeamMergeReviewStatus =
  | "draft"
  | "ready"
  | "approved"
  | "applied"
  | "rejected"
  | "conflict"
  | "error"
  | string;

export type FocusAgentAgentTeamPlanGranularity = "auto" | "coarse" | "balanced" | "detailed";

export type FocusAgentAgentTeamPlanFocus =
  | "auto"
  | "research"
  | "debugging"
  | "review"
  | "implementation"
  | "verification"
  | "writing";

export interface FocusAgentAgentTeamPlanningMetadata {
  source?: string | null;
  rationale?: string | null;
  planner_model_id?: string | null;
  generated_at?: string | null;
  plan_hash?: string | null;
  error?: string | null;
  task_count: number;
}

export interface FocusAgentAgentTeamRunMetadata {
  execution_mode?: string | null;
  scheduled_task_ids?: string[];
  running_task_ids?: string[];
  max_parallel_runs?: number;
}

export interface FocusAgentAgentTeamReadinessCapabilities {
  task_run_queries: boolean;
  evidence_queries: boolean;
  revision_commands: boolean;
}

export interface FocusAgentAgentTeamReadiness {
  status: "ready" | "disabled" | "degraded";
  ready: boolean;
  enabled: boolean;
  service_available: boolean;
  capabilities: FocusAgentAgentTeamReadinessCapabilities;
  detail?: string | null;
}

export interface FocusAgentAgentTeamTaskRun {
  task_run_id: string;
  task_id: string;
  session_id: string;
  status: FocusAgentAgentTeamTaskStatus;
  attempt: number;
  started_at?: string | null;
  finished_at?: string | null;
  last_error?: string | null;
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
  updated_at?: string | null;
}

export interface FocusAgentAgentTeamTaskRunResponse {
  task_run: FocusAgentAgentTeamTaskRun;
}

export interface FocusAgentAgentTeamTaskRunListResponse {
  items: FocusAgentAgentTeamTaskRun[];
  count: number;
}

export interface FocusAgentAgentTeamEvidence {
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

export interface FocusAgentAgentTeamEvidenceListResponse {
  items: FocusAgentAgentTeamEvidence[];
  count: number;
}

export type FocusAgentAgentTeamRevisionCommand =
  | "create"
  | "activate"
  | "supersede"
  | "cancel"
  | "resume";

export interface FocusAgentAgentTeamRevisionCommandRequest {
  command: FocusAgentAgentTeamRevisionCommand;
  revision_id?: string | null;
  parent_revision_id?: string | null;
  task_ids?: string[];
  metadata?: Record<string, unknown>;
}

export interface FocusAgentAgentTeamRevisionCommandResponse {
  command: FocusAgentAgentTeamRevisionCommand;
  session_id: string;
  outcome: Record<string, unknown>;
}

export interface FocusAgentAgentTeamSession {
  session_id: string;
  root_thread_id: string;
  user_id: string;
  title: string;
  goal: string;
  status: FocusAgentAgentTeamSessionStatus;
  created_at: string;
  updated_at: string;
  latest_merge_bundle?: FocusAgentAgentTeamMergeBundle | null;
  merge_decision?: Record<string, unknown> | null;
  planning_source?: string | null;
  planning_rationale?: string | null;
  planner_model_id?: string | null;
  plan_generated_at?: string | null;
  plan_hash?: string | null;
  planning_error?: string | null;
  planning?: FocusAgentAgentTeamPlanningMetadata | null;
  skill_plan?: Record<string, unknown>;
}

export interface FocusAgentAgentTeamTask {
  task_id: string;
  session_id: string;
  branch_id?: string | null;
  child_thread_id?: string | null;
  role: FocusAgentAgentTeamTaskRole;
  goal: string;
  title?: string | null;
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
  acceptance_criteria?: string[];
  context_refs?: Record<string, unknown>[];
  active_skill_ids?: string[];
  skill_resolution_events?: Record<string, unknown>[];
  scope: string[];
  dependencies: string[];
  status: FocusAgentAgentTeamTaskStatus;
  run_status?: string | null;
  output_artifact_ids: string[];
  agent_run_id?: string | null;
  delegated_task_id?: string | null;
  artifact_ids: string[];
  execution_status?: string | null;
  changed_files: string[];
  test_evidence?: string[];
  verification_summary?: string | null;
  risk_notes: string[];
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

export interface FocusAgentAgentTeamTaskOutput {
  output_id?: string;
  task_id: string;
  task_run_id?: string | null;
  kind?: FocusAgentAgentTeamArtifactKind | null;
  artifact_id?: string | null;
  /** @deprecated Never sent by the backend; read `kind`. */
  artifact_kind?: FocusAgentAgentTeamArtifactKind | null;
  /** @deprecated Never sent by the backend; read `summary`. */
  content?: string | null;
  summary?: string | null;
  changed_files: string[];
  test_evidence?: string[];
  /** @deprecated Never sent by the backend; read `test_evidence`. */
  verification_summary?: string | null;
  risk_notes: string[];
  workspace_id?: string | null;
  workspace_branch?: string | null;
  workspace_path?: string | null;
  base_commit?: string | null;
  diff_summary?: string | null;
  workspace_status?: string | null;
  execution_profile?: string | null;
  execution_class?: string | null;
  evidence_level?: string;
  evidence_verdict?: string;
  evidence_summary?: string | null;
  sandbox_id?: string | null;
  revision_id?: string | null;
  row_version?: number;
  cancel_epoch?: number;
  deliverable?: boolean;
  metadata?: Record<string, unknown> | null;
  created_at?: string | null;
}

export interface FocusAgentAgentTeamArtifact {
  artifact_id: string;
  task_id?: string | null;
  kind?: FocusAgentAgentTeamArtifactKind | string | null;
  title?: string | null;
  summary?: string | null;
  payload?: Record<string, unknown> | null;
  /** @deprecated Never sent by the backend; read `summary` / `payload`. */
  content?: string | null;
  /** @deprecated Never sent by the backend; read `payload`. */
  metadata?: Record<string, unknown> | null;
  created_at?: string | null;
}

export interface FocusAgentAgentTeamMergeBundle {
  session_id: string;
  summary: string;
  final_answer?: string | null;
  final_answer_status?: FocusAgentAgentTeamFinalAnswerStatus | null;
  final_answer_warnings?: string[];
  source_output_ids?: string[];
  accepted_tasks: string[];
  rejected_tasks: string[];
  key_findings: string[];
  changed_files: string[];
  test_evidence: string[];
  execution_evidence: Record<string, unknown>[];
  open_questions: string[];
  risk_items: string[];
  recommended_next_action: FocusAgentAgentTeamMergeNextAction;
}

export interface FocusAgentAgentTeamMergeReviewTask {
  task_id: string;
  title?: string | null;
  role?: string | null;
  selected: boolean;
  adoptable?: boolean;
  changed_files: string[];
  diff_summary?: string | null;
  test_evidence: string[];
  risk_items: string[];
  workspace_status?: string | null;
  workspace_branch?: string | null;
  workspace_path?: string | null;
  output_status?: FocusAgentAgentTeamFinalAnswerStatus | null;
  placeholder?: boolean;
  fake?: boolean;
}

export interface FocusAgentAgentTeamMergeReview {
  review_id: string;
  session_id: string;
  user_id?: string;
  status: FocusAgentAgentTeamMergeReviewStatus;
  title?: string | null;
  summary?: string | null;
  selected_task_ids: string[];
  /** Tasks explicitly excluded from adoption (backend field name). */
  excluded_task_ids?: string[];
  /** @deprecated Never sent by the backend; read `excluded_task_ids`. */
  rejected_task_ids?: string[];
  /** Per-task adoption summary computed by the backend during preview. */
  task_summaries?: FocusAgentAgentTeamMergeReviewTaskSummary[];
  /** @deprecated Never sent by the backend; read `task_summaries`. */
  task_reviews?: FocusAgentAgentTeamMergeReviewTask[];
  changed_files: string[];
  diffstat?: string | null;
  /** @deprecated Never sent by the backend; read `summary` / `diffstat`. */
  diff_summary?: string | null;
  test_evidence: string[];
  risk_items: string[];
  conflict_files: string[];
  error_message?: string | null;
  apply_target_path?: string | null;
  /** @deprecated Never sent by the backend; read `apply_target_path`. */
  apply_target?: string | null;
  /** @deprecated Never sent by the backend; read `error_message`. */
  last_error?: string | null;
  created_at: string;
  updated_at: string;
  previewed_at?: string | null;
  /** @deprecated Never sent by the backend. */
  approved_at?: string | null;
  applied_at?: string | null;
  rejected_at?: string | null;
  metadata?: Record<string, unknown> | null;
}

export interface FocusAgentAgentTeamMergeReviewTaskSummary {
  task_id: string;
  title?: string | null;
  role?: string | null;
  status?: string | null;
  workspace_path?: string | null;
  workspace_status?: string | null;
  changed_files?: string[];
  test_evidence?: string[];
  risk_items?: string[];
  adoptable?: boolean;
  non_adoptable_reason?: string | null;
  output_ids?: string[];
}

export interface FocusAgentAgentTeamMergeReviewEvent {
  event_id: string;
  review_id: string;
  session_id: string;
  event_type?: string;
  status?: FocusAgentAgentTeamMergeReviewStatus | null;
  message?: string | null;
  metadata?: Record<string, unknown>;
  /** @deprecated Never sent by the backend; read `event_type`. */
  kind?: string;
  /** @deprecated Never sent by the backend; read `metadata`. */
  data?: Record<string, unknown>;
  created_at: string;
}

export interface FocusAgentAgentTeamMergeReviewListResponse {
  items: FocusAgentAgentTeamMergeReview[];
  reviews?: FocusAgentAgentTeamMergeReview[];
  latest?: FocusAgentAgentTeamMergeReview | null;
  count: number;
}

export interface FocusAgentAgentTeamCreateMergeReviewRequest {
  selected_task_ids?: string[];
  excluded_task_ids?: string[];
  /** @deprecated Alias of `excluded_task_ids`; the client sends it as `excluded_task_ids`. */
  rejected_task_ids?: string[];
  title?: string | null;
  metadata?: Record<string, unknown> | null;
}

export interface FocusAgentAgentTeamUpdateMergeReviewRequest {
  status?: FocusAgentAgentTeamMergeReviewStatus | null;
  selected_task_ids?: string[] | null;
  excluded_task_ids?: string[] | null;
  /** @deprecated Alias of `excluded_task_ids`; the client sends it as `excluded_task_ids`. */
  rejected_task_ids?: string[] | null;
  title?: string | null;
  metadata?: Record<string, unknown> | null;
}

/**
 * @deprecated The preview endpoint takes no body; it previews the review's saved
 * selection. Update the review first to change the selection.
 */
export interface FocusAgentAgentTeamMergeReviewPreviewRequest {
  selected_task_ids?: string[];
  rejected_task_ids?: string[];
  max_diff_bytes?: number | null;
}

export interface FocusAgentAgentTeamMergeReviewApplyRequest {
  apply_target_path?: string | null;
  /** @deprecated Alias of `apply_target_path`. */
  apply_target?: string | null;
  /** @deprecated Ignored by the backend; apply uses the review's saved selection. */
  selected_task_ids?: string[];
  /** @deprecated Ignored by the backend; apply uses the review's saved selection. */
  rejected_task_ids?: string[];
  /** @deprecated Ignored by the backend. */
  rationale?: string | null;
}

export interface FocusAgentAgentTeamMergeReviewRejectRequest {
  rationale?: string | null;
  /** @deprecated Alias of `rationale`; the client sends it as `rationale`. */
  reason?: string | null;
}

export interface FocusAgentAgentTeamMergeReviewResponse {
  review: FocusAgentAgentTeamMergeReview;
  events?: FocusAgentAgentTeamMergeReviewEvent[];
}

export interface FocusAgentAgentTeamMergeReviewPreviewResponse {
  review: FocusAgentAgentTeamMergeReview;
  events?: FocusAgentAgentTeamMergeReviewEvent[];
  /** Derived by the client: false when the previewed review is in `conflict` or `error`. */
  applicable: boolean;
  /** Derived by the client from `review.metadata.patch`. */
  diff?: string | null;
  diffstat?: string | null;
  conflict_files: string[];
  /** Derived by the client from `review.error_message`. */
  warnings: string[];
}

export type FocusAgentAgentTeamToolApprovalStatus =
  | "pending"
  | "approved"
  | "rejected"
  | "auto_approved"
  | "timed_out"
  | string;

export interface FocusAgentAgentTeamToolApproval {
  request_id: string;
  session_id: string;
  agent_id: string;
  tool_name: string;
  tool_args: Record<string, unknown>;
  risk_level: string;
  status: FocusAgentAgentTeamToolApprovalStatus;
  submitted_at: number;
  timeout_at: number;
  decided_by?: string | null;
}

export interface FocusAgentAgentTeamToolApprovalListResponse {
  approvals?: FocusAgentAgentTeamToolApproval[];
  items: FocusAgentAgentTeamToolApproval[];
  count: number;
}

export interface FocusAgentAgentTeamToolApprovalDecisionRequest {
  approved: boolean;
  reason?: string | null;
}

export interface FocusAgentAgentTeamToolApprovalDecisionResponse {
  approval: FocusAgentAgentTeamToolApproval;
}

export interface FocusAgentAgentTeamCreateSessionRequest {
  root_thread_id?: string | null;
  goal: string;
  title?: string | null;
}

export interface FocusAgentAgentTeamListSessionsRequest {
  root_thread_id?: string;
  status?: FocusAgentAgentTeamSessionStatus | FocusAgentAgentTeamSessionStatus[];
  limit?: number;
  offset?: number;
}

export interface FocusAgentAgentTeamSessionListResponse {
  items: FocusAgentAgentTeamSession[];
  count: number;
}

export interface FocusAgentAgentTeamDispatchRequest {
  create_branches?: boolean;
  auto_fork_branch?: boolean | null;
  parent_thread_id?: string | null;
}

export interface FocusAgentAgentTeamDispatchResponse {
  session: FocusAgentAgentTeamSession;
  tasks: FocusAgentAgentTeamTask[];
  items: FocusAgentAgentTeamTask[];
  outputs?: FocusAgentAgentTeamTaskOutput[];
  artifacts?: FocusAgentAgentTeamArtifact[];
  merge_bundle?: FocusAgentAgentTeamMergeBundle | null;
  planning?: FocusAgentAgentTeamPlanningMetadata | null;
  count: number;
}

export interface FocusAgentAgentTeamSessionView {
  session: FocusAgentAgentTeamSession;
  tasks: FocusAgentAgentTeamTask[];
  outputs?: FocusAgentAgentTeamTaskOutput[];
  artifacts: FocusAgentAgentTeamArtifact[];
  merge_bundle?: FocusAgentAgentTeamMergeBundle | null;
  planning?: FocusAgentAgentTeamPlanningMetadata | null;
  run?: FocusAgentAgentTeamRunMetadata | null;
  pending_tool_approvals?: FocusAgentAgentTeamToolApproval[];
}

export interface FocusAgentAgentTeamSessionRunRequest {
  create_branches?: boolean;
  auto_fork_branch?: boolean | null;
  parent_thread_id?: string | null;
  task_ids?: string[];
  run_ready_only?: boolean | null;
  metadata?: Record<string, unknown> | null;
}

export interface FocusAgentAgentTeamTaskRunRequest {
  create_branch?: boolean;
  auto_fork_branch?: boolean | null;
  parent_thread_id?: string | null;
  metadata?: Record<string, unknown> | null;
}

export interface FocusAgentAgentTeamSessionRunResponse {
  session: FocusAgentAgentTeamSession;
  tasks: FocusAgentAgentTeamTask[];
  items: FocusAgentAgentTeamTask[];
  outputs: FocusAgentAgentTeamTaskOutput[];
  artifacts: FocusAgentAgentTeamArtifact[];
  merge_bundle?: FocusAgentAgentTeamMergeBundle | null;
  planning?: FocusAgentAgentTeamPlanningMetadata | null;
  run?: FocusAgentAgentTeamRunMetadata | null;
  pending_tool_approvals?: FocusAgentAgentTeamToolApproval[];
  count: number;
}

export interface FocusAgentAgentTeamPlanSessionRequest extends FocusAgentAgentTeamSessionRunRequest {
  replace_existing?: boolean;
  granularity?: FocusAgentAgentTeamPlanGranularity;
  focus?: FocusAgentAgentTeamPlanFocus;
  max_tasks?: number;
}

export type FocusAgentAgentTeamPlanSessionResponse = FocusAgentAgentTeamSessionRunResponse;
export type FocusAgentAgentTeamRunSessionRequest = FocusAgentAgentTeamSessionRunRequest;
export type FocusAgentAgentTeamRunSessionResponse = FocusAgentAgentTeamSessionRunResponse;

export interface FocusAgentAgentTeamRunTaskResponse {
  task?: FocusAgentAgentTeamTask | null;
  session?: FocusAgentAgentTeamSession | null;
  tasks: FocusAgentAgentTeamTask[];
  items: FocusAgentAgentTeamTask[];
  outputs: FocusAgentAgentTeamTaskOutput[];
  artifacts: FocusAgentAgentTeamArtifact[];
  merge_bundle?: FocusAgentAgentTeamMergeBundle | null;
  planning?: FocusAgentAgentTeamPlanningMetadata | null;
  run?: FocusAgentAgentTeamRunMetadata | null;
  pending_tool_approvals?: FocusAgentAgentTeamToolApproval[];
  count: number;
}

export interface FocusAgentAgentTeamCreateTaskRequest {
  role: FocusAgentAgentTeamTaskRole;
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
  acceptance_criteria?: string[];
  context_refs?: Record<string, unknown>[];
  active_skill_ids?: string[];
  skill_resolution_events?: Record<string, unknown>[];
  scope?: string[];
  dependencies?: string[];
  branch_id?: string | null;
  child_thread_id?: string | null;
  auto_fork_branch?: boolean | null;
  create_branch?: boolean | null;
  branch_name?: string | null;
}

export interface FocusAgentAgentTeamListTasksRequest {
  status?: FocusAgentAgentTeamTaskStatus | FocusAgentAgentTeamTaskStatus[];
  role?: FocusAgentAgentTeamTaskRole | FocusAgentAgentTeamTaskRole[];
  limit?: number;
  offset?: number;
}

export interface FocusAgentAgentTeamTaskListResponse {
  items: FocusAgentAgentTeamTask[];
  count: number;
}

export interface FocusAgentAgentTeamUpdateTaskRequest {
  status?: FocusAgentAgentTeamTaskStatus;
  goal?: string;
  input_contract?: Record<string, unknown> | null;
  output_contract?: Record<string, unknown> | null;
  evidence_required?: string[];
  capability_requirements?: string[];
  risk_level?: string | null;
  write_scope?: string[];
  resource_claims?: string[];
  replan_policy?: Record<string, unknown> | null;
  acceptance_criteria?: string[];
  context_refs?: Record<string, unknown>[];
  active_skill_ids?: string[];
  skill_resolution_events?: Record<string, unknown>[];
  scope?: string[];
  dependencies?: string[];
  branch_id?: string | null;
  child_thread_id?: string | null;
  output_artifact_ids?: string[];
  run_status?: string | null;
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
}

export interface FocusAgentAgentTeamRecordTaskOutputRequest {
  artifact_id?: string | null;
  artifact_kind?: FocusAgentAgentTeamArtifactKind | null;
  content?: string | null;
  summary?: string | null;
  changed_files?: string[];
  test_evidence?: string[];
  verification_summary?: string | null;
  workspace_id?: string | null;
  workspace_branch?: string | null;
  workspace_path?: string | null;
  base_commit?: string | null;
  diff_summary?: string | null;
  workspace_status?: string | null;
  risk_notes?: string[];
  metadata?: Record<string, unknown> | null;
}

export interface FocusAgentAgentTeamRecordTaskOutputResponse {
  task?: FocusAgentAgentTeamTask | null;
  output?: FocusAgentAgentTeamTaskOutput | null;
}

export interface FocusAgentAgentTeamPrepareMergeBundleRequest {
  accepted_tasks?: string[];
  rejected_tasks?: string[];
}

export interface FocusAgentAgentTeamMergeDecisionRequest {
  accepted_tasks: string[];
  rejected_tasks?: string[];
  apply?: boolean;
  rationale?: string | null;
  summary_override?: string | null;
  next_action?: FocusAgentAgentTeamMergeNextAction | null;
}

export interface FocusAgentAgentTeamMergeDecision {
  decision_id: string;
  session_id: string;
  approved?: boolean;
  action?: FocusAgentAgentTeamMergeNextAction;
  rationale?: string | null;
  accepted_tasks?: string[];
  rejected_tasks?: string[];
  created_at: string;
}

export interface FocusAgentAgentTeamMergeDecisionResponse {
  decision: FocusAgentAgentTeamMergeDecision;
  session: FocusAgentAgentTeamSession;
  merge_bundle: FocusAgentAgentTeamMergeBundle;
  applied: boolean;
}
