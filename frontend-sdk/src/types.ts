export type FocusAgentStreamChannel =
  | "visible_text"
  | "reasoning_tool_call"
  | "tool"
  | "system";

export type FocusAgentEventName =
  | "turn.status"
  | "turn.interrupt"
  | "turn.completed"
  | "turn.failed"
  | "turn.closed"
  | "visible_text.delta"
  | "visible_text.completed"
  | "message.delta"
  | "message.completed"
  | "reasoning.delta"
  | "reasoning.completed"
  | "tool_call.delta"
  | "tool.call.delta"
  | "tool.requested"
  | "tool.start"
  | "tool.delta"
  | "tool.end"
  | "tool.error"
  | "tool.result"
  | "task.update"
  | "task.started"
  | "task.finished"
  | "task.failed"
  | "agent.update"
  | "custom"
  | "status"
  | "stream.chunk";

export interface FocusAgentStreamMetadata {
  langgraph_node?: string;
  langgraph_path?: string | string[];
  langgraph_step?: number;
  tags?: string[];
  run_id?: string;
  model_name?: string;
  ls_provider?: string;
  [key: string]: unknown;
}

export interface FocusAgentBaseEventPayload {
  thread_id?: string;
  namespace?: string[];
  channel?: FocusAgentStreamChannel;
  metadata?: FocusAgentStreamMetadata;
  [key: string]: unknown;
}

export interface VisibleTextDeltaPayload extends FocusAgentBaseEventPayload {
  delta: string;
  channel: "visible_text";
}

export interface VisibleTextCompletedPayload extends FocusAgentBaseEventPayload {
  content: string;
}

export interface ReasoningDeltaPayload extends FocusAgentBaseEventPayload {
  delta: string;
  channel: "reasoning_tool_call";
}

export interface ReasoningCompletedPayload extends FocusAgentBaseEventPayload {
  content: string;
}

export interface ToolCallDeltaPayload extends FocusAgentBaseEventPayload {
  id?: string;
  name?: string;
  args_delta?: string;
  raw?: Record<string, unknown>;
  channel: "reasoning_tool_call";
}

export interface ToolRequestedPayload extends FocusAgentBaseEventPayload {
  node?: string;
  tool_name?: string;
  tool_call_id?: string;
  args?: unknown;
}

export interface ToolLifecyclePayload extends FocusAgentBaseEventPayload {
  event?: string;
  stage?: string;
  tool_name?: string;
  tool_call_id?: string;
  message?: string;
  output?: unknown;
}

export interface TurnStatusPayload extends FocusAgentBaseEventPayload {
  phase: string;
  kind?: string;
}

export interface TurnInterruptPayload extends FocusAgentBaseEventPayload {
  interrupt: unknown;
}

export interface TurnCompletedPayload extends FocusAgentBaseEventPayload {
  thread_state: Record<string, unknown>;
}

export interface TurnFailedPayload extends FocusAgentBaseEventPayload {
  error: string;
  message: string;
}

export interface TurnClosedPayload extends FocusAgentBaseEventPayload {
  status: string;
}

export interface AgentUpdatePayload extends FocusAgentBaseEventPayload {
  data: Record<string, unknown>;
}

export interface TaskPayload extends FocusAgentBaseEventPayload {
  event?: string;
  status?: string;
  value?: unknown;
}

export interface CustomPayload extends FocusAgentBaseEventPayload {
  value?: unknown;
}

export interface StreamChunkPayload extends FocusAgentBaseEventPayload {
  type?: string;
  data?: unknown;
}

