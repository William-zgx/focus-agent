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

export interface AgentTeamSession {
  session_id: string;
  root_thread_id: string;
  user_id?: string;
  title: string;
  goal: string;
  status: AgentTeamSessionStatus;
  created_at?: string;
  updated_at?: string;
}

export interface AgentTeamTask {
  task_id: string;
  session_id: string;
  branch_id?: string | null;
  child_thread_id?: string | null;
  role: AgentTeamRole | string;
  goal: string;
  scope?: string[];
  dependencies?: string[];
  status: AgentTeamTaskStatus | string;
  output_artifact_ids?: string[];
  changed_files?: string[];
  verification_summary?: string | null;
  risk_notes?: string[];
}

export interface AgentTeamArtifact {
  artifact_id: string;
  task_id?: string | null;
  kind?: string | null;
  title?: string | null;
  summary?: string | null;
  created_at?: string;
}

export interface AgentTeamMergeBundle {
  session_id: string;
  summary: string;
  accepted_tasks?: string[];
  rejected_tasks?: string[];
  key_findings?: string[];
  changed_files?: string[];
  test_evidence?: string[];
  open_questions?: string[];
  risk_items?: string[];
  recommended_next_action?: "merge" | "request_changes" | "split_followup" | "discard" | string;
}

export interface AgentTeamSessionView {
  session: AgentTeamSession;
  tasks: AgentTeamTask[];
  artifacts?: AgentTeamArtifact[];
  merge_bundle?: AgentTeamMergeBundle | null;
}

export interface AgentTeamCreateSessionRequest {
  title?: string;
  goal: string;
  root_thread_id: string;
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
  scope?: string[];
  dependencies?: string[];
}

export interface AgentTeamDispatchRequest {
  create_branches?: boolean;
  auto_fork_branch?: boolean | null;
  parent_thread_id?: string | null;
}

export interface AgentTeamClientContract {
  createAgentTeamSession: (request: AgentTeamCreateSessionRequest) => Promise<AgentTeamSession | AgentTeamSessionView>;
  listAgentTeamSessions?: (
    request?: AgentTeamListSessionsRequest,
  ) => Promise<AgentTeamSessionListResponse | { sessions?: AgentTeamSession[]; items?: AgentTeamSession[]; count?: number } | AgentTeamSession[]>;
  getAgentTeamSession: (sessionId: string) => Promise<AgentTeamSession | AgentTeamSessionView>;
  dispatchAgentTeamSession?: (
    sessionId: string,
    request?: AgentTeamDispatchRequest,
  ) => Promise<AgentTeamSessionView | { session: AgentTeamSession; tasks?: AgentTeamTask[]; items?: AgentTeamTask[]; count?: number }>;
  listAgentTeamTasks?: (
    sessionId: string,
    request?: Record<string, unknown>,
  ) => Promise<{ items?: AgentTeamTask[]; count?: number } | AgentTeamTask[]>;
  createAgentTeamTask?: (sessionId: string, request: AgentTeamCreateTaskRequest) => Promise<AgentTeamTask | AgentTeamSessionView>;
  prepareAgentTeamMergeBundle?: (
    sessionId: string,
    request?: Record<string, unknown>,
  ) => Promise<AgentTeamMergeBundle | AgentTeamSessionView>;
  createAgentTeamMergeProposal?: (sessionId: string) => Promise<AgentTeamMergeBundle | AgentTeamSessionView>;
  mergeAgentTeamSession?: (
    sessionId: string,
    request: { accepted_tasks?: string[]; rejected_tasks?: string[] },
  ) => Promise<AgentTeamSessionView | AgentTeamMergeBundle>;
}
