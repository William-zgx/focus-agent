from __future__ import annotations

import sys
from typing import Any

from langgraph.config import get_stream_writer

from ..observability.tracing import current_trace_runtime_payload
from .tool_execution_types import ToolExecutionInput


def emit_runtime_tool_event(
    *,
    item: ToolExecutionInput,
    stage: str,
    **payload: Any,
) -> None:
    try:
        writer = _stream_writer()
    except Exception:  # noqa: BLE001
        return
    metadata = getattr(item.tool, "metadata", None)
    display_name = metadata.get("display_name") if isinstance(metadata, dict) else None
    writer(
        {
            "event": "tool",
            "tool_name": item.tool_name,
            "display_name": display_name,
            "stage": stage,
            **current_trace_runtime_payload(),
            **payload,
        }
    )


def _stream_writer() -> Any:
    facade = sys.modules.get("focus_agent.capabilities.tool_runtime")
    facade_getter = getattr(facade, "get_stream_writer", None)
    if callable(facade_getter):
        return facade_getter()
    return get_stream_writer()
