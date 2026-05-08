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

export type FocusAgentAgentTeamPlanGranularity = "auto" | "coarse" | "balanced" | "detailed";

export type FocusAgentAgentTeamPlanFocus = "auto" | "research" | "implementation" | "verification";

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
  plan_source?: string | null;
  acceptance_criteria?: string[];
  context_refs?: Record<string, unknown>[];
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
  verification_summary?: string | null;
  risk_notes: string[];
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
  kind?: FocusAgentAgentTeamArtifactKind | null;
  artifact_id?: string | null;
  artifact_kind?: FocusAgentAgentTeamArtifactKind | null;
  content?: string | null;
  summary?: string | null;
  changed_files: string[];
  test_evidence?: string[];
  verification_summary?: string | null;
  risk_notes: string[];
  metadata?: Record<string, unknown> | null;
  created_at?: string | null;
}

export interface FocusAgentAgentTeamArtifact {
  artifact_id: string;
  task_id?: string | null;
  kind?: FocusAgentAgentTeamArtifactKind | string | null;
  title?: string | null;
  summary?: string | null;
  content?: string | null;
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

export interface FocusAgentAgentTeamCreateSessionRequest {
  root_thread_id: string;
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
}

export interface FocusAgentAgentTeamSessionRunRequest {
  create_branches?: boolean;
  auto_fork_branch?: boolean | null;
  parent_thread_id?: string | null;
  task_ids?: string[];
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
  count: number;
}

export interface FocusAgentAgentTeamCreateTaskRequest {
  role: FocusAgentAgentTeamTaskRole;
  goal: string;
  acceptance_criteria?: string[];
  context_refs?: Record<string, unknown>[];
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
  acceptance_criteria?: string[];
  context_refs?: Record<string, unknown>[];
  scope?: string[];
  dependencies?: string[];
  branch_id?: string | null;
  child_thread_id?: string | null;
  output_artifact_ids?: string[];
  run_status?: string | null;
  changed_files?: string[];
  verification_summary?: string | null;
  risk_notes?: string[];
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
  verification_summary?: string | null;
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

export interface FocusAgentAgentTeamMergeDecisionResponse {
  session: FocusAgentAgentTeamSession;
  merge_bundle: FocusAgentAgentTeamMergeBundle;
  applied: boolean;
}
