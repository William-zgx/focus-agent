export interface FocusAgentTokenUsageSummary {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
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
