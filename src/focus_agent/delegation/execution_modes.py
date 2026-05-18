from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

DelegationExecutionMode = Literal["observe", "fake", "inline", "background"]
ModelFactory = Callable[..., Any]


def normalize_delegation_execution_mode(value: str | None) -> DelegationExecutionMode:
    normalized = str(value or "observe").strip().lower()
    if normalized in {"fake", "inline", "background"}:
        return normalized  # type: ignore[return-value]
    return "observe"


__all__ = [
    "DelegationExecutionMode",
    "ModelFactory",
    "normalize_delegation_execution_mode",
]
