from __future__ import annotations

from typing import NamedTuple

_SENSITIVE_FIELD_NAMES = frozenset(
    {
        "api_key_default",
        "agent_memory_embedding_api_key",
        "auth_jwt_secret",
        "database_uri",
    }
)


class ConfigFieldSpec(NamedTuple):
    key: str
    env_key: str
    label: str
    value_type: str
    description: str
    options: tuple[str, ...] = ()
    requires_restart: bool = True


_POLICY_FIELD_SPECS: tuple[ConfigFieldSpec, ...] = (
    ConfigFieldSpec(
        "agent_deferred_tools_enabled",
        "AGENT_DEFERRED_TOOLS_ENABLED",
        "Deferred tools",
        "boolean",
        "Load rarely used tools on demand through tool_search.",
    ),
    ConfigFieldSpec(
        "multi_agent_v2_enabled",
        "MULTI_AGENT_V2_ENABLED",
        "Multi-agent v2",
        "boolean",
        "Enable the v2 multi-agent coordination surface.",
    ),
    ConfigFieldSpec(
        "multi_agent_async_approval_enabled",
        "MULTI_AGENT_ASYNC_APPROVAL_ENABLED",
        "Async approvals",
        "boolean",
        "Allow multi-agent approval waits to run asynchronously.",
    ),
    ConfigFieldSpec(
        "agent_branch_decision_enabled",
        "AGENT_BRANCH_DECISION_ENABLED",
        "Branch decisions",
        "boolean",
        "Enable evidence-first branch decision recording.",
    ),
    ConfigFieldSpec(
        "agent_branch_decision_mode",
        "AGENT_BRANCH_DECISION_MODE",
        "Branch decision mode",
        "string",
        "Control branch decision behavior.",
        ("shadow", "suggest", "execute"),
    ),
    ConfigFieldSpec(
        "agent_branch_decision_min_confidence",
        "AGENT_BRANCH_DECISION_MIN_CONFIDENCE",
        "Branch min confidence",
        "float",
        "Minimum confidence for branch decisions.",
    ),
    ConfigFieldSpec(
        "agent_branch_decision_split_threshold",
        "AGENT_BRANCH_DECISION_SPLIT_THRESHOLD",
        "Split threshold",
        "float",
        "Confidence threshold for split decisions.",
    ),
    ConfigFieldSpec(
        "agent_branch_decision_conclude_threshold",
        "AGENT_BRANCH_DECISION_CONCLUDE_THRESHOLD",
        "Conclude threshold",
        "float",
        "Confidence threshold for conclude decisions.",
    ),
    ConfigFieldSpec(
        "agent_branch_decision_merge_candidate_threshold",
        "AGENT_BRANCH_DECISION_MERGE_CANDIDATE_THRESHOLD",
        "Merge candidate threshold",
        "float",
        "Confidence threshold for merge-candidate decisions.",
    ),
    ConfigFieldSpec(
        "agent_branch_decision_rate_limit_per_hour",
        "AGENT_BRANCH_DECISION_RATE_LIMIT_PER_HOUR",
        "Branch decision rate limit",
        "integer",
        "Maximum automated branch decisions per hour.",
    ),
    ConfigFieldSpec(
        "agent_branch_recommendation_enabled",
        "AGENT_BRANCH_RECOMMENDATION_ENABLED",
        "Branch recommendations",
        "boolean",
        "Enable pre-turn branch recommendations.",
    ),
    ConfigFieldSpec(
        "agent_branch_recommendation_mode",
        "AGENT_BRANCH_RECOMMENDATION_MODE",
        "Branch recommendation mode",
        "string",
        "Control recommendation behavior: shadow records diagnostics only; suggest may create pending cards.",
        ("shadow", "suggest"),
    ),
    ConfigFieldSpec(
        "agent_branch_recommendation_min_confidence",
        "AGENT_BRANCH_RECOMMENDATION_MIN_CONFIDENCE",
        "Recommendation min confidence",
        "float",
        "Minimum confidence for branch recommendations.",
    ),
    ConfigFieldSpec(
        "agent_branch_recommendation_semantic_enabled",
        "AGENT_BRANCH_RECOMMENDATION_SEMANTIC_ENABLED",
        "Semantic branch recommendations",
        "boolean",
        "Enable semantic topic relation classification for branch recommendations.",
    ),
    ConfigFieldSpec(
        "agent_branch_recommendation_semantic_model",
        "AGENT_BRANCH_RECOMMENDATION_SEMANTIC_MODEL",
        "Semantic recommendation model",
        "string",
        "Model used for semantic topic relation classification; leave empty to use the selected model.",
    ),
    ConfigFieldSpec(
        "agent_branch_recommendation_semantic_fallback_model",
        "AGENT_BRANCH_RECOMMENDATION_SEMANTIC_FALLBACK_MODEL",
        "Semantic recommendation fallback model",
        "string",
        "Optional chat or System One model used when the primary semantic classifier fails.",
    ),
    ConfigFieldSpec(
        "agent_branch_recommendation_semantic_decision_min_confidence",
        "AGENT_BRANCH_RECOMMENDATION_SEMANTIC_DECISION_MIN_CONFIDENCE",
        "Semantic decision min confidence",
        "float",
        "Minimum System One confidence required before its branch action can be used.",
    ),
    ConfigFieldSpec(
        "agent_branch_recommendation_timeout_seconds",
        "AGENT_BRANCH_RECOMMENDATION_TIMEOUT_SECONDS",
        "Recommendation timeout",
        "float",
        "Maximum seconds to wait for a pre-turn branch recommendation before continuing.",
    ),
    ConfigFieldSpec(
        "agent_context_engineering_v2_enabled",
        "AGENT_CONTEXT_ENGINEERING_V2_ENABLED",
        "Context engineering v2",
        "boolean",
        "Enable the v2 context assembly policy surface.",
    ),
    ConfigFieldSpec(
        "agent_context_artifactize_long_observations",
        "AGENT_CONTEXT_ARTIFACTIZE_LONG_OBSERVATIONS",
        "Artifactize long observations",
        "boolean",
        "Move long tool observations into artifacts when assembling context.",
    ),
    ConfigFieldSpec(
        "agent_context_role_views_enabled",
        "AGENT_CONTEXT_ROLE_VIEWS_ENABLED",
        "Context role views",
        "boolean",
        "Assemble role-specific context views.",
    ),
    ConfigFieldSpec(
        "agent_context_tokenizer_mode",
        "AGENT_CONTEXT_TOKENIZER_MODE",
        "Context tokenizer mode",
        "string",
        "Tokenizer strategy for context budgeting.",
        ("tokenizer_first", "chars_fallback"),
    ),
    ConfigFieldSpec(
        "agent_context_artifact_min_chars",
        "AGENT_CONTEXT_ARTIFACT_MIN_CHARS",
        "Artifact min chars",
        "integer",
        "Minimum observation size before artifactization can apply.",
    ),
    ConfigFieldSpec(
        "context_auto_compaction_enabled",
        "CONTEXT_AUTO_COMPACTION_ENABLED",
        "Auto compaction",
        "boolean",
        "Automatically compact context near budget limits.",
    ),
    ConfigFieldSpec(
        "context_auto_compaction_pre_send_ratio",
        "CONTEXT_AUTO_COMPACTION_PRE_SEND_RATIO",
        "Pre-send compaction ratio",
        "float",
        "Context usage ratio that triggers compaction before model calls.",
    ),
    ConfigFieldSpec(
        "context_auto_compaction_post_turn_ratio",
        "CONTEXT_AUTO_COMPACTION_POST_TURN_RATIO",
        "Post-turn compaction ratio",
        "float",
        "Context usage ratio that triggers compaction after a turn.",
    ),
    ConfigFieldSpec(
        "agent_memory_curator_enabled",
        "AGENT_MEMORY_CURATOR_ENABLED",
        "Memory curator",
        "boolean",
        "Enable the memory curator policy.",
    ),
    ConfigFieldSpec(
        "agent_memory_auto_promote_on_merge",
        "AGENT_MEMORY_AUTO_PROMOTE_ON_MERGE",
        "Memory auto promote",
        "boolean",
        "Promote memory candidates after accepted merges.",
    ),
    ConfigFieldSpec(
        "agent_retrieval_backend",
        "AGENT_RETRIEVAL_BACKEND",
        "Retrieval backend",
        "string",
        "Primary retrieval backend for memory and RAG surfaces.",
        ("zvec", "postgres", "auto"),
    ),
    ConfigFieldSpec(
        "agent_retrieval_fallback_backend",
        "AGENT_RETRIEVAL_FALLBACK_BACKEND",
        "Retrieval fallback",
        "string",
        "Fallback retrieval backend when the primary backend is unavailable.",
        ("postgres", "none"),
    ),
    ConfigFieldSpec(
        "agent_zvec_enabled",
        "AGENT_ZVEC_ENABLED",
        "Zvec retrieval",
        "boolean",
        "Enable the embedded Zvec retrieval index.",
    ),
)

