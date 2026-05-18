from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from focus_agent.config import Settings
from focus_agent.config_parts.auth import validate_jwt_secret_for_environment
from focus_agent.engine.runtime import create_runtime
from focus_agent.runtime.http_client import aclose as close_async_http_client
from focus_agent.runtime.http_client import close as close_sync_http_client
from focus_agent.runtime.lifecycle import (
    install_signal_handlers,
    register_shutdown_hook,
    reset_shutdown_state,
    trigger_shutdown,
    unregister_shutdown_hook,
)
from focus_agent.runtime.thread_pool import shutdown_thread_pool
from focus_agent.services.chat import ChatService


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    settings = Settings.from_env()
    validate_jwt_secret_for_environment(settings)
    reset_shutdown_state()
    install_signal_handlers(asyncio.get_running_loop())
    runtime = create_runtime(settings)
    app.state.runtime = runtime
    app.state.chat_service = ChatService(runtime)
    register_shutdown_hook(close_async_http_client)

    async def _close_runtime() -> None:
        runtime.close()
        close_sync_http_client()
        shutdown_thread_pool()

    register_shutdown_hook(_close_runtime)
    runtime.start_durable_background_worker(app.state.chat_service)
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
