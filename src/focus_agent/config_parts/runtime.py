from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

from .catalogs import ModelCatalogConfig, ToolCatalogConfig
from .common import _split_csv
from .env import env_bool, env_float, env_int


def load_runtime_config(
    env: MutableMapping[str, str],
    defaults: Any,
    *,
    model_catalog: ModelCatalogConfig,
    tool_catalog: ToolCatalogConfig,
) -> dict[str, object]:
    return {
        "model": env.get("MODEL") or model_catalog.default_model or defaults.model,
        "helper_model": env.get("HELPER_MODEL") or model_catalog.helper_model or None,
        "model_choices": model_catalog.model_choices or defaults.model_choices,
        "model_catalog": model_catalog,
        "tool_catalog": tool_catalog,
        "web_search": tool_catalog.web_search,
        "resolved_env": dict(env),
        "temperature": env_float(env, "TEMPERATURE", defaults.temperature),
        "model_request_timeout_seconds": max(
            1.0,
            env_float(env, "MODEL_REQUEST_TIMEOUT_SECONDS", defaults.model_request_timeout_seconds),
        ),
        "database_uri": env.get("DATABASE_URI") or None,
        "langgraph_api_url": env.get("LANGGRAPH_API_URL") or None,
        "branch_db_path": env.get("BRANCH_DB_PATH", defaults.branch_db_path),
        "artifact_dir": env.get("ARTIFACT_DIR", defaults.artifact_dir),
        "local_checkpoint_path": env.get("LOCAL_CHECKPOINT_PATH") or None,
        "local_store_path": env.get("LOCAL_STORE_PATH") or None,
        "branch_max_depth": env_int(env, "BRANCH_MAX_DEPTH", defaults.branch_max_depth),
        "skills_enabled": env_bool(
            env,
            "FOCUS_AGENT_SKILLS_ENABLED",
            default=env_bool(env, "SKILLS_ENABLED", default=defaults.skills_enabled),
        ),
        "tool_max_parallel_workers": env_int(
            env, "TOOL_MAX_PARALLEL_WORKERS", defaults.tool_max_parallel_workers
        ),
        "tool_pool_isolated": env_bool(
            env,
            "FOCUS_AGENT_TOOL_POOL_ISOLATED",
            default=defaults.tool_pool_isolated,
        ),
        "background_worker_max_concurrency": env_int(
            env, "BACKGROUND_WORKER_MAX_CONCURRENCY", defaults.background_worker_max_concurrency
        ),
        "background_queue_max_size": env_int(
            env, "BACKGROUND_QUEUE_MAX_SIZE", defaults.background_queue_max_size
        ),
        "background_job_backend": env.get(
            "BACKGROUND_JOB_BACKEND", defaults.background_job_backend
        ),
        "background_job_execution": env.get(
            "BACKGROUND_JOB_EXECUTION",
            defaults.background_job_execution,
        ),
        "background_job_claim_ttl_seconds": env_float(
            env, "BACKGROUND_JOB_CLAIM_TTL_SECONDS", defaults.background_job_claim_ttl_seconds
        ),
        "background_job_retry_base_delay_seconds": env_float(
            env,
            "BACKGROUND_JOB_RETRY_BASE_DELAY_SECONDS",
            defaults.background_job_retry_base_delay_seconds,
        ),
        "background_job_retry_max_delay_seconds": env_float(
            env,
            "BACKGROUND_JOB_RETRY_MAX_DELAY_SECONDS",
            defaults.background_job_retry_max_delay_seconds,
        ),
        "background_job_old_pending_seconds": env_float(
            env, "BACKGROUND_JOB_OLD_PENDING_SECONDS", defaults.background_job_old_pending_seconds
        ),
        "runtime_thread_lock_ttl_seconds": env_float(
            env, "RUNTIME_THREAD_LOCK_TTL_SECONDS", defaults.runtime_thread_lock_ttl_seconds
        ),
        "runtime_thread_lock_heartbeat_seconds": env_float(
            env,
            "RUNTIME_THREAD_LOCK_HEARTBEAT_SECONDS",
            defaults.runtime_thread_lock_heartbeat_seconds,
        ),
        "db_pool_enabled": env_bool(
            env,
            "FOCUS_AGENT_DB_POOL_ENABLED",
            default=env_bool(
                env,
                "POSTGRES_POOL_ENABLED",
                default=defaults.postgres_pool_enabled,
            ),
        ),
        "db_pool_max": env_int(
            env,
            "FOCUS_AGENT_DB_POOL_MAX",
            env_int(
                env,
                "DB_POOL_MAX",
                env_int(env, "POSTGRES_POOL_MAX_SIZE", defaults.db_pool_max),
            ),
        ),
        "postgres_pool_enabled": env_bool(
            env,
            "FOCUS_AGENT_DB_POOL_ENABLED",
            default=env_bool(
                env,
                "POSTGRES_POOL_ENABLED",
                default=defaults.postgres_pool_enabled,
            ),
        ),
        "postgres_pool_min_size": env_int(
            env, "POSTGRES_POOL_MIN_SIZE", defaults.postgres_pool_min_size
        ),
        "postgres_pool_max_size": env_int(
            env,
            "FOCUS_AGENT_DB_POOL_MAX",
            env_int(
                env,
                "DB_POOL_MAX",
                env_int(env, "POSTGRES_POOL_MAX_SIZE", defaults.postgres_pool_max_size),
            ),
        ),
        "postgres_slow_query_threshold_ms": env_float(
            env, "POSTGRES_SLOW_QUERY_THRESHOLD_MS", defaults.postgres_slow_query_threshold_ms
        ),
        "skill_directories": (
            _split_csv(env.get("FOCUS_AGENT_SKILLS_DIRS"))
            if env.get("FOCUS_AGENT_SKILLS_DIRS") is not None
            else defaults.skill_directories
        ),
        "skill_disabled_ids": (
            _split_csv(env.get("FOCUS_AGENT_SKILL_DISABLED_IDS") or env.get("SKILL_DISABLED_IDS"))
            if (
                env.get("FOCUS_AGENT_SKILL_DISABLED_IDS") is not None
                or env.get("SKILL_DISABLED_IDS") is not None
            )
            else defaults.skill_disabled_ids
        ),
        "skill_semantic_match_enabled": env_bool(
            env,
            "SKILL_SEMANTIC_MATCH_ENABLED",
            default=defaults.skill_semantic_match_enabled,
        ),
        "skill_semantic_match_threshold": env_float(
            env, "SKILL_SEMANTIC_MATCH_THRESHOLD", defaults.skill_semantic_match_threshold
        ),
        "skill_selection_event_log_enabled": env_bool(
            env,
            "SKILL_SELECTION_EVENT_LOG_ENABLED",
            default=defaults.skill_selection_event_log_enabled,
        ),
        "workspace_root": env.get("WORKSPACE_ROOT", defaults.workspace_root),
        "multi_agent_v2_enabled": env_bool(
            env,
            "MULTI_AGENT_V2_ENABLED",
            default=defaults.multi_agent_v2_enabled,
        ),
        "multi_agent_async_approval_enabled": env_bool(
            env,
            "MULTI_AGENT_ASYNC_APPROVAL_ENABLED",
            default=defaults.multi_agent_async_approval_enabled,
        ),
        "multi_agent_message_ttl_seconds": env_float(
            env, "MULTI_AGENT_MESSAGE_TTL_SECONDS", defaults.multi_agent_message_ttl_seconds
        ),
        "multi_agent_approval_timeout_seconds": env_float(
            env,
            "MULTI_AGENT_APPROVAL_TIMEOUT_SECONDS",
            defaults.multi_agent_approval_timeout_seconds,
        ),
        "feedback_capture_enabled": env_bool(
            env,
            "FEEDBACK_CAPTURE_ENABLED",
            default=defaults.feedback_capture_enabled,
        ),
        "context_memory_evidence_enabled": env_bool(
            env,
            "CONTEXT_MEMORY_EVIDENCE_ENABLED",
            default=defaults.context_memory_evidence_enabled,
        ),
    }
