from __future__ import annotations

# ruff: noqa: F403, F405
from ..route_helpers import *

router = APIRouter()


@router.get('/healthz')
def health_check() -> dict[str, str]:
    return {'status': 'ok'}

@router.get('/readyz', response_model=RuntimeReadinessResponse)
def readiness_check(
    response: Response,
    runtime: AppRuntime = Depends(get_app_runtime),
) -> RuntimeReadinessResponse:
    readiness = _build_runtime_readiness(runtime)
    if not readiness.ready:
        response.status_code = 503
    return readiness

@router.get('/metrics', response_class=PlainTextResponse)
def metrics_scrape(runtime: AppRuntime = Depends(get_app_runtime)) -> PlainTextResponse:
    runtime_status = _build_runtime_readiness(runtime)
    trajectory_stats: dict[str, Any] | None = None
    agent_governance_metrics: dict[str, int] = {}
    trajectory_available = False
    repo = _maybe_get_trajectory_repository(runtime)
    if repo is not None:
        try:
            trajectory_stats = repo.get_turn_stats(TrajectoryTurnQuery(limit=None, newest_first=True))
            rows = repo.list_turns(TrajectoryTurnQuery(limit=None, newest_first=True))
        except Exception:  # noqa: BLE001
            trajectory_stats = None
        else:
            trajectory_available = True
            agent_governance_metrics = _agent_governance_metrics_from_turns(rows)
    payload = _build_prometheus_metrics_payload(
        runtime_status=runtime_status,
        trajectory_stats=trajectory_stats,
        trajectory_available=trajectory_available,
        agent_governance_metrics=agent_governance_metrics,
    )
    return PlainTextResponse(payload, media_type="text/plain; version=0.0.4; charset=utf-8")
