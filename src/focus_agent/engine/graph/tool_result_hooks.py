from __future__ import annotations

import json
import logging
from typing import Any

from langchain.messages import ToolMessage

from ...capabilities.tool_messages import build_tool_error_message, build_tool_message
from ...capabilities.tool_runtime import ToolExecutionResult

logger = logging.getLogger(__name__)


def _patch_tool_message_content(message: ToolMessage, new_content: Any) -> ToolMessage:
    """Return a copy of *message* with its content replaced by *new_content*."""

    if isinstance(new_content, str):
        content_str = new_content
    else:
        try:
            content_str = json.dumps(new_content, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            content_str = str(new_content)
    artifact = getattr(message, "artifact", None)
    runtime_info: dict[str, Any] = {}
    prompt_observation = None
    tool_name = ""
    if isinstance(artifact, dict):
        tool_name = str(artifact.get("tool_name", "") or "")
        rt = artifact.get("runtime")
        if isinstance(rt, dict):
            runtime_info = dict(rt)
        po = artifact.get("prompt_observation")
        if isinstance(po, str):
            prompt_observation = po
    runtime_info["content_patched"] = True
    return build_tool_message(
        content=content_str,
        tool_call_id=str(getattr(message, "tool_call_id", "") or ""),
        tool_name=tool_name,
        prompt_observation=prompt_observation,
        status=str(getattr(message, "status", "success") or "success"),
        runtime_info=runtime_info,
    )


def _patch_tool_message_error(message: ToolMessage, error_text: str) -> ToolMessage:
    """Return a copy of *message* rewritten as an error ToolMessage."""

    artifact = getattr(message, "artifact", None)
    tool_name = ""
    if isinstance(artifact, dict):
        tool_name = str(artifact.get("tool_name", "") or "")
    runtime_info: dict[str, Any] = {"error_patched": True}
    if isinstance(artifact, dict):
        rt = artifact.get("runtime")
        if isinstance(rt, dict):
            runtime_info = {**rt, **runtime_info}
    args: dict[str, Any] = {}
    try:
        parsed = json.loads(str(message.content or ""))
        if isinstance(parsed, dict) and isinstance(parsed.get("args"), dict):
            args = parsed["args"]
    except (TypeError, ValueError, json.JSONDecodeError):
        args = {}
    return build_tool_error_message(
        tool_call_id=str(getattr(message, "tool_call_id", "") or ""),
        tool_name=tool_name,
        args=args,
        error=error_text,
        runtime_info=runtime_info,
    )


def _apply_result_hooks(
    results: list[Any],
    *,
    services: Any | None,
    ext_ctx: Any,
    thread_id: str,
    run_id: str | None,
    active_agent_name: str,
) -> list[Any]:
    """Apply middleware and extension result hooks without mutating cached results."""

    if not results:
        return results
    if services is None:
        return results
    have_mw = services.middleware_stack is not None
    have_ext = services.extension_registry is not None and ext_ctx is not None
    if not have_mw and not have_ext:
        return results

    mw_ctx = {
        "thread_id": thread_id,
        "run_id": run_id,
        "agent_name": active_agent_name,
    }

    patched_results: list[Any] = []
    for result in results:
        message = result.message
        tool_name = ""
        artifact = getattr(message, "artifact", None)
        if isinstance(artifact, dict):
            tool_name = str(artifact.get("tool_name", "") or "")
        try:
            if have_mw:
                mw_decision = services.middleware_stack.intercept_tool_result(
                    tool_name,
                    message,
                    ctx=mw_ctx,
                )
                if mw_decision is not None:
                    if mw_decision.patched_content is not None:
                        message = _patch_tool_message_content(message, mw_decision.patched_content)
                    if mw_decision.patched_error is not None:
                        message = _patch_tool_message_error(message, mw_decision.patched_error)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Middleware intercept_tool_result failed for tool=%s",
                tool_name,
                exc_info=True,
            )

        try:
            if have_ext:
                from ...harness.extensions import ToolResultInterception as ExtResultInterception

                ext_hooks = services.extension_registry.fire_hook(
                    "on_tool_result",
                    ext_ctx,
                    tool_name=tool_name,
                    result=message,
                )
                for result_hook in ext_hooks:
                    if isinstance(result_hook, ExtResultInterception):
                        if result_hook.patched_content is not None:
                            message = _patch_tool_message_content(
                                message, result_hook.patched_content
                            )
                        if result_hook.patched_error is not None:
                            message = _patch_tool_message_error(message, result_hook.patched_error)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Extension on_tool_result hook failed for tool=%s",
                tool_name,
                exc_info=True,
            )

        patched_results.append(
            ToolExecutionResult(
                index=result.index,
                message=message,
                cache_hit=getattr(result, "cache_hit", False),
            )
        )
    return patched_results


__all__ = [
    "_apply_result_hooks",
    "_patch_tool_message_content",
    "_patch_tool_message_error",
]
