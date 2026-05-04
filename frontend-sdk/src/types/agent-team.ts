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
}

export interface FocusAgentAgentTeamTask {
  task_id: string;
  session_id: string;
  branch_id?: string | null;
  child_thread_id?: string | null;
  role: FocusAgentAgentTeamTaskRole;
  goal: string;
  scope: string[];
  dependencies: string[];
  status: FocusAgentAgentTeamTaskStatus;
  output_artifact_ids: string[];
  agent_run_id?: string | null;
  delegated_task_id?: string | null;
  artifact_ids: string[];
  execution_status?: string | null;
  changed_files: string[];
  verification_summary?: string | null;
  risk_notes: string[];
}

export interface FocusAgentAgentTeamTaskOutput {
  task_id: string;
  artifact_id?: string | null;
  artifact_kind?: FocusAgentAgentTeamArtifactKind | null;
  content?: string | null;
  summary?: string | null;
  changed_files: string[];
  verification_summary?: string | null;
  risk_notes: string[];
  metadata?: Record<string, unknown> | null;
  created_at?: string | null;
}

export interface FocusAgentAgentTeamMergeBundle {
  session_id: string;
  summary: string;
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
  count: number;
}

export interface FocusAgentAgentTeamCreateTaskRequest {
  role: FocusAgentAgentTeamTaskRole;
  goal: string;
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
  scope?: string[];
  dependencies?: string[];
  branch_id?: string | null;
  child_thread_id?: string | null;
  output_artifact_ids?: string[];
  changed_files?: string[];
  verification_summary?: string | null;
  risk_notes?: string[];
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
