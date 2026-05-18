from __future__ import annotations

import json
from typing import Any

from langchain.messages import ToolMessage

from .tool_execution_types import ToolExecutionInput, ToolExecutionResult


def build_tool_error_message(
    *,
    tool_call_id: str,
    tool_name: str,
    args: dict[str, Any],
    error: Exception | str,
    runtime_info: dict[str, Any] | None = None,
) -> ToolMessage:
    merged_runtime_info = {"cache_hit": False, "fallback_used": False, **dict(runtime_info or {})}
    payload = {
        "status": "error",
        "tool": tool_name,
        "args": args,
        "error": str(error),
        "runtime": merged_runtime_info,
    }
    return build_tool_message(
        content=json.dumps(payload, ensure_ascii=False),
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        status="error",
        runtime_info=merged_runtime_info,
    )


def build_tool_message(
    *,
    content: str,
    tool_call_id: str,
    tool_name: str,
    prompt_observation: str | None = None,
    status: str = "success",
    runtime_info: dict[str, Any] | None = None,
) -> ToolMessage:
    artifact = {
        "runtime": dict(runtime_info or {}),
        "tool_name": tool_name,
    }
    if prompt_observation:
        artifact["prompt_observation"] = prompt_observation
    return ToolMessage(
        content=content,
        tool_call_id=tool_call_id,
        status=status,  # type: ignore[arg-type]
        artifact=artifact,
    )


def copy_result_for_tool_call(
    *,
    source: ToolExecutionResult,
    item: ToolExecutionInput,
    cache_hit: bool,
) -> ToolExecutionResult:
    artifact = getattr(source.message, "artifact", None)
    runtime_info = {}
    prompt_observation = None
    if isinstance(artifact, dict) and isinstance(artifact.get("runtime"), dict):
        runtime_info = dict(artifact.get("runtime") or {})
        if isinstance(artifact.get("prompt_observation"), str):
            prompt_observation = str(artifact.get("prompt_observation"))
    runtime_info["deduplicated"] = True
    if cache_hit:
        runtime_info["cache_hit"] = True
    return ToolExecutionResult(
        index=item.index,
        cache_hit=cache_hit,
        message=build_tool_message(
            content=str(source.message.content),
            tool_call_id=item.tool_call_id,
            tool_name=item.tool_name,
            prompt_observation=prompt_observation,
            status=getattr(source.message, "status", "success"),
            runtime_info=runtime_info,
        ),
    )


def annotate_tool_result_runtime(result: ToolExecutionResult, runtime_info: dict[str, Any]) -> None:
    clean_runtime_info = {key: value for key, value in runtime_info.items() if value is not None}
    if not clean_runtime_info:
        return
    artifact = getattr(result.message, "artifact", None)
    if not isinstance(artifact, dict):
        artifact = {}
    existing_runtime = artifact.get("runtime")
    merged_runtime = dict(existing_runtime or {}) if isinstance(existing_runtime, dict) else {}
    for key, value in clean_runtime_info.items():
        merged_runtime.setdefault(key, value)
    artifact["runtime"] = merged_runtime
    result.message.artifact = artifact