_SYSTEM_FIELD_SPECS: tuple[ConfigFieldSpec, ...] = (
    ConfigFieldSpec(
        "temperature",
        "TEMPERATURE",
        "Temperature",
        "float",
        "Default chat model temperature.",
        requires_restart=False,
    ),
    ConfigFieldSpec(
        "rate_limit_enabled",
        "RATE_LIMIT_ENABLED",
        "Rate limiting",
        "boolean",
        "Enable API request rate limits.",
    ),
    ConfigFieldSpec(
        "rate_limit_per_minute",
        "RATE_LIMIT_PER_MINUTE",
        "API rate limit",
        "integer",
        "Default API request limit per minute.",
    ),
    ConfigFieldSpec(
        "rate_limit_chat_per_minute",
        "RATE_LIMIT_CHAT_PER_MINUTE",
        "Chat rate limit",
        "integer",
        "Chat request limit per minute.",
    ),
    ConfigFieldSpec(
        "sse_heartbeat_seconds",
        "SSE_HEARTBEAT_SECONDS",
        "SSE heartbeat",
        "float",
        "Server-sent event heartbeat interval.",
    ),
    ConfigFieldSpec(
        "metrics_cache_ttl_seconds",
        "METRICS_CACHE_TTL_SECONDS",
        "Metrics cache TTL",
        "integer",
        "Seconds before metrics cache entries expire.",
    ),
    ConfigFieldSpec(
        "trajectory_enabled",
        "TRAJECTORY_ENABLED",
        "Trajectory capture",
        "boolean",
        "Enable trajectory recording when storage is available.",
    ),
    ConfigFieldSpec(
        "api_host",
        "API_HOST",
        "API host",
        "string",
        "API bind host. Restart is required.",
    ),
    ConfigFieldSpec(
        "api_port",
        "API_PORT",
        "API port",
        "integer",
        "API bind port. Restart is required.",
    ),
    ConfigFieldSpec(
        "database_uri",
        "DATABASE_URI",
        "Database URI",
        "string",
        "Database connection string. The value is never returned.",
    ),
    ConfigFieldSpec(
        "agent_zvec_data_dir",
        "AGENT_ZVEC_DATA_DIR",
        "Zvec data dir",
        "string",
        "Local directory for embedded Zvec retrieval indexes.",
    ),
    ConfigFieldSpec(
        "auth_jwt_secret",
        "AUTH_JWT_SECRET",
        "JWT secret",
        "string",
        "JWT signing secret. The value is never returned.",
    ),
)


__all__ = [
    "ConfigFieldSpec",
    "_POLICY_FIELD_SPECS",
    "_SENSITIVE_FIELD_NAMES",
    "_SYSTEM_FIELD_SPECS",
]
