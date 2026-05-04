from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from langchain.messages import ToolMessage

from .tool_registry import ToolRuntimeMeta


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
