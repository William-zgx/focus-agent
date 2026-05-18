from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import Lock
from time import monotonic
from typing import Any

from fastapi import APIRouter, Depends, Response
from fastapi.responses import PlainTextResponse

from focus_agent.capabilities.tool_invocation import tool_invocation_runtime_snapshot
from focus_agent.core.repo_call import safe_repo_call
from focus_agent.engine.runtime import AppRuntime

from ..contracts import RuntimeReadinessResponse
from ..deps import get_app_runtime
from ..route_utils.agent_governance import _agent_governance_metrics_from_turns
from ..route_utils.metrics import _build_prometheus_metrics_payload
from ..route_utils.readiness import _build_runtime_readiness
from ..route_utils.trajectory import TrajectoryTurnQuery, _maybe_get_trajectory_repository

router = APIRouter()

_METRICS_TRAJECTORY_CACHE: dict[tuple[int, int, int], tuple[float, dict[str, Any]]] = {}
_METRICS_TRAJECTORY_CACHE_LOCK = Lock()
_DEFAULT_METRICS_TRAJECTORY_WINDOW_HOURS = 24
_DEFAULT_METRICS_CACHE_TTL_SECONDS = 15
_DEFAULT_METRICS_GOVERNANCE_RECENT_LIMIT = 1000


@router.get("/healthz")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", response_model=RuntimeReadinessResponse)
def readiness_check(
    response: Response,
    runtime: AppRuntime = Depends(get_app_runtime),
) -> RuntimeReadinessResponse:
    readiness = _build_runtime_readiness(runtime)
    if not readiness.ready:
        response.status_code = 503
    return readiness


@router.get("/metrics", response_class=PlainTextResponse)
def metrics_scrape(runtime: AppRuntime = Depends(get_app_runtime)) -> PlainTextResponse:
    runtime_status = _build_runtime_readiness(runtime)
    repo = _maybe_get_trajectory_repository(runtime)
    metrics_data = _metrics_trajectory_data(runtime=runtime, repo=repo)
    payload = _build_prometheus_metrics_payload(
        runtime_status=runtime_status,
        trajectory_stats=metrics_data["trajectory_stats"],
        trajectory_available=bool(metrics_data["trajectory_available"]),
        agent_governance_metrics=metrics_data["agent_governance_metrics"],
        background_metrics=_background_metrics(runtime),
        postgres_metrics=_postgres_metrics(runtime),
        tool_runtime_metrics=tool_invocation_runtime_snapshot(),
    )
    return PlainTextResponse(payload, media_type="text/plain; version=0.0.4; charset=utf-8")


def _background_metrics(runtime: AppRuntime) -> dict[str, int]:
    return {
        **_snapshot_metrics(getattr(runtime, "background_work", None), "job_backend_error"),
        **_snapshot_metrics(
            getattr(runtime, "durable_background_worker", None), "durable_worker_snapshot_error"
        ),
    }


def _postgres_metrics(runtime: AppRuntime) -> dict[str, int | float]:
    return _snapshot_metrics(
        getattr(runtime, "postgres_connection_provider", None), "postgres_metrics_error"
    )


def _snapshot_metrics(source: Any, error_key: str) -> dict[str, int | float]:
    snapshot = safe_repo_call(
        source,
        "snapshot",
        default_missing={},
        default_error={error_key: 1},
    )
    try:
        return dict(snapshot)
    except Exception:  # noqa: BLE001
        return {error_key: 1}


def _metrics_trajectory_data(*, runtime: AppRuntime, repo: Any | None) -> dict[str, Any]:
    if repo is None:
        return {
            "trajectory_stats": None,
            "trajectory_available": False,
            "agent_governance_metrics": {},
        }

    settings = getattr(runtime, "settings", None)
    window_hours = max(
        int(
            getattr(
                settings,
                "metrics_trajectory_window_hours",
                _DEFAULT_METRICS_TRAJECTORY_WINDOW_HOURS,
            )
            or 0
        ),
        1,
    )
    cache_ttl_seconds = max(
        int(
            getattr(settings, "metrics_cache_ttl_seconds", _DEFAULT_METRICS_CACHE_TTL_SECONDS) or 0
        ),
        0,
    )
    governance_recent_limit = max(
        int(
            getattr(
                settings,
                "metrics_governance_recent_limit",
                _DEFAULT_METRICS_GOVERNANCE_RECENT_LIMIT,
            )
            or 0
        ),
        0,
    )
    cache_key = (id(repo), window_hours, governance_recent_limit)
    now = monotonic()
    if cache_ttl_seconds > 0:
        with _METRICS_TRAJECTORY_CACHE_LOCK:
            cached = _METRICS_TRAJECTORY_CACHE.get(cache_key)
            if cached is not None and cached[0] > now:
                return cached[1]

    since = datetime.now(UTC) - timedelta(hours=window_hours)
    try:
        trajectory_stats = repo.get_turn_stats(
            TrajectoryTurnQuery(since=since, limit=None, newest_first=True)
        )
        rows = repo.list_turns(
            TrajectoryTurnQuery(
                since=since,
                limit=governance_recent_limit,
                newest_first=True,
            )
        )
    except Exception:  # noqa: BLE001
        data = {
            "trajectory_stats": None,
            "trajectory_available": False,
            "agent_governance_metrics": {},
        }
    else:
        data = {
            "trajectory_stats": trajectory_stats,
            "trajectory_available": True,
            "agent_governance_metrics": _agent_governance_metrics_from_turns(rows),
        }

    if cache_ttl_seconds > 0:
        with _METRICS_TRAJECTORY_CACHE_LOCK:
            _METRICS_TRAJECTORY_CACHE[cache_key] = (now + cache_ttl_seconds, data)
    return data
