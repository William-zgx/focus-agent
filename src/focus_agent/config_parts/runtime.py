from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

from .catalogs import ModelCatalogConfig, ToolCatalogConfig
from .common import _env_bool, _split_csv


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
        "temperature": float(env.get("TEMPERATURE", str(defaults.temperature))),
        "database_uri": env.get("DATABASE_URI") or None,
        "langgraph_api_url": env.get("LANGGRAPH_API_URL") or None,
        "branch_db_path": env.get("BRANCH_DB_PATH", defaults.branch_db_path),
        "artifact_dir": env.get("ARTIFACT_DIR", defaults.artifact_dir),
        "local_checkpoint_path": env.get("LOCAL_CHECKPOINT_PATH") or None,
        "local_store_path": env.get("LOCAL_STORE_PATH") or None,
        "branch_max_depth": int(env.get("BRANCH_MAX_DEPTH", str(defaults.branch_max_depth))),
        "tool_max_parallel_workers": int(
            env.get("TOOL_MAX_PARALLEL_WORKERS", str(defaults.tool_max_parallel_workers))
        ),
        "background_worker_max_concurrency": int(
            env.get(
                "BACKGROUND_WORKER_MAX_CONCURRENCY",
                str(defaults.background_worker_max_concurrency),
            )
        ),
        "background_queue_max_size": int(
            env.get("BACKGROUND_QUEUE_MAX_SIZE", str(defaults.background_queue_max_size))
        ),
        "background_job_backend": env.get(
            "BACKGROUND_JOB_BACKEND", defaults.background_job_backend
        ),
        "background_job_execution": env.get(
            "BACKGROUND_JOB_EXECUTION",
            defaults.background_job_execution,
        ),
        "background_job_claim_ttl_seconds": float(
            env.get(
                "BACKGROUND_JOB_CLAIM_TTL_SECONDS",
                str(defaults.background_job_claim_ttl_seconds),
            )
        ),
        "background_job_retry_base_delay_seconds": float(
            env.get(
                "BACKGROUND_JOB_RETRY_BASE_DELAY_SECONDS",
                str(defaults.background_job_retry_base_delay_seconds),
            )
        ),
        "background_job_retry_max_delay_seconds": float(
            env.get(
                "BACKGROUND_JOB_RETRY_MAX_DELAY_SECONDS",
                str(defaults.background_job_retry_max_delay_seconds),
            )
        ),
        "background_job_old_pending_seconds": float(
            env.get(
                "BACKGROUND_JOB_OLD_PENDING_SECONDS",
                str(defaults.background_job_old_pending_seconds),
            )
        ),
        "runtime_thread_lock_ttl_seconds": float(
            env.get(
                "RUNTIME_THREAD_LOCK_TTL_SECONDS",
                str(defaults.runtime_thread_lock_ttl_seconds),
            )
        ),
        "runtime_thread_lock_heartbeat_seconds": float(
            env.get(
                "RUNTIME_THREAD_LOCK_HEARTBEAT_SECONDS",
                str(defaults.runtime_thread_lock_heartbeat_seconds),
            )
        ),
        "postgres_pool_enabled": str(
            env.get("POSTGRES_POOL_ENABLED", str(defaults.postgres_pool_enabled))
        )
        .strip()
        .lower()
        not in {"0", "false", "no", "off"},
        "postgres_pool_min_size": int(
            env.get("POSTGRES_POOL_MIN_SIZE", str(defaults.postgres_pool_min_size))
        ),
        "postgres_pool_max_size": int(
            env.get("POSTGRES_POOL_MAX_SIZE", str(defaults.postgres_pool_max_size))
        ),
        "postgres_slow_query_threshold_ms": float(
            env.get(
                "POSTGRES_SLOW_QUERY_THRESHOLD_MS", str(defaults.postgres_slow_query_threshold_ms)
            )
        ),
        "skill_directories": (
            _split_csv(env.get("FOCUS_AGENT_SKILLS_DIRS"))
            if env.get("FOCUS_AGENT_SKILLS_DIRS") is not None
            else defaults.skill_directories
        ),
        "skill_semantic_match_enabled": _env_bool(
            env,
            "SKILL_SEMANTIC_MATCH_ENABLED",
            default=defaults.skill_semantic_match_enabled,
        ),
        "skill_semantic_match_threshold": float(
            env.get(
                "SKILL_SEMANTIC_MATCH_THRESHOLD",
                str(defaults.skill_semantic_match_threshold),
            )
        ),
        "skill_selection_event_log_enabled": _env_bool(
            env,
            "SKILL_SELECTION_EVENT_LOG_ENABLED",
            default=defaults.skill_selection_event_log_enabled,
        ),
        "workspace_root": env.get("WORKSPACE_ROOT", defaults.workspace_root),
        "agent_team_merge_apply_enabled": _env_bool(
            env,
            "AGENT_TEAM_MERGE_APPLY_ENABLED",
            default=defaults.agent_team_merge_apply_enabled,
        ),
        "agent_team_merge_review_max_diff_bytes": int(
            env.get(
                "AGENT_TEAM_MERGE_REVIEW_MAX_DIFF_BYTES",
                str(defaults.agent_team_merge_review_max_diff_bytes),
            )
        ),
        "feedback_capture_enabled": _env_bool(
            env,
            "FEEDBACK_CAPTURE_ENABLED",
            default=defaults.feedback_capture_enabled,
        ),
        "context_memory_evidence_enabled": _env_bool(
            env,
            "CONTEXT_MEMORY_EVIDENCE_ENABLED",
            default=defaults.context_memory_evidence_enabled,
        ),
    }
