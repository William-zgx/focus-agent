"""Runtime readiness helpers for API routes."""

from __future__ import annotations

from typing import Any

from focus_agent.engine.runtime import AppRuntime

from ..contracts import RuntimeComponentStatusResponse, RuntimeReadinessResponse


def trajectory_expected(settings: Any) -> bool:
    enabled = getattr(settings, "trajectory_enabled", None)
    database_uri = getattr(settings, "database_uri", None)
    if enabled is None:
        return bool(database_uri)
    return bool(enabled and database_uri)


def build_runtime_readiness(runtime: AppRuntime | Any) -> RuntimeReadinessResponse:
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
    else:
        checks.append(
            RuntimeComponentStatusResponse(
                name="persistence_backend",
                ready=True,
                detail="local-fallback",
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

    trajectory_recorder = getattr(runtime, "trajectory_recorder", None)
    if trajectory_expected(settings):
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


__all__ = ["build_runtime_readiness", "trajectory_expected"]
