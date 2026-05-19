export interface FocusAgentTrajectoryFilters {
  turn_id?: string;
  turn_ids?: string[];
  request_id?: string;
  trace_id?: string;
  thread_id?: string;
  root_thread_id?: string;
  parent_thread_id?: string;
  branch_id?: string;
  branch_role?: string | string[];
  status?: string | string[];
  scene?: string | string[];
  kind?: string | string[];
  tool?: string | string[];
  model?: string | string[];
  selected_model?: string | string[];
  started_after?: string;
  started_before?: string;
  since?: string;
  until?: string;
  fallback_used?: boolean;
  cache_hit?: boolean;
  has_error?: boolean;
  min_latency_ms?: number;
  max_latency_ms?: number;
  min_tool_calls?: number;
  max_tool_calls?: number;
  newest_first?: boolean;
}

export interface FocusAgentTrajectoryListRequest extends FocusAgentTrajectoryFilters {
  limit?: number;
  offset?: number;
}

export interface FocusAgentTrajectoryStatsRequest extends FocusAgentTrajectoryFilters {}

export interface FocusAgentTrajectoryMetrics {
  latency_ms?: number;
  tool_calls?: number;
  llm_calls?: number;
  input_tokens?: number;
  output_tokens?: number;
  total_tokens?: number;
  cache_hits?: number;
  fallback_uses?: number;
  parallel_tool_calls?: number;
  [key: string]: unknown;
}

export interface FocusAgentTrajectoryStep {
  tool: string;
  args: Record<string, unknown>;
  observation: string;
  duration_ms: number;
  error?: string | null;
  cache_hit: boolean;
  fallback_used: boolean;
  fallback_group?: string | null;
  parallel_batch_size?: number | null;
  runtime?: Record<string, unknown>;
  observation_truncated?: boolean;
}

export interface FocusAgentTrajectoryTurnSummary {
  id: string;
  schema_version: number;
  kind: string;
  status: string;
  thread_id: string;
  root_thread_id: string;
  request_id?: string | null;
  trace_id?: string | null;
  root_span_id?: string | null;
  environment?: string | null;
  deployment?: string | null;
  app_version?: string | null;
  parent_thread_id?: string | null;
  branch_id?: string | null;
  branch_role?: string | null;
  scene: string;
  turn_index?: number | null;
  task_brief?: string | null;
  user_message?: string | null;
  answer?: string | null;
  selected_model?: string | null;
  selected_thinking_mode?: string | null;
  error?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  created_at?: string | null;
  metrics: FocusAgentTrajectoryMetrics;
  plan_meta: Record<string, unknown>;
  latency_ms: number;
  tool_calls: number;
  llm_calls: number;
  cache_hits: number;
  fallback_uses: number;
}

export interface FocusAgentTrajectoryTurnDetail extends FocusAgentTrajectoryTurnSummary {
  user_id_hash: string;
  plan?: unknown;
  reflection?: unknown;
  trajectory: FocusAgentTrajectoryStep[];
}

export interface FocusAgentTrajectoryListResponse {
  items: FocusAgentTrajectoryTurnSummary[];
  count: number;
  filters: FocusAgentTrajectoryFilters;
  limit: number;
  offset: number;
}

export interface FocusAgentTrajectoryDetailResponse {
  item: FocusAgentTrajectoryTurnDetail | null;
}

export interface FocusAgentTrajectoryStatsRow {
  key?: string;
  turn_count?: number;
  step_count?: number;
  avg_latency_ms?: number;
  avg_duration_ms?: number;
  cache_hit_steps?: number;
  fallback_steps?: number;
  succeeded_count?: number;
  non_succeeded_count?: number;
  total_tool_calls?: number;
  total_llm_calls?: number;
  total_cache_hits?: number;
  total_fallback_uses?: number;
  max_latency_ms?: number;
  [key: string]: unknown;
}

export interface FocusAgentTrajectoryStats {
  overview: FocusAgentTrajectoryStatsRow;
  by_status: FocusAgentTrajectoryStatsRow[];
  by_scene: FocusAgentTrajectoryStatsRow[];
  by_branch_role: FocusAgentTrajectoryStatsRow[];
  by_model: FocusAgentTrajectoryStatsRow[];
  by_day: FocusAgentTrajectoryStatsRow[];
  by_tool: FocusAgentTrajectoryStatsRow[];
}

