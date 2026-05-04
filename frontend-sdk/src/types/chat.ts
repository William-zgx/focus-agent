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
}
