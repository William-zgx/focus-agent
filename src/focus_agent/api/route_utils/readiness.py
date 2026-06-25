from __future__ import annotations

from typing import Any

from focus_agent.config import Settings
from focus_agent.core.repo_call import has_repo_method, safe_repo_call
from focus_agent.runtime.lifecycle import is_shutting_down

from ..contracts import RuntimeComponentStatusResponse, RuntimeReadinessResponse


def _trajectory_expected(settings: Settings | Any) -> bool:
    enabled = getattr(settings, "trajectory_enabled", None)
    database_uri = getattr(settings, "database_uri", None)
    if enabled is None:
        return bool(database_uri)
    return bool(enabled and database_uri)


def _memory_embedding_configured(settings: Settings | Any) -> bool:
    enabled = bool(getattr(settings, "agent_memory_embedding_enabled", False))
    backend = str(getattr(settings, "agent_memory_embedding_backend", "") or "").strip().lower()
    if backend and backend not in {"disabled", "none", "off"}:
        return True
    if enabled:
        return True
    return (
        str(getattr(settings, "agent_memory_vector_search_mode", "off") or "").strip().lower()
        == "hybrid"
    )


def _memory_embedding_backend_check(runtime: Any) -> RuntimeComponentStatusResponse:
    settings = getattr(runtime, "settings", None)
    enabled = bool(getattr(settings, "agent_memory_embedding_enabled", False))
    backend = str(getattr(settings, "agent_memory_embedding_backend", "") or "").strip().lower()
    if backend in {"", "disabled", "none", "off"} and enabled:
        backend = (
            str(getattr(settings, "agent_memory_embedding_provider", "openai_compatible"))
            .strip()
            .lower()
        )
    if backend in {"", "disabled", "none", "off"}:
        return RuntimeComponentStatusResponse(
            name="memory_embedding_backend",
            ready=True,
            detail="disabled",
        )

    service = getattr(runtime, "memory_embedding_service", None)
    if service is not None:
        provider_obj = getattr(service, "embedder", None) or getattr(service, "provider", None)
        provider = getattr(provider_obj, "provider_id", None)
        if provider is None and isinstance(provider_obj, str):
            provider = provider_obj
        model = getattr(provider_obj, "model_id", None) or getattr(provider_obj, "model", None)
        details = [f"{provider or backend}: ready"]
        if backend == "auto" and provider:
            details.append(f"auto_selected={provider}")
        if model:
            details.append(f"model={model}")
        dimensions = getattr(provider_obj, "dimensions", None)
        if dimensions:
            details.append(f"dimensions={dimensions}")
        return RuntimeComponentStatusResponse(
            name="memory_embedding_backend",
            ready=True,
            detail=" ".join(details),
        )

    if not getattr(settings, "database_uri", None):
        detail = getattr(runtime, "memory_embedding_backend_error", None) or "local_fallback"
        return RuntimeComponentStatusResponse(
            name="memory_embedding_backend",
            ready=True,
            detail=f"local_fallback: {detail}",
        )

    return RuntimeComponentStatusResponse(
        name="memory_embedding_backend",
        ready=False,
        detail=_memory_embedding_unavailable_detail(runtime, backend=backend),
    )


def _memory_embedding_unavailable_detail(runtime: Any, *, backend: str) -> str:
    settings = getattr(runtime, "settings", None)
    detail = (
        getattr(runtime, "memory_embedding_backend_error", None)
        or f"{backend}: provider unavailable"
    )
    provider = str(getattr(settings, "agent_memory_embedding_provider", "") or "").strip().lower()
    if (
        backend in {"auto", "ollama"} or provider == "ollama" or "ollama" in detail.lower()
    ) and "ollama pull" not in detail:
        return f"{detail}; install_hint=ollama pull embeddinggemma"
    return detail


