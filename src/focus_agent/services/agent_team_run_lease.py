from __future__ import annotations

import threading
from typing import Any

from focus_agent.core.agent_team import AgentTeamTask
from focus_agent.multi_agent.contracts import ResourceClaim

from .agent_team_run_helpers import _AGENT_TEAM_TASK_CLAIM_TTL_SECONDS


class _AgentTeamLeaseHeartbeat:
    def __init__(
        self,
        service: Any,
        *,
        task: AgentTeamTask,
        resource_claims: list[ResourceClaim],
    ) -> None:
        self._service = service
        self._task_id = task.task_id
        self._claim_token = task.claim_token or ""
        self._resource_claims = list(resource_claims)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        resource_ttl = float(
            getattr(service.settings, "multi_agent_resource_lock_ttl_seconds", 60.0) or 60.0
        )
        configured_interval = float(
            getattr(service.settings, "multi_agent_resource_lock_heartbeat_seconds", 15.0) or 15.0
        )
        self._resource_ttl = max(resource_ttl, 0.001)
        self._interval = max(0.001, min(configured_interval, self._resource_ttl / 3.0))

    def start(self) -> None:
        if not self._claim_token and not self._resource_claims:
            return
        self._thread = threading.Thread(
            target=self._run,
            name=f"agent-team-lease-heartbeat:{self._task_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(self._interval * 2.0, 0.05))

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            if not self._heartbeat_once():
                self._stop.set()
                return

    def _heartbeat_once(self) -> bool:
        if self._claim_token:
            try:
                alive = self._service.repository.heartbeat_task_claim(
                    task_id=self._task_id,
                    claim_token=self._claim_token,
                    ttl_seconds=_AGENT_TEAM_TASK_CLAIM_TTL_SECONDS,
                )
            except Exception:  # noqa: BLE001
                return False
            if not alive:
                return False
        lock_backend = getattr(self._service.coordination_backend, "resource_locks", None)
        if lock_backend is None:
            return True
        for claim in self._resource_claims:
            try:
                alive = bool(lock_backend.heartbeat(claim, ttl_seconds=self._resource_ttl))
            except Exception:  # noqa: BLE001
                return False
            if not alive:
                return False
        return True


__all__ = ["_AgentTeamLeaseHeartbeat"]
