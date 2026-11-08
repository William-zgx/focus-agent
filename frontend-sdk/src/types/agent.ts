export interface FocusAgentModelOption {
  id: string;
  provider: string;
  provider_label: string;
  provider_logo_slug?: string | null;
  provider_logo_letter?: string | null;
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

export interface FocusAgentSkillSelectRequest {
  message: string;
  skill_hints?: string[];
  semantic_enabled?: boolean | null;
  semantic_threshold?: number | null;
}

export interface FocusAgentSkillSemanticCandidate {
  skill_id: string;
  score: number;
  matched_terms: string[];
  auto_activate: boolean;
  rationale: string;
}

export interface FocusAgentSkillSelectionResponse {
  skill_ids: string[];
  stripped_message: string;
  prompt_mode?: string | null;
  selection_source: string;
  matched_triggers: string[];
  semantic_candidates: FocusAgentSkillSemanticCandidate[];
  confidence: number;
  rationale: string;
  semantic_enabled: boolean;
  semantic_threshold: number;
}

export interface FocusAgentSkillSelectionEvent {
  selection_id: string;
  created_at: string;
  message?: string | null;
  selection_source: string;
  explicit_hints: string[];
  matched_triggers: string[];
  semantic_candidates: FocusAgentSkillSemanticCandidate[];
  activated_skills: string[];
  confidence: number;
  rationale?: string | null;
  user_override?: string | null;
  feedback?: string | null;
}

export interface FocusAgentSkillSelectionListResponse {
  items: FocusAgentSkillSelectionEvent[];
  count: number;
}

export interface FocusAgentSkillCatalogItem {
  skill_id: string;
  description: string;
  when_to_use: string[];
  triggers: string[];
  aliases: string[];
  localized_triggers: string[];
  domains: string[];
  intents: string[];
  primary_tools: string[];
  recommended_tools: string[];
  path?: string | null;
  prompt_mode?: string | null;
  preference?: FocusAgentSkillPreferenceResponse | null;
}

export interface FocusAgentSkillCatalogResponse {
  items: FocusAgentSkillCatalogItem[];
  count: number;
}

export interface FocusAgentSkillSelectionFeedbackRequest {
  feedback: "useful" | "misfire" | "ignored" | string;
  note?: string | null;
}

export interface FocusAgentSkillPreferenceRequest {
  state: string;
  metadata?: Record<string, unknown>;
}

export interface FocusAgentSkillPreferenceResponse {
  preference_id: string;
  user_id: string;
  skill_id: string;
  state: string;
  metadata: Record<string, unknown>;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface FocusAgentCapability {
  name: string;
  description: string;
  toolset?: string | null;
  allowed_roles: string[];
  risk_level: string;
  side_effect: boolean;
  parallel_safe: boolean;
  cacheable: boolean;
  requires_network: boolean;
  requires_workspace_write: boolean;
  requires_approval: boolean;
  sensitive_args?: string[];
  redaction_policy?: string;
  provider_id?: string | null;
}

export interface FocusAgentCapabilityListResponse {
  items: FocusAgentCapability[];
  count: number;
}

export interface FocusAgentToolset {
  name: string;
  description: string;
  tools: string[];
  count: number;
  provider_ids: string[];
  risk_levels: string[];
  allowed_roles: string[];
  intent_policies: string[];
  requires_network: boolean;
  requires_workspace_write: boolean;
  side_effect: boolean;
  requires_approval: boolean;
}

export interface FocusAgentToolsetListResponse {
  items: FocusAgentToolset[];
  count: number;
}

export interface FocusAgentMemoryCuratorPolicyResponse {
  enabled: boolean;
  auto_promote_on_merge: boolean;
  branch_local_only_until_merge: boolean;
  conflict_strategy: string;
}

export interface FocusAgentMemoryCuratorEvaluateRequest {
  root_thread_id: string;
  branch_id: string;
  branch_name?: string;
  branch_role?: string;
  branch_status?: string;
  child_thread_id?: string | null;
  parent_thread_id?: string | null;
  findings?: Array<Record<string, unknown>>;
  user_id?: string | null;
  auto_promote?: boolean | null;
}

export interface FocusAgentMemoryCuratorEvaluateResponse {
  decision: Record<string, unknown>;
}

export interface FocusAgentMemoryCuratorDecisionListResponse {
  items: Array<Record<string, unknown>>;
  count: number;
  trajectory_available: boolean;
  trajectory_error?: string | null;
}

export interface FocusAgentContextPolicyResponse {
  enabled: boolean;
  artifactize_long_observations: boolean;
  role_views_enabled: boolean;
  tokenizer_mode: string;
  artifact_min_chars: number;
  default_off_legacy_safe: boolean;
}

export interface FocusAgentContextPreviewRequest {
  state?: Record<string, unknown>;
  prompt_mode?: string;
  role?: string;
  assembled_context?: string | null;
  materialize_artifacts?: boolean;
}

export interface FocusAgentContextPreviewResponse {
  decision: Record<string, unknown>;
}

export interface FocusAgentContextDecisionListResponse {
  items: Array<Record<string, unknown>>;
  count: number;
  trajectory_available: boolean;
  trajectory_error?: string | null;
}

export interface FocusAgentContextArtifactListResponse {
  items: Array<Record<string, unknown>>;
  count: number;
  trajectory_available: boolean;
  trajectory_error?: string | null;
}

export interface FocusAgentContextMemoryEvidence {
  evidence_id: string;
  thread_id?: string | null;
  turn_id?: string | null;
  created_at: string;
  selected_memories: Array<Record<string, unknown>>;
  excluded_memories: Array<Record<string, unknown>>;
  compaction_summary?: string | null;
  drift_report?: Record<string, unknown> | null;
  artifact_refs: Array<Record<string, unknown>>;
  token_counting_backend?: string | null;
  tokenizer_id?: string | null;
  estimated?: boolean | null;
  risk_flags: string[];
  metadata?: Record<string, unknown> | null;
}

export interface FocusAgentContextMemoryEvidenceListResponse {
  items: FocusAgentContextMemoryEvidence[];
  count: number;
}

export interface FocusAgentContextExplainRequest {
  thread_id?: string | null;
  turn_id?: string | null;
  message?: string | null;
}

export interface FocusAgentContextExplainResponse {
  evidence: FocusAgentContextMemoryEvidence;
  answerability?: Record<string, unknown> | null;
}

export interface FocusAgentMemoryUsageResponse {
  memory_id: string;
  usage: Array<Record<string, unknown>>;
  count: number;
}

export interface FocusAgentFeedbackTrendResponse {
  negative_feedback_count: number;
  merge_review_apply_success_rate?: number | null;
  merge_review_conflict_rate?: number | null;
  skill_low_confidence_rate?: number | null;
  skill_override_rate?: number | null;
  context_high_drift_count: number;
  notes_tasks_capture_count: number;
  top_failing_trajectory_samples: Array<Record<string, unknown>>;
  generated_at?: string | null;
}

export interface FocusAgentArtifactListResponse {
  items: Array<Record<string, unknown>>;
  count: number;
  trajectory_available: boolean;
  trajectory_error?: string | null;
}
