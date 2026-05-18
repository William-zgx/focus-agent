export type FocusAgentNoteStatus = "active" | "archived";
export type FocusAgentTaskStatus = "todo" | "in_progress" | "completed" | "archived";
export type FocusAgentProductivitySourceKind = "chat" | "agent_team" | "merge_review" | "task_output" | "artifact" | "manual" | string;

export interface FocusAgentNote {
  note_id: string;
  user_id: string;
  title: string;
  body: string;
  tags: string[];
  status: FocusAgentNoteStatus;
  source_thread_id?: string | null;
  source_artifact_id?: string | null;
  source_kind?: FocusAgentProductivitySourceKind | null;
  source_id?: string | null;
  source_url?: string | null;
  pinned_context?: string | null;
  captured_from?: string | null;
  is_archived: boolean;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  archived_at?: string | null;
}

export interface FocusAgentTask {
  task_id: string;
  user_id: string;
  title: string;
  description: string;
  status: FocusAgentTaskStatus;
  due_at?: string | null;
  priority?: number | null;
  source_thread_id?: string | null;
  source_note_id?: string | null;
  source_kind?: FocusAgentProductivitySourceKind | null;
  source_id?: string | null;
  source_url?: string | null;
  pinned_context?: string | null;
  captured_from?: string | null;
  assignee_user_id?: string | null;
  tags: string[];
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
  archived_at?: string | null;
}

export interface FocusAgentTaskEvent {
  event_id: string;
  task_id: string;
  user_id: string;
  kind: "created" | "updated" | "completed" | "archived";
  data: Record<string, unknown>;
  created_at: string;
}

export interface FocusAgentCreateNoteRequest {
  title: string;
  body?: string;
  tags?: string[];
  source_thread_id?: string | null;
  source_artifact_id?: string | null;
  source_kind?: FocusAgentProductivitySourceKind | null;
  source_id?: string | null;
  source_url?: string | null;
  pinned_context?: string | null;
  captured_from?: string | null;
  metadata?: Record<string, unknown> | null;
}

export interface FocusAgentUpdateNoteRequest {
  title?: string | null;
  body?: string | null;
  tags?: string[] | null;
  status?: FocusAgentNoteStatus | null;
  source_thread_id?: string | null;
  source_artifact_id?: string | null;
  source_kind?: FocusAgentProductivitySourceKind | null;
  source_id?: string | null;
  source_url?: string | null;
  pinned_context?: string | null;
  captured_from?: string | null;
  is_archived?: boolean | null;
  metadata?: Record<string, unknown> | null;
}

export interface FocusAgentListNotesRequest {
  q?: string | null;
  tag?: string[] | null;
  source_kind?: FocusAgentProductivitySourceKind | null;
  include_archived?: boolean;
  limit?: number;
  offset?: number;
}

export interface FocusAgentNoteResponse {
  note: FocusAgentNote;
}

export interface FocusAgentNoteListResponse {
  items: FocusAgentNote[];
  count: number;
}

export interface FocusAgentCreateTaskRequest {
  title: string;
  description?: string;
  due_at?: string | null;
  priority?: number | null;
  source_thread_id?: string | null;
  source_note_id?: string | null;
  source_kind?: FocusAgentProductivitySourceKind | null;
  source_id?: string | null;
  source_url?: string | null;
  pinned_context?: string | null;
  captured_from?: string | null;
  assignee_user_id?: string | null;
  tags?: string[];
  metadata?: Record<string, unknown> | null;
}

export interface FocusAgentUpdateTaskRequest {
  title?: string | null;
  description?: string | null;
  status?: FocusAgentTaskStatus | null;
  due_at?: string | null;
  priority?: number | null;
  source_thread_id?: string | null;
  source_note_id?: string | null;
  source_kind?: FocusAgentProductivitySourceKind | null;
  source_id?: string | null;
  source_url?: string | null;
  pinned_context?: string | null;
  captured_from?: string | null;
  assignee_user_id?: string | null;
  tags?: string[] | null;
  metadata?: Record<string, unknown> | null;
}

export interface FocusAgentListTasksRequest {
  status?: FocusAgentTaskStatus | null;
  source_kind?: FocusAgentProductivitySourceKind | null;
  include_archived?: boolean;
  limit?: number;
  offset?: number;
}

export interface FocusAgentTaskResponse {
  task: FocusAgentTask;
}

export interface FocusAgentTaskListResponse {
  items: FocusAgentTask[];
  count: number;
}

export interface FocusAgentTaskEventListResponse {
  items: FocusAgentTaskEvent[];
  count: number;
}

export interface FocusAgentCaptureNoteRequest {
  title?: string | null;
  body: string;
  tags?: string[];
  source_kind?: FocusAgentProductivitySourceKind | null;
  source_id?: string | null;
  source_url?: string | null;
  source_thread_id?: string | null;
  source_artifact_id?: string | null;
  pinned_context?: string | null;
  captured_from?: string | null;
  metadata?: Record<string, unknown> | null;
}

export interface FocusAgentCaptureTaskRequest {
  title: string;
  description?: string;
  due_at?: string | null;
  priority?: number | null;
  tags?: string[];
  source_kind?: FocusAgentProductivitySourceKind | null;
  source_id?: string | null;
  source_url?: string | null;
  source_thread_id?: string | null;
  source_note_id?: string | null;
  pinned_context?: string | null;
  captured_from?: string | null;
  assignee_user_id?: string | null;
  metadata?: Record<string, unknown> | null;
}
