from __future__ import annotations

import time
from types import SimpleNamespace

from focus_agent.api.route_utils.readiness import _build_runtime_readiness
from focus_agent.services.background_work import (
    BackgroundJobHandlerRegistry,
    DurableBackgroundWorker,
)


def test_durable_worker_recovers_from_claim_error_and_reports_liveness() -> None:
    class Backend:
        def __init__(self) -> None:
            self.claim_attempts = 0

        def claim_next_job(self, *, allowed_kinds, claim_ttl_seconds=None):
            self.claim_attempts += 1
            if self.claim_attempts == 1:
                raise RuntimeError("database unavailable")
            return None

    backend = Backend()
    worker = DurableBackgroundWorker(
        name="claim-recovery",
        job_backend=backend,
        handlers=BackgroundJobHandlerRegistry(),
        poll_interval_seconds=0.05,
    )
    try:
        worker.start()
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and backend.claim_attempts < 2:
            time.sleep(0.01)

        snapshot = worker.snapshot()
        assert backend.claim_attempts >= 2
        assert snapshot["durable_worker_claim_error_total"] == 1
        assert snapshot["durable_worker_consecutive_claim_errors"] == 0
        assert snapshot["durable_worker_thread_alive"] == 1
        assert snapshot["durable_worker_heartbeat_fresh"] == 1
    finally:
        worker.close()


def test_readyz_rejects_dead_or_stale_durable_worker() -> None:
    class Worker:
        def __init__(self, *, thread_alive: int, heartbeat_fresh: int) -> None:
            self.thread_alive = thread_alive
            self.heartbeat_fresh = heartbeat_fresh

        def snapshot(self) -> dict[str, int]:
            return {
                "durable_worker_thread_alive": self.thread_alive,
                "durable_worker_heartbeat_fresh": self.heartbeat_fresh,
            }

    runtime = _runtime_with_durable_worker(Worker(thread_alive=0, heartbeat_fresh=1))
    readiness = _build_runtime_readiness(runtime)

    assert readiness.ready is False
    assert _check_detail(readiness, "background_jobs") == "durable_worker_dead"

    runtime.durable_background_worker = Worker(thread_alive=1, heartbeat_fresh=0)
    readiness = _build_runtime_readiness(runtime)

    assert readiness.ready is False
    assert _check_detail(readiness, "background_jobs") == "durable_worker_heartbeat_stale"


def _runtime_with_durable_worker(worker: object) -> SimpleNamespace:
    return SimpleNamespace(
        settings=SimpleNamespace(
            background_job_execution="durable",
            background_job_old_pending_seconds=900.0,
            database_uri=None,
            tracing_enabled=False,
            otel_traces_exporters=(),
            agent_memory_embedding_enabled=False,
            agent_memory_embedding_backend="disabled",
            agent_memory_vector_search_mode="off",
            agent_zvec_enabled=False,
            trajectory_enabled=False,
            app_version=None,
            app_environment=None,
            deployment_name=None,
        ),
        graph=object(),
        repo=object(),
        branch_service=object(),
        tool_registry=object(),
        skill_registry=object(),
        background_work=SimpleNamespace(snapshot=lambda: {}),
        durable_background_worker=worker,
        memory_embedding_service=None,
        memory_embedding_backend_error=None,
        retrieval_index=None,
        retrieval_index_error=None,
        trajectory_recorder=None,
        postgres_connection_provider=None,
    )


def _check_detail(readiness, name: str) -> str:
    return next(check.detail for check in readiness.checks if check.name == name)
