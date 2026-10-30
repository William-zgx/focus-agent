from __future__ import annotations

from fastapi import APIRouter

from . import replay_execution, replay_streaming

router = APIRouter()
router.include_router(replay_execution.router)
router.include_router(replay_streaming.router)

__all__ = ["router"]
