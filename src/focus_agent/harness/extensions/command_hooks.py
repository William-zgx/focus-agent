from __future__ import annotations

import fnmatch
import json
import logging
import subprocess
from typing import Any

from . import BaseExtension, ExtensionContext, ToolInterceptionResult, ToolResultInterception

logger = logging.getLogger(__name__)

_TOOL_RESULT_CLIP_CHARS = 4000


class CommandHooksExtension(BaseExtension):
    """Run administrator-configured commands at the existing tool hook points."""

    name = "command_hooks"
    version = "1.0.0"

    def __init__(
        self, *, pre_tool_use: tuple[Any, ...] = (), post_tool_use: tuple[Any, ...] = ()
    ) -> None:
        self._pre_tool_use = pre_tool_use
        self._post_tool_use = post_tool_use

    def on_tool_call(
        self,
        ctx: ExtensionContext,
        tool_name: str,
        args: dict[str, Any],
    ) -> ToolInterceptionResult | None:
        for hook in self._pre_tool_use:
            if not fnmatch.fnmatch(tool_name, hook.matcher):
                continue
            completed = _run_hook(
                hook,
                event_name="pre_tool_use",
                ctx=ctx,
                tool_name=tool_name,
                tool_input=args,
            )
            if completed is None:
                continue
            if completed.returncode == 2:
                return ToolInterceptionResult(
                    block=True,
                    reason=completed.stderr.strip() or "blocked by pre_tool_use hook (exit 2)",
                )
            if completed.returncode != 0:
                _log_nonzero_exit("pre_tool_use", tool_name, completed.returncode)
                continue
            output = _stdout_json(completed.stdout)
            if output.get("decision") == "block":
                reason = output.get("reason")
                return ToolInterceptionResult(
                    block=True,
                    reason=str(reason).strip() if reason else "blocked by pre_tool_use hook",
                )
        return None

    def on_tool_result(
        self,
        ctx: ExtensionContext,
        tool_name: str,
        result: Any,
    ) -> ToolResultInterception | None:
        additional_context: list[str] = []
        for hook in self._post_tool_use:
            if not fnmatch.fnmatch(tool_name, hook.matcher):
                continue
            completed = _run_hook(
                hook,
                event_name="post_tool_use",
                ctx=ctx,
                tool_name=tool_name,
                tool_input=dict(ctx.extra.get("tool_input") or {}),
                tool_result=_clip_content(result.content),
                status=str(getattr(result, "status", "success") or "success"),
            )
            if completed is None:
                continue
            if completed.returncode != 0:
                _log_nonzero_exit("post_tool_use", tool_name, completed.returncode)
                continue
            context = _stdout_json(completed.stdout).get("additional_context")
            if isinstance(context, str) and context.strip():
                additional_context.append(context.strip())
        if not additional_context:
            return None
        original = _content_text(result.content)
        patched_content = "\n\n".join([*([original] if original else []), *additional_context])
        return ToolResultInterception(patched_content=patched_content)


def _run_hook(
    hook: Any,
    *,
    event_name: str,
    ctx: ExtensionContext,
    tool_name: str,
    tool_input: dict[str, Any],
    **extra: Any,
) -> subprocess.CompletedProcess[str] | None:
    payload = {
        "event": event_name,
        "tool_name": tool_name,
        "tool_input": tool_input,
        "thread_id": ctx.thread_id,
        "run_id": ctx.run_id,
        **extra,
    }
    try:
        return subprocess.run(
            list(hook.command),
            input=json.dumps(payload, ensure_ascii=False, default=str),
            text=True,
            capture_output=True,
            shell=False,
            timeout=hook.timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logger.warning(
            "Command hook timed out event=%s tool=%s timeout_seconds=%s",
            event_name,
            tool_name,
            hook.timeout_seconds,
        )
    except OSError as exc:
        logger.warning(
            "Command hook could not start event=%s tool=%s error=%s",
            event_name,
            tool_name,
            exc,
        )
    return None


def _stdout_json(stdout: str) -> dict[str, Any]:
    try:
        payload = json.loads(stdout.strip() or "{}")
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, default=str)


def _clip_content(content: Any) -> str:
    text = _content_text(content)
    if len(text) <= _TOOL_RESULT_CLIP_CHARS:
        return text
    return f"{text[:_TOOL_RESULT_CLIP_CHARS]}..."


def _log_nonzero_exit(event_name: str, tool_name: str, returncode: int) -> None:
    logger.warning(
        "Command hook failed event=%s tool=%s exit_code=%d",
        event_name,
        tool_name,
        returncode,
    )


__all__ = ["CommandHooksExtension"]
