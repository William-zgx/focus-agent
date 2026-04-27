"""FastAPI application lifespan boundary."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from focus_agent.config import Settings
from focus_agent.engine.runtime import create_runtime
from focus_agent.services.chat import ChatService


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    runtime = create_runtime(Settings.from_env())
    app.state.runtime = runtime
    app.state.chat_service = ChatService(runtime)
    try:
        yield
    finally:
        runtime.close()


__all__ = ["app_lifespan"]
