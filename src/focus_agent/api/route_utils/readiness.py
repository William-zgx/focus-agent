from __future__ import annotations

from typing import Any

from focus_agent.config import Settings
from focus_agent.engine.runtime import AppRuntime

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
        str(getattr(settings, "agent_memory_vector_search_mode", "off") or "")
        .strip()
        .lower()
        == "hybrid"
    )


def _memory_embedding_backend_check(runtime: AppRuntime | Any) -> RuntimeComponentStatusResponse:
    settings = getattr(runtime, "settings", None)
    enabled = bool(getattr(settings, "agent_memory_embedding_enabled", False))
    backend = str(getattr(settings, "agent_memory_embedding_backend", "") or "").strip().lower()
    if backend in {"", "disabled", "none", "off"} and enabled:
        backend = str(
            getattr(settings, "agent_memory_embedding_provider", "openai_compatible")
        ).strip().lower()
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


def _memory_embedding_unavailable_detail(runtime: AppRuntime | Any, *, backend: str) -> str:
    settings = getattr(runtime, "settings", None)
    detail = (
        getattr(runtime, "memory_embedding_backend_error", None)
        or f"{backend}: provider unavailable"
    )
    provider = str(getattr(settings, "agent_memory_embedding_provider", "") or "").strip().lower()
    if (
        backend in {"auto", "ollama"}
        or provider == "ollama"
        or "ollama" in detail.lower()
    ) and "ollama pull" not in detail:
        return f"{detail}; install_hint=ollama pull embeddinggemma"
    return detail


def _memory_pgvector_check(runtime: AppRuntime | Any) -> RuntimeComponentStatusResponse:
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
    inspect_pgvector = getattr(repository, "inspect_pgvector_support", None)
    if not callable(inspect_pgvector):
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
        status = inspect_pgvector(dimensions=dimensions, vector_index=vector_index)
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


def _build_runtime_readiness(runtime: AppRuntime | Any) -> RuntimeReadinessResponse:
    settings = getattr(runtime, "settings", None)
    otel_runtime = getattr(runtime, "otel_runtime", None)
    checks = [
        RuntimeComponentStatusResponse(
            name="graph",
            ready=getattr(runtime, "graph", None) is not None,
            detail="langgraph pipeline initialized" if getattr(runtime, "graph", None) is not None else "graph missing",
        ),
        RuntimeComponentStatusResponse(
            name="branch_repository",
            ready=getattr(runtime, "repo", None) is not None,
            detail="branch persistence ready" if getattr(runtime, "repo", None) is not None else "branch repository missing",
        ),
        RuntimeComponentStatusResponse(
            name="branch_service",
            ready=getattr(runtime, "branch_service", None) is not None,
            detail="branch service initialized" if getattr(runtime, "branch_service", None) is not None else "branch service missing",
        ),
        RuntimeComponentStatusResponse(
            name="tool_registry",
            ready=getattr(runtime, "tool_registry", None) is not None,
            detail="tool registry loaded" if getattr(runtime, "tool_registry", None) is not None else "tool registry missing",
        ),
        RuntimeComponentStatusResponse(
            name="skill_registry",
            ready=getattr(runtime, "skill_registry", None) is not None,
            detail="skill registry loaded" if getattr(runtime, "skill_registry", None) is not None else "skill registry missing",
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
            RuntimeComponentStatusResponse(
                name="memory_repository",
                ready=getattr(runtime, "memory_repository", None) is not None,
                detail=(
                    "postgres-canonical"
                    if getattr(runtime, "memory_repository", None) is not None
                    else "postgres memory repository missing"
                ),
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
                    detail=str(getattr(otel_runtime, "detail", "tracing exporter state unavailable")),
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

    trajectory_expected = _trajectory_expected(settings)
    trajectory_recorder = getattr(runtime, "trajectory_recorder", None)
    if trajectory_expected:
        checks.append(
            RuntimeComponentStatusResponse(
                name="trajectory_recorder",
                ready=trajectory_recorder is not None,
                detail=(
                    "trajectory recorder ready"
                    if trajectory_recorder is not None
                    else "trajectory recorder missing while trajectory persistence is configured"
                ),
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
    return RuntimeReadinessResponse(
        status="ok" if ready else "degraded",
        ready=ready,
        app_version=getattr(settings, "app_version", None),
        environment=getattr(settings, "app_environment", None),
        deployment=getattr(settings, "deployment_name", None),
        checks=checks,
    )




__all__ = [
    "_build_runtime_readiness",
]
