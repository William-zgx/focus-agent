from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from focus_agent.config import Settings
from focus_agent.config_parts.auth import validate_jwt_secret_for_environment
from focus_agent.engine.runtime import create_runtime
from focus_agent.runtime.http_client import aclose as close_async_http_client
from focus_agent.runtime.http_client import close as close_sync_http_client
from focus_agent.runtime.lifecycle import (
    register_shutdown_hook,
    reset_shutdown_state,
    trigger_shutdown,
    unregister_shutdown_hook,
)
from focus_agent.runtime.thread_pool import shutdown_thread_pool
from focus_agent.services.chat import ChatService

from ..deps import _start_durable_background_worker


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    settings = Settings.from_env()
    validate_jwt_secret_for_environment(settings)
    reset_shutdown_state()
    runtime = create_runtime(settings)
    app.state.runtime = runtime
    app.state.chat_service = ChatService(runtime)
    register_shutdown_hook(close_async_http_client)

    async def _close_runtime() -> None:
        close_chat_service = getattr(app.state.chat_service, "close", None)
        if callable(close_chat_service):
            close_chat_service()
        close_run_manager = getattr(getattr(runtime, "run_manager", None), "close", None)
        if callable(close_run_manager):
            await close_run_manager()
        runtime.close()
        close_sync_http_client()
        shutdown_thread_pool()

    register_shutdown_hook(_close_runtime)
    await _start_durable_background_worker(runtime, app.state.chat_service)
    try:
        yield
    finally:
        try:
            await trigger_shutdown()
        finally:
            unregister_shutdown_hook(_close_runtime)
            unregister_shutdown_hook(close_async_http_client)
            app.state.runtime = None
            app.state.chat_service = None


__all__ = [
    "app_lifespan",
]