export interface FocusAgentTrajectoryStatsResponse {
  filters: FocusAgentTrajectoryFilters;
  stats: FocusAgentTrajectoryStats;
}

export interface FocusAgentRuntimeComponentStatus {
  name: string;
  ready: boolean;
  detail?: string | null;
}

export interface FocusAgentRuntimeReadiness {
  status: string;
  ready: boolean;
  app_version?: string | null;
  environment?: string | null;
  deployment?: string | null;
  active_connections: number;
  checks: FocusAgentRuntimeComponentStatus[];
}

export interface FocusAgentObservabilityOverviewRequest extends FocusAgentTrajectoryStatsRequest {
  newest_first?: boolean;
}

export interface FocusAgentObservabilityOverviewResponse {
  generated_at: string;
  filters: FocusAgentTrajectoryFilters;
  runtime: FocusAgentRuntimeReadiness;
  trajectory_available: boolean;
  trajectory_error?: string | null;
  stats: FocusAgentTrajectoryStats;
}

export interface FocusAgentTrajectoryReplayRequest {
  model?: string | null;
  case_id_prefix?: string;
  copy_tool_trajectory?: boolean;
  copy_answer_substring?: boolean;
  answer_substring_chars?: number;
}

export interface FocusAgentTrajectoryPromotionRequest {
  case_id_prefix?: string;
  copy_tool_trajectory?: boolean;
  copy_answer_substring?: boolean;
  answer_substring_chars?: number;
}

export interface FocusAgentTrajectoryBatchPromotionPreviewRequest
  extends FocusAgentTrajectoryListRequest,
    FocusAgentTrajectoryPromotionRequest {}

export interface FocusAgentTrajectoryBatchReplayCompareRequest
  extends Omit<FocusAgentTrajectoryListRequest, "model">,
    FocusAgentTrajectoryReplayRequest {}

export interface FocusAgentTrajectoryEvalCase {
  id: string;
  input: Record<string, unknown>;
  expected: Record<string, unknown>;
  tags: string[];
  scene: string;
  skill_hints?: string[];
  setup?: Array<Record<string, string>>;
  judge?: Record<string, unknown>;
  origin?: Record<string, unknown> | null;
}

export interface FocusAgentTrajectoryReplayCase extends FocusAgentTrajectoryEvalCase {}

export interface FocusAgentTrajectoryReplayResult {
  case_id: string;
  passed: boolean;
  answer: string;
  verdicts: Array<Record<string, unknown>>;
  trajectory: Array<Record<string, unknown>>;
  metrics: Record<string, unknown>;
  error?: string | null;
  tags: string[];
}

export interface FocusAgentTrajectoryReplayComparison {
  case_id: string;
  trajectory_id?: string | null;
  source_status?: string | null;
  source_failed: boolean;
  replay_passed: boolean;
  replay_error?: string | null;
  source_tools: string[];
  replay_tools: string[];
  tool_path_changed: boolean;
  source_tool_calls: number;
  replay_tool_calls: number;
  source_latency_ms: number;
  replay_latency_ms: number;
  source_fallback_uses: number;
  replay_fallback_uses: number;
  source_cache_hits: number;
  replay_cache_hits: number;
  source_answer_preview: string;
  replay_answer_preview: string;
}

export interface FocusAgentTrajectoryReplayResponse {
  source_turn_id: string;
  model_used: string;
  replay_case: FocusAgentTrajectoryReplayCase;
  replay_case_jsonl: string;
  replay_result: FocusAgentTrajectoryReplayResult;
  comparison: FocusAgentTrajectoryReplayComparison;
}

export interface FocusAgentTrajectoryPromotionResponse {
  source_turn_id: string;
  case_id: string;
  dataset_record: FocusAgentTrajectoryEvalCase;
  jsonl: string;
}

export interface FocusAgentTrajectoryBatchPromotionPreviewResponse {
  items: FocusAgentTrajectoryPromotionResponse[];
  count: number;
  filters: FocusAgentTrajectoryFilters;
  limit: number;
  offset: number;
  jsonl: string;
}

export interface FocusAgentTrajectoryBatchReplayCompareResponse {
  results: FocusAgentTrajectoryReplayResponse[];
  summary: {
    total: number;
    passed: number;
    failed: number;
    source_failed: number;
    tool_path_changed: number;
  };
  filters: FocusAgentTrajectoryFilters;
  limit: number;
  offset: number;
}
