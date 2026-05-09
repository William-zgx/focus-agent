"""Tool harness helpers."""

from typing import Any

from .envelope import ToolResultContent, ToolResultEnvelope, ToolResultStatus
from .messages import envelope_to_tool_message, tool_message_to_envelope
from .schema import canonical_tool_schema, tool_schema_fingerprint, tools_schema_fingerprint


def __getattr__(name: str) -> Any:
    if name in {"SubagentTaskToolInput", "create_subagent_task_tool"}:
        from .subagents import SubagentTaskToolInput, create_subagent_task_tool

        return {
            "SubagentTaskToolInput": SubagentTaskToolInput,
            "create_subagent_task_tool": create_subagent_task_tool,
        }[name]
    raise AttributeError(name)

__all__ = [
    "SubagentTaskToolInput",
    "ToolResultContent",
    "ToolResultEnvelope",
    "ToolResultStatus",
    "canonical_tool_schema",
    "create_subagent_task_tool",
    "envelope_to_tool_message",
    "tool_message_to_envelope",
    "tool_schema_fingerprint",
    "tools_schema_fingerprint",
]