def _memory_pgvector_check(runtime: Any) -> RuntimeComponentStatusResponse:
    settings = getattr(runtime, "settings", None)
    if not _memory_embedding_configured(settings):
        return RuntimeComponentStatusResponse(
            name="memory_pgvector",
            ready=True,
            detail="disabled",
        )
    if not getattr(settings, "database_uri", None):
        return RuntimeComponentStatusResponse(
            name="memory_pgvector",
            ready=True,
            detail="local_fallback",
        )

    repository = getattr(runtime, "memory_repository", None)
    if repository is None:
        return RuntimeComponentStatusResponse(
            name="memory_pgvector",
            ready=False,
            detail="postgres memory repository missing",
        )
    if not has_repo_method(repository, "inspect_pgvector_support"):
        return RuntimeComponentStatusResponse(
            name="memory_pgvector",
            ready=False,
            detail="postgres memory repository cannot inspect pgvector",
        )

    dimensions = int(getattr(settings, "agent_memory_embedding_dimensions", 1536) or 1536)
    vector_index = bool(getattr(settings, "agent_memory_vector_index_enabled", False))
    extension_mode = str(
        getattr(settings, "agent_memory_pgvector_extension_mode", "auto_create") or "auto_create"
    ).strip()
    try:
        status = repository.inspect_pgvector_support(
            dimensions=dimensions, vector_index=vector_index
        )
    except Exception as exc:  # pragma: no cover - concrete failures are driver-specific.
        return RuntimeComponentStatusResponse(
            name="memory_pgvector",
            ready=False,
            detail=f"inspection_failed: {type(exc).__name__}",
        )

    extension_installed = bool(status.get("extension_installed"))
    table_exists = bool(status.get("embeddings_table_exists"))
    dimensions_match = bool(status.get("dimensions_match"))
    vector_index_exists = bool(status.get("vector_index_exists"))
    ready = extension_installed and table_exists and dimensions_match
    if vector_index:
        ready = ready and vector_index_exists

    version = status.get("extension_version") or "unknown"
    column_type = status.get("embedding_column_type") or "missing"
    index_detail = "present" if vector_index_exists else "missing"
    if not vector_index:
        index_detail = "disabled"
    return RuntimeComponentStatusResponse(
        name="memory_pgvector",
        ready=ready,
        detail=(
            f"mode={extension_mode} extension={'installed' if extension_installed else 'missing'}"
            f" version={version} table={'present' if table_exists else 'missing'}"
            f" dimensions={column_type} index={index_detail}"
        ),
    )


def _retrieval_zvec_check(runtime: Any) -> RuntimeComponentStatusResponse:
    settings = getattr(runtime, "settings", None)
    if not bool(getattr(settings, "agent_zvec_enabled", True)):
        return RuntimeComponentStatusResponse(
            name="retrieval_zvec",
            ready=True,
            detail="disabled",
        )
    backend = str(getattr(settings, "agent_retrieval_backend", "zvec") or "zvec").lower()
    if backend not in {"zvec", "auto"}:
        return RuntimeComponentStatusResponse(
            name="retrieval_zvec",
            ready=True,
            detail=f"backend={backend}",
        )
    index = getattr(runtime, "retrieval_index", None)
    if index is not None:
        data_dir = getattr(index, "data_dir", None)
        detail = f"zvec: ready backend={backend}"
        if data_dir is not None:
            detail += f" data_dir={data_dir}"
        return RuntimeComponentStatusResponse(
            name="retrieval_zvec",
            ready=True,
            detail=detail,
        )
    fallback = str(
        getattr(settings, "agent_retrieval_fallback_backend", "postgres") or ""
    ).strip()
    error = getattr(runtime, "retrieval_index_error", None) or "zvec unavailable"
    return RuntimeComponentStatusResponse(
        name="retrieval_zvec",
        ready=bool(fallback),
        detail=f"{error}; fallback={fallback or 'none'}",
    )


def _component_status(
    runtime: Any,
    attr: str,
    *,
    name: str | None = None,
    ready_detail: str,
    missing_detail: str,
) -> RuntimeComponentStatusResponse:
    ready = getattr(runtime, attr, None) is not None
    return RuntimeComponentStatusResponse(
        name=name or attr,
        ready=ready,
        detail=ready_detail if ready else missing_detail,
    )


def _snapshot_metrics(source: Any, error_key: str) -> dict[str, int]:
    snapshot = safe_repo_call(
        source,
        "snapshot",
        default_missing={},
        default_error={error_key: 1},
    )
    try:
        return {str(key): int(value) for key, value in dict(snapshot).items()}
    except Exception:  # noqa: BLE001 - readiness must degrade instead of crashing.
        return {error_key: 1}


def _background_jobs_check(runtime: Any) -> RuntimeComponentStatusResponse:
    settings = getattr(runtime, "settings", None)
    metrics = {
        **_snapshot_metrics(getattr(runtime, "background_work", None), "job_backend_error"),
        **_snapshot_metrics(
            getattr(runtime, "durable_background_worker", None), "durable_worker_snapshot_error"
        ),
    }
    errors = [
        key
        for key in ("job_backend_error", "durable_worker_snapshot_error")
        if int(metrics.get(key) or 0) > 0
    ]
    dead_lettered = int(metrics.get("job_dead_lettered_total") or 0)
    oldest_pending_seconds = int(metrics.get("job_oldest_pending_seconds") or 0)
    old_pending_threshold = max(
        int(float(getattr(settings, "background_job_old_pending_seconds", 900.0) or 0.0)),
        0,
    )
    problems: list[str] = []
    if errors:
        problems.append(f"snapshot_error={','.join(errors)}")
    if dead_lettered > 0:
        problems.append(f"dead_lettered={dead_lettered}")
    if old_pending_threshold > 0 and oldest_pending_seconds > old_pending_threshold:
        problems.append(f"oldest_pending_seconds={oldest_pending_seconds}")
    if problems:
        return RuntimeComponentStatusResponse(
            name="background_jobs",
            ready=False,
            detail=" ".join(problems),
        )
    return RuntimeComponentStatusResponse(
        name="background_jobs",
        ready=True,
        detail=(
            f"pending={int(metrics.get('job_pending_total') or 0)} "
            f"retrying={int(metrics.get('job_retrying_total') or 0)} "
            f"dead_lettered={dead_lettered}"
        ),
    )