export interface FocusAgentEventPayloadMap {
  "turn.status": TurnStatusPayload;
  "turn.interrupt": TurnInterruptPayload;
  "turn.completed": TurnCompletedPayload;
  "turn.failed": TurnFailedPayload;
  "turn.closed": TurnClosedPayload;
  "visible_text.delta": VisibleTextDeltaPayload;
  "visible_text.completed": VisibleTextCompletedPayload;
  "message.delta": VisibleTextDeltaPayload;
  "message.completed": VisibleTextCompletedPayload;
  "reasoning.delta": ReasoningDeltaPayload;
  "reasoning.completed": ReasoningCompletedPayload;
  "tool_call.delta": ToolCallDeltaPayload;
  "tool.call.delta": ToolCallDeltaPayload;
  "tool.requested": ToolRequestedPayload;
  "tool.start": ToolLifecyclePayload;
  "tool.delta": ToolLifecyclePayload;
  "tool.end": ToolLifecyclePayload;
  "tool.error": ToolLifecyclePayload;
  "tool.result": ToolLifecyclePayload;
  "task.update": TaskPayload;
  "task.started": TaskPayload;
  "task.finished": TaskPayload;
  "task.failed": TaskPayload;
  "agent.update": AgentUpdatePayload;
  "custom": CustomPayload;
  "status": CustomPayload;
  "stream.chunk": StreamChunkPayload;
}

export type FocusAgentEventPayload = FocusAgentEventPayloadMap[FocusAgentEventName];

export type FocusAgentEvent<K extends FocusAgentEventName = FocusAgentEventName> =
  K extends FocusAgentEventName
    ? {
        event: K;
        data: FocusAgentEventPayloadMap[K];
        raw?: string;
      }
    : never;

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

export interface FocusAgentDemoTokenRequest {
  user_id?: string;
  tenant_id?: string | null;
  scopes?: string[];
}

export interface FocusAgentTokenResponse {
  access_token: string;
  token_type: "bearer";
  expires_in_seconds: number;
  issuer: string;
}

export interface FocusAgentPrincipalResponse {
  user_id: string;
  tenant_id?: string | null;
  scopes: string[];
  auth_enabled: boolean;
}

export interface FocusAgentModelOption {
  id: string;
  provider: string;
  provider_label: string;
  name: string;
  label: string;
  is_default: boolean;
  supports_thinking: boolean;
  default_thinking_enabled: boolean;
}

