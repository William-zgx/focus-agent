from __future__ import annotations

import sys
from types import ModuleType

from fastapi import APIRouter

from . import (
    detail,
    list,
    promote,
    replay,
    replay_execution,
    replay_helpers,
    replay_models,
    replay_streaming,
)

router = APIRouter()
router.include_router(replay.router)
router.include_router(detail.router)
router.include_router(list.router)
router.include_router(promote.router)

_COMPAT_MODULES = (
    replay,
    replay_models,
    replay_helpers,
    replay_execution,
    replay_streaming,
    detail,
    list,
    promote,
)

for _module in _COMPAT_MODULES:
    for _name, _value in vars(_module).items():
        if _name.startswith("__") or _name == "router":
            continue
        globals().setdefault(_name, _value)


class _HarnessRunsModule(ModuleType):
    def __setattr__(self, name: str, value: object) -> None:
        super().__setattr__(name, value)
        for module in _COMPAT_MODULES:
            if hasattr(module, name):
                setattr(module, name, value)


sys.modules[__name__].__class__ = _HarnessRunsModule

__all__ = [
    name for name in globals() if not name.startswith("__") and name not in {"ModuleType", "sys"}
]
