export type FocusAgentMemoryNamespace = string | string[];

export interface FocusAgentMemoryRecord {
  memory_id: string;
  kind?: string | null;
  scope?: string | null;
  visibility?: string | null;
  status?: string | null;
  namespace?: string[] | null;
  content?: string | null;
  summary?: string | null;
  tags?: string[];
  evidence_refs?: string[];
  source_thread_id?: string | null;
  source_branch_id?: string | null;
  root_thread_id?: string | null;
  user_id?: string | null;
  confidence?: number | null;
  importance?: number | null;
  promoted_to_main?: boolean | null;
  fingerprint?: string | null;
  semantic_key?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  deleted_at?: string | null;
  payload_redacted?: boolean;
  [key: string]: unknown;
}

export interface FocusAgentMemoryListRequest {
  namespace?: FocusAgentMemoryNamespace | null;
  kind?: string | null;
  scope?: string | null;
  visibility?: string | null;
  status?: string | null;
  user_id?: string | null;
  root_thread_id?: string | null;
  source_thread_id?: string | null;
  source_branch_id?: string | null;
  limit?: number;
  offset?: number;
}

export interface FocusAgentMemoryListResponse {
  items: FocusAgentMemoryRecord[];
  count: number;
  filters: Record<string, unknown>;
  limit: number;
  offset: number;
  backend?: string;
  available?: boolean;
  error?: string | null;
}

export interface FocusAgentMemoryDetailResponse {
  item: FocusAgentMemoryRecord | null;
  backend?: string;
  available?: boolean;
  error?: string | null;
}

export interface FocusAgentMemoryAuditEvent {
  event_id: string;
  action?: string | null;
  decision?: string | null;
  memory_id?: string | null;
  candidate_id?: string | null;
  actor?: string | null;
  reason?: string | null;
  namespace?: string[] | null;
  user_id?: string | null;
  root_thread_id?: string | null;
  source_thread_id?: string | null;
  source_branch_id?: string | null;
  request_id?: string | null;
  data?: Record<string, unknown>;
  created_at?: string | null;
  [key: string]: unknown;
}

export interface FocusAgentMemoryAuditEventListRequest {
  memory_id?: string | null;
  limit?: number;
}

export interface FocusAgentMemoryAuditEventListResponse {
  items: FocusAgentMemoryAuditEvent[];
  count: number;
  filters: Record<string, unknown>;
  limit: number;
  backend?: string;
  available?: boolean;
  error?: string | null;
}

export interface FocusAgentForgetMemoryRequest {
  namespace?: FocusAgentMemoryNamespace | null;
  reason?: string | null;
}

export interface FocusAgentForgetMemoryResponse {
  memory_id: string;
  forgotten: boolean;
  status?: string | null;
  tombstone_id?: string | null;
  audit_id?: string | null;
  decision?: Record<string, unknown>;
}

export interface FocusAgentMemoryCandidate {
  candidate_id: string;
  status?: string | null;
  agent_id?: string | null;
  task_id?: string | null;
  branch_id?: string | null;
  root_thread_id?: string | null;
  user_id?: string | null;
  evidence_refs?: string[];
  record?: Record<string, unknown>;
  reason?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  [key: string]: unknown;
}

export interface FocusAgentMemoryCandidateListRequest {
  status?: string | null;
  root_thread_id?: string | null;
  limit?: number;
}

export interface FocusAgentMemoryCandidateListResponse {
  items: FocusAgentMemoryCandidate[];
  count: number;
  filters: Record<string, unknown>;
  limit: number;
  backend?: string;
  available?: boolean;
  error?: string | null;
}
