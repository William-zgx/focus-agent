export interface FocusAgentTokenUsageSummary {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
}

export interface FocusAgentRuntimeOutcome extends Record<string, unknown> {
  status?: string;
  tool_call_id?: string;
  tool_name?: string;
  turn_id?: string | null;
  human_turn_index?: number | null;
  attempt_index?: number;
  max_attempts?: number;
  retryable?: boolean;
  contract_satisfied?: boolean;
  fallback_used?: boolean;
  fallback_group?: string | null;
  degraded_reason?: string | null;
  recovery_of_tool_call_id?: string | null;
  error_category?: string | null;
  error_message?: string | null;
  evidence_role?: string | null;
  policy?: string | null;
  answer_basis?: string | null;
  repair_action_taken?: string | null;
  degradation_reason?: string | null;
  evidence_count?: number | null;
  warnings?: unknown[];
}

export type ContextUsageStatus =
  | "ok"
  | "warm"
  | "hot"
  | "over"
  | "compacting"
  | "error";

export interface ContextUsageResponse {
  used_tokens: number;
  token_limit: number;
  remaining_tokens: number;
  used_ratio: number;
  status: ContextUsageStatus;
  prompt_chars: number;
  prompt_budget_chars: number;
  tokenizer_mode: string;
  last_compacted_at?: string | null;
}
