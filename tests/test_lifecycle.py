from __future__ import annotations

import asyncio
from types import SimpleNamespace

from focus_agent.api.route_utils import lifespan as lifespan_module
from focus_agent.runtime.lifecycle import (
    is_shutting_down,
    register_shutdown_hook,
    reset_shutdown_state,
    trigger_shutdown,
    unregister_shutdown_hook,
)


def test_trigger_shutdown_sets_flag_and_runs_registered_hooks() -> None:
    reset_shutdown_state()
    calls: list[str] = []

    async def hook() -> None:
        calls.append("hook")

    register_shutdown_hook(hook)
    try:
        asyncio.run(trigger_shutdown())
    finally:
        unregister_shutdown_hook(hook)

    assert is_shutting_down() is True
    assert calls == ["hook"]


def test_reset_shutdown_state_clears_drain_flag_between_app_lifespans() -> None:
    reset_shutdown_state()
    assert is_shutting_down() is False


def test_app_lifespan_leaves_uvicorn_signal_handlers_alone(monkeypatch) -> None:
    signal_calls: list[object] = []

    class FakeSettings:
        @classmethod
        def from_env(cls):
            return cls()

    class FakeRuntime:
        def start_durable_background_worker(self, _chat_service) -> None:
            return None

        def close(self) -> None:
            return None

    async def close_async_http_client() -> None:
        return None

    monkeypatch.setattr(lifespan_module, "Settings", FakeSettings)
    monkeypatch.setattr(lifespan_module, "validate_jwt_secret_for_environment", lambda _s: None)
    monkeypatch.setattr(lifespan_module, "create_runtime", lambda _s: FakeRuntime())
    monkeypatch.setattr(lifespan_module, "ChatService", lambda _runtime: object())
    monkeypatch.setattr(lifespan_module, "close_async_http_client", close_async_http_client)
    monkeypatch.setattr(lifespan_module, "close_sync_http_client", lambda: None)
    monkeypatch.setattr(lifespan_module, "shutdown_thread_pool", lambda: None)
    monkeypatch.setattr(
        lifespan_module,
        "install_signal_handlers",
        lambda *args, **kwargs: signal_calls.append((args, kwargs)),
        raising=False,
    )

    async def run_lifespan() -> None:
        app = SimpleNamespace(state=SimpleNamespace())
        async with lifespan_module.app_lifespan(app):
            assert app.state.runtime is not None

    try:
        asyncio.run(run_lifespan())
    finally:
        reset_shutdown_state()

    assert signal_calls == []
