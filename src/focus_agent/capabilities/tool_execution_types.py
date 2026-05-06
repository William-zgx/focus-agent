from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from langchain.messages import ToolMessage

from .tool_registry import ToolRuntimeMeta

TOOL_APPROVAL_INTERRUPT_KIND = "tool_approval"


@dataclass(slots=True)
class ToolExecutionInput:
    index: int
    tool_call_id: str
    tool_name: str
    args: dict[str, Any]
    tool: Any
    runtime: ToolRuntimeMeta


@dataclass(slots=True)
class ToolExecutionResult:
    index: int
    message: ToolMessage
    cache_hit: bool = False


@dataclass(frozen=True, slots=True)
class ToolParallelClassification:
    mode: Literal["parallel_safe", "serialized_side_effect", "serialized_runtime"]
    reason: str

    @property
    def can_run_in_parallel(self) -> bool:
        return self.mode == "parallel_safe"


def build_tool_approval_interrupt_payload(item: ToolExecutionInput) -> dict[str, Any]:
    return {
        "kind": TOOL_APPROVAL_INTERRUPT_KIND,
        "tool_name": item.tool_name,
        "tool_call_id": item.tool_call_id,
        "args": item.args,
        "risk_level": item.runtime.risk_level or "low",
    }


def is_tool_approval_approved(response: Any) -> bool:
    if isinstance(response, bool):
        return response
    if isinstance(response, str):
        return _approval_text_is_approved(response)
    if not isinstance(response, dict):
        return False
    kind = response.get("kind")
    if kind is not None and kind != TOOL_APPROVAL_INTERRUPT_KIND:
        return False
    for key in ("approved", "approve", "allowed", "allow"):
        if key in response:
            value = response.get(key)
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return _approval_text_is_approved(value)
            return bool(value)
    decision = (
        str(response.get("decision") or response.get("action") or response.get("status") or "")
        .strip()
        .lower()
    )
    return decision in {"approve", "approved", "allow", "allowed", "yes", "true"}


def _approval_text_is_approved(value: str) -> bool:
    return value.strip().lower() in {
        "approve",
        "approved",
        "allow",
        "allowed",
        "yes",
        "true",
    }
