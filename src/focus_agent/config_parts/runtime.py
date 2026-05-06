from __future__ import annotations

from typing import Any, MutableMapping

from .catalogs import ModelCatalogConfig, ToolCatalogConfig
from .common import _split_csv


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
        "background_job_backend": env.get("BACKGROUND_JOB_BACKEND", defaults.background_job_backend),
        "background_job_claim_ttl_seconds": float(
            env.get(
                "BACKGROUND_JOB_CLAIM_TTL_SECONDS",
                str(defaults.background_job_claim_ttl_seconds),
            )
        ),
        "runtime_thread_lock_ttl_seconds": float(
            env.get(
                "RUNTIME_THREAD_LOCK_TTL_SECONDS",
                str(defaults.runtime_thread_lock_ttl_seconds),
            )
        ),
        "skill_directories": (
            _split_csv(env.get("FOCUS_AGENT_SKILLS_DIRS"))
            if env.get("FOCUS_AGENT_SKILLS_DIRS") is not None
            else defaults.skill_directories
        ),
        "workspace_root": env.get("WORKSPACE_ROOT", defaults.workspace_root),
    }
