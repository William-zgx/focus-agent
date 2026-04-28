export interface FocusAgentCreateConversationRequest {
  title?: string | null;
}

export interface FocusAgentUpdateConversationRequest {
  title: string;
}

export interface FocusAgentConversationSummary {
  root_thread_id: string;
  title: string;
  is_archived: boolean;
  archived_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  token_usage?: FocusAgentTokenUsageSummary;
}

export interface FocusAgentConversationListResponse {
  conversations: FocusAgentConversationSummary[];
}

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

export interface ThreadContextPreviewRequest {
  draft_message?: string | null;
}

export interface ThreadContextPreviewResponse {
  context_usage: ContextUsageResponse;
}

export type ThreadContextCompactTrigger =
  | "manual"
  | "auto_pre_send"
  | "auto_post_turn";

export interface ThreadContextCompactRequest {
  trigger?: ThreadContextCompactTrigger;
}