export interface FocusAgentModelsResponse {
  default_model: string;
  models: FocusAgentModelOption[];
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

export interface FocusAgentCreateConversationRequest {
  title?: string | null;
}

export interface FocusAgentUpdateConversationRequest {
  title: string;
}

export type BranchRole = "main" | "explore_alternatives" | "deep_dive" | "execute" | "verify" | "writeup";
export type BranchStatus =
  | "active"
  | "paused"
  | "preparing_merge_review"
  | "awaiting_merge_review"
  | "merged"
  | "discarded"
  | "closed";
export type MergeMode = "none" | "summary_only" | "summary_plus_evidence" | "selected_artifacts";
export type MergeTarget = "return_thread" | "root_thread";

export interface BranchMeta {
  branch_id: string;
  root_thread_id: string;
  parent_thread_id: string;
  return_thread_id: string;
  branch_name: string;
  branch_role: BranchRole;
  branch_depth: number;
  branch_status: BranchStatus;
  is_archived?: boolean;
  archived_at?: string | null;
  fork_checkpoint_id?: string | null;
  fork_strategy: string;
}

export interface BranchTreeNode {
  thread_id: string;
  root_thread_id: string;
  parent_thread_id?: string | null;
  branch_id?: string | null;
  branch_name: string;
  branch_role: BranchRole;
  branch_status: BranchStatus;
  is_archived?: boolean;
  archived_at?: string | null;
  branch_depth: number;
  fork_strategy?: string | null;
  token_usage?: FocusAgentTokenUsageSummary;
  children: BranchTreeNode[];
}

export interface BranchTreeResponse {
  root: BranchTreeNode;
  archived_branches: BranchTreeNode[];
}

export interface FocusAgentMergeProposal {
  summary: string;
  key_findings: string[];
  open_questions: string[];
  evidence_refs: string[];
  artifacts: string[];
  recommended_import_mode: MergeMode;
}

export interface FocusAgentMergeProposalOverrides {
  summary?: string | null;
  key_findings?: string[] | null;
  open_questions?: string[] | null;
  evidence_refs?: string[] | null;
  artifacts?: string[] | null;
  recommended_import_mode?: MergeMode | null;
}

export interface FocusAgentImportedConclusion {
  branch_id: string;
  branch_name: string;
  mode: MergeMode;
  summary: string;
  key_findings: string[];
  evidence_refs: string[];
  artifacts: string[];
  rationale?: string | null;
}

export interface FocusAgentBranchRecord {
  branch_id: string;
  root_thread_id: string;
  parent_thread_id: string;
  child_thread_id: string;
  return_thread_id: string;
  owner_user_id: string;
  branch_name: string;
  branch_role: BranchRole;
  branch_depth: number;
  branch_status: BranchStatus;
  is_archived: boolean;
  archived_at?: string | null;
  fork_checkpoint_id?: string | null;
  fork_strategy: string;
  merge_proposal?: FocusAgentMergeProposal | null;
  merge_decision?: Record<string, unknown> | null;
}

export interface ThreadStateResponse {
  thread_id: string;
  root_thread_id: string;
  assistant_message?: string | null;
  rolling_summary: string;
  selected_model: string;
  selected_thinking_mode: string;
  branch_meta?: BranchMeta | null;
  merge_proposal?: FocusAgentMergeProposal | null;
  merge_decision?: Record<string, unknown> | null;
  merge_queue: FocusAgentImportedConclusion[];
  active_skill_ids: string[];
  messages: Array<Record<string, unknown>>;
  interrupts: unknown[];
  trace: Record<string, unknown>;
}

export interface FocusAgentForkBranchRequest {
  parent_thread_id: string;
  branch_name?: string;
  name_source?: string;
  branch_role?: BranchRole;
  fork_checkpoint_id?: string;
  language?: "en" | "zh";
}

export interface FocusAgentRenameBranchRequest {
  branch_name: string;
}

export interface FocusAgentApplyMergeDecisionRequest {
  approved?: boolean;
  mode?: MergeMode;
  target?: MergeTarget;
  rationale?: string | null;
  selected_artifacts?: string[];
  proposal_overrides?: FocusAgentMergeProposalOverrides | null;
}

export interface FocusAgentApplyMergeDecisionResponse {
  imported?: FocusAgentImportedConclusion | null;
}

export type FocusAgentToolCallEvent =
  | FocusAgentEvent<"tool_call.delta">
  | FocusAgentEvent<"tool.call.delta">;

export type FocusAgentToolEvent =
  | FocusAgentEvent<"tool.requested">
  | FocusAgentEvent<"tool.start">
  | FocusAgentEvent<"tool.delta">
  | FocusAgentEvent<"tool.end">
  | FocusAgentEvent<"tool.error">
  | FocusAgentEvent<"tool.result">;

export interface FocusAgentStreamHandlers {
  onEvent?: (event: FocusAgentEvent) => void;
  onVisibleTextDelta?: (event: FocusAgentEvent<"visible_text.delta">) => void;
  onReasoningDelta?: (event: FocusAgentEvent<"reasoning.delta">) => void;
  onToolCallDelta?: (event: FocusAgentToolCallEvent) => void;
  onToolEvent?: (event: FocusAgentToolEvent) => void;
  onCompleted?: (event: FocusAgentEvent<"turn.completed">) => void;
  onFailed?: (event: FocusAgentEvent<"turn.failed">) => void;
}

export interface FocusAgentStreamState {
  visibleText: string;
  reasoningText: string;
  toolCalls: FocusAgentToolCallEvent[];
  toolEvents: FocusAgentToolEvent[];
  latestTurnState?: Record<string, unknown>;
  isClosed: boolean;
  failed?: TurnFailedPayload;
}