def _build_runtime_readiness(runtime: Any) -> RuntimeReadinessResponse:
    settings = getattr(runtime, "settings", None)
    otel_runtime = getattr(runtime, "otel_runtime", None)
    checks = [
        _component_status(
            runtime,
            "graph",
            ready_detail="langgraph pipeline initialized",
            missing_detail="graph missing",
        ),
        _component_status(
            runtime,
            "repo",
            name="branch_repository",
            ready_detail="branch persistence ready",
            missing_detail="branch repository missing",
        ),
        _component_status(
            runtime,
            "branch_service",
            ready_detail="branch service initialized",
            missing_detail="branch service missing",
        ),
        _component_status(
            runtime,
            "tool_registry",
            ready_detail="tool registry loaded",
            missing_detail="tool registry missing",
        ),
        _component_status(
            runtime,
            "skill_registry",
            ready_detail="skill registry loaded",
            missing_detail="skill registry missing",
        ),
    ]
    if getattr(settings, "database_uri", None):
        checks.append(
            RuntimeComponentStatusResponse(
                name="persistence_backend",
                ready=True,
                detail="postgres-primary",
            )
        )
        checks.append(
            _component_status(
                runtime,
                "memory_repository",
                ready_detail="postgres-canonical",
                missing_detail="postgres memory repository missing",
            )
        )
    else:
        checks.append(
            RuntimeComponentStatusResponse(
                name="persistence_backend",
                ready=True,
                detail="local-fallback",
            )
        )
        checks.append(
            RuntimeComponentStatusResponse(
                name="memory_repository",
                ready=True,
                detail="local_fallback: legacy LangGraph store memory",
            )
        )

    tracing_enabled = bool(getattr(settings, "tracing_enabled", False))
    tracing_exporters = tuple(getattr(settings, "otel_traces_exporters", ()) or ())
    if tracing_enabled:
        if otel_runtime is not None:
            checks.append(
                RuntimeComponentStatusResponse(
                    name="tracing_exporter",
                    ready=bool(getattr(otel_runtime, "ready", False)),
                    detail=str(
                        getattr(otel_runtime, "detail", "tracing exporter state unavailable")
                    ),
                )
            )
        elif tracing_exporters:
            checks.append(
                RuntimeComponentStatusResponse(
                    name="tracing_exporter",
                    ready=False,
                    detail="tracing exporters requested but runtime exporter state is missing",
                )
            )
        else:
            checks.append(
                RuntimeComponentStatusResponse(
                    name="tracing_exporter",
                    ready=True,
                    detail="tracing enabled without exporter",
                )
            )
    else:
        checks.append(
            RuntimeComponentStatusResponse(
                name="tracing_exporter",
                ready=True,
                detail="tracing disabled",
            )
        )

    checks.append(_memory_embedding_backend_check(runtime))
    checks.append(_memory_pgvector_check(runtime))
    checks.append(_retrieval_zvec_check(runtime))
    checks.append(_background_jobs_check(runtime))

    trajectory_expected = _trajectory_expected(settings)
    if trajectory_expected:
        checks.append(
            _component_status(
                runtime,
                "trajectory_recorder",
                ready_detail="trajectory recorder ready",
                missing_detail="trajectory recorder missing while trajectory persistence is configured",
            )
        )
    else:
        checks.append(
            RuntimeComponentStatusResponse(
                name="trajectory_recorder",
                ready=True,
                detail="trajectory persistence disabled",
            )
        )

    ready = all(check.ready for check in checks)
    if is_shutting_down():
        ready = False
        checks.append(
            RuntimeComponentStatusResponse(
                name="shutdown_drain",
                ready=False,
                detail="shutdown in progress; refusing new traffic",
            )
        )
    postgres_metrics = _snapshot_metrics(
        getattr(runtime, "postgres_connection_provider", None),
        "postgres_metrics_error",
    )
    active_connections = int(
        postgres_metrics.get("active_connections")
        or postgres_metrics.get("postgres_active_connections")
        or postgres_metrics.get("postgres_connection_in_use")
        or 0
    )
    return RuntimeReadinessResponse(
        status="ok" if ready else "degraded",
        ready=ready,
        app_version=getattr(settings, "app_version", None),
        environment=getattr(settings, "app_environment", None),
        deployment=getattr(settings, "deployment_name", None),
        active_connections=active_connections,
        checks=checks,
    )


__all__ = [
    "_build_runtime_readiness",
]
