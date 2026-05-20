from __future__ import annotations

from fastapi import APIRouter

from . import replay_execution, replay_helpers, replay_models, replay_streaming

router = APIRouter()
router.include_router(replay_execution.router)
router.include_router(replay_streaming.router)

_COMPAT_MODULES = (replay_models, replay_helpers, replay_execution, replay_streaming)

for _module in _COMPAT_MODULES:
    for _name, _value in vars(_module).items():
        if _name.startswith("__") or _name == "router":
            continue
        globals().setdefault(_name, _value)

__all__ = [name for name in globals() if not name.startswith("__") and name not in {"ModuleType"}]
