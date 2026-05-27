export interface FocusAgentTurnRequest {
  thread_id: string;
  message: string;
  model?: string;
  thinking_mode?: string;
  skill_hints?: string[];
}

export interface FocusAgentResumeRequest {
  thread_id: string;
  resume: unknown;
  metadata?: Record<string, unknown>;
  on_disconnect?: "cancel" | "continue" | "rollback";
  multitask_strategy?: "reject" | "interrupt" | "rollback" | "enqueue";
}

export interface FocusAgentHarnessRunRequest {
  message?: string;
  input?: Record<string, unknown>;
  model?: string;
  thinking_mode?: string;
  metadata?: Record<string, unknown>;
  skill_hints?: string[];
  on_disconnect?: "cancel" | "continue" | "rollback";
  multitask_strategy?: "reject" | "interrupt" | "rollback" | "enqueue";
}

export interface FocusAgentHarnessRunRecord {
  run_id: string;
  thread_id?: string;
  assistant_id?: string | null;
  status?: string;
  created_at?: string;
  updated_at?: string;
  started_at?: string | null;
  finished_at?: string | null;
  error?: string | null;
  metadata?: Record<string, unknown>;
  kwargs?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface FocusAgentHarnessRunResponse {
  run: FocusAgentHarnessRunRecord;
  thread_state?: Record<string, unknown> | null;
}

export interface FocusAgentThreadHarnessRunsCancelResponse {
  thread_id: string;
  cancelled_run_ids: string[];
  cancelled_count: number;
}

export interface FocusAgentHarnessRunCancelRequest {
  action?: "interrupt" | "rollback";
}

export interface FocusAgentHarnessResumeRequest {
  resume: unknown;
  metadata?: Record<string, unknown>;
  on_disconnect?: "cancel" | "continue" | "rollback";
  multitask_strategy?: "reject" | "interrupt" | "rollback" | "enqueue";
}
