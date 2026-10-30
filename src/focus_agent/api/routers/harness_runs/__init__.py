from __future__ import annotations

from fastapi import APIRouter

from . import detail, list, promote, replay

router = APIRouter()
router.include_router(replay.router)
router.include_router(detail.router)
router.include_router(list.router)
router.include_router(promote.router)

__all__ = ["router"]
