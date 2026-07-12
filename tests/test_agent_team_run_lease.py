from __future__ import annotations

from types import SimpleNamespace

from focus_agent.core.agent_team import AgentTeamTask, AgentTeamTaskRole
from focus_agent.multi_agent.contracts import LockMode, ResourceClaim
from focus_agent.services.agent_team_run_helpers import _AGENT_TEAM_TASK_CLAIM_TTL_SECONDS
from focus_agent.services.agent_team_run_lease import _AgentTeamLeaseHeartbeat


def _task(*, claim_token: str | None = "claim-token") -> AgentTeamTask:
    return AgentTeamTask(
        task_id="task-1",
        session_id="session-1",
        role=AgentTeamTaskRole.BACKEND_EXECUTOR,
        goal="Implement the task",
        claim_token=claim_token,
        created_at="2026-07-11T00:00:00Z",
        updated_at="2026-07-11T00:00:00Z",
    )


def _claim(claim_id: str) -> ResourceClaim:
    return ResourceClaim(
        claim_id=claim_id,
        resource_id=f"file:src/{claim_id}.py",
        agent_id="backend:task-1",
        session_id="session-1",
        mode=LockMode.EXCLUSIVE,
        expires_at=1.0,
    )


class _Repository:
    def __init__(self, *, alive: bool = True) -> None:
        self.alive = alive
        self.calls: list[dict[str, object]] = []

    def heartbeat_task_claim(self, **kwargs: object) -> bool:
        self.calls.append(kwargs)
        return self.alive


class _ResourceLocks:
    def __init__(self, *, results: list[bool] | None = None) -> None:
        self.results = list(results or [])
        self.calls: list[tuple[ResourceClaim, float]] = []

    def heartbeat(self, claim: ResourceClaim, *, ttl_seconds: float) -> bool:
        self.calls.append((claim, ttl_seconds))
        return self.results.pop(0) if self.results else True


def _service(
    repository: _Repository,
    resource_locks: _ResourceLocks | None,
    *,
    ttl_seconds: float = 60.0,
    heartbeat_seconds: float = 15.0,
) -> SimpleNamespace:
    return SimpleNamespace(
        repository=repository,
        coordination_backend=SimpleNamespace(resource_locks=resource_locks),
        settings=SimpleNamespace(
            multi_agent_resource_lock_ttl_seconds=ttl_seconds,
            multi_agent_resource_lock_heartbeat_seconds=heartbeat_seconds,
        ),
    )


def test_lease_heartbeat_renews_task_claim_before_resource_claims() -> None:
    repository = _Repository()
    resource_locks = _ResourceLocks()
    claims = [_claim("claim-1"), _claim("claim-2")]
    heartbeat = _AgentTeamLeaseHeartbeat(
        _service(repository, resource_locks, ttl_seconds=9.0),
        task=_task(),
        resource_claims=claims,
    )

    assert heartbeat._heartbeat_once() is True
    assert repository.calls == [
        {
            "task_id": "task-1",
            "claim_token": "claim-token",
            "ttl_seconds": _AGENT_TEAM_TASK_CLAIM_TTL_SECONDS,
        }
    ]
    assert resource_locks.calls == [(claims[0], 9.0), (claims[1], 9.0)]


def test_lease_heartbeat_stops_when_task_or_resource_claim_is_lost() -> None:
    lost_repository = _Repository(alive=False)
    resource_locks = _ResourceLocks()
    heartbeat = _AgentTeamLeaseHeartbeat(
        _service(lost_repository, resource_locks),
        task=_task(),
        resource_claims=[_claim("claim-1")],
    )

    assert heartbeat._heartbeat_once() is False
    assert resource_locks.calls == []

    live_repository = _Repository()
    resource_locks = _ResourceLocks(results=[False])
    claims = [_claim("claim-1"), _claim("claim-2")]
    heartbeat = _AgentTeamLeaseHeartbeat(
        _service(live_repository, resource_locks),
        task=_task(),
        resource_claims=claims,
    )

    assert heartbeat._heartbeat_once() is False
    assert resource_locks.calls == [(claims[0], 60.0)]


def test_lease_heartbeat_interval_is_bounded_and_empty_lease_does_not_start() -> None:
    heartbeat = _AgentTeamLeaseHeartbeat(
        _service(
            _Repository(),
            None,
            ttl_seconds=0.002,
            heartbeat_seconds=30.0,
        ),
        task=_task(claim_token=None),
        resource_claims=[],
    )

    assert heartbeat._resource_ttl == 0.002
    assert heartbeat._interval == 0.001
    heartbeat.start()
    heartbeat.stop()
    assert heartbeat._thread is None
