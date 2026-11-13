from contextlib import ExitStack
from types import SimpleNamespace

from focus_agent.engine.runtime_composition import start_durable_background_worker
from focus_agent.services.background_work import (
    BackgroundJobHandlerRegistry,
    register_default_background_job_handlers,
)


class _Worker:
    def __init__(self, *, name, job_backend, handlers, claim_ttl_seconds):  # noqa: ARG002
        self.handlers = handlers
        self.started = False
        self.closed = False

    def start(self):
        self.started = True

    def close(self):
        self.closed = True


def _runtime():
    return SimpleNamespace(
        settings=SimpleNamespace(
            background_job_execution="durable",
            database_uri="postgresql://test",
            background_job_backend="postgres",
            background_job_claim_ttl_seconds=30,
        ),
        durable_background_worker=None,
        branch_service=None,
        branch_decision_service=None,
        memory_embedding_service=None,
        memory_repository=None,
        coordination_backend=SimpleNamespace(job_deduper=object()),
        _exit_stack=ExitStack(),
    )


def _start(runtime, harness_run_handler=None):
    return start_durable_background_worker(
        runtime=runtime,
        chat_service=object(),
        handler_registry_factory=BackgroundJobHandlerRegistry,
        handler_registrar=register_default_background_job_handlers,
        durable_worker_factory=_Worker,
        harness_run_handler=harness_run_handler,
    )


def test_engine_registers_injected_harness_run_handler():
    runtime = _runtime()
    calls = []
    handler = calls.append

    worker = _start(runtime, handler)

    assert worker.started
    assert worker.handlers.get("harness_run") is handler
    worker.handlers.get("harness_run")({"run_id": "run-1"})
    assert calls == [{"run_id": "run-1"}]
    runtime._exit_stack.close()
    assert worker.closed


def test_engine_leaves_harness_run_unregistered_without_api_handler():
    runtime = _runtime()

    worker = _start(runtime)

    assert "harness_run" not in worker.handlers.kinds()
    runtime._exit_stack.close()
