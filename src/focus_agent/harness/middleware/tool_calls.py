from __future__ import annotations

import functools
import inspect
import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from langchain.messages import AIMessage, ToolMessage

from .base import (
    BaseAgentMiddleware,
    MiddlewareHandler,
    copy_state_with_messages,
    messages_from_state,
    replace_state_in_call,
    state_from_call,
)


@dataclass(slots=True)
class DanglingToolCallMiddleware(BaseAgentMiddleware):
    """Insert synthetic error tool results for unanswered assistant tool calls."""

    repair_trailing: bool = True
    error_message: str = "Tool call did not produce a result before the next model step."

    def wrap(self, handler: MiddlewareHandler) -> MiddlewareHandler:
        if inspect.iscoroutinefunction(handler):

            @functools.wraps(handler)
            async def async_wrapped(*args: Any, **kwargs: Any) -> Any:
                updated_args, updated_kwargs = self._repair_call_state(args, kwargs)
                return await handler(*updated_args, **updated_kwargs)

            return async_wrapped

        @functools.wraps(handler)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            updated_args, updated_kwargs = self._repair_call_state(args, kwargs)
            return handler(*updated_args, **updated_kwargs)

        return wrapped

    def _repair_call_state(
        self,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> tuple[tuple[Any, ...], dict[str, Any]]:
        state = state_from_call(args, kwargs)
        messages = messages_from_state(state)
        if state is None or messages is None:
            return args, kwargs

        repaired = self.repair_messages(messages)
        if _same_message_objects(messages, repaired):
            return args, kwargs

        updated_state = copy_state_with_messages(state, repaired)
        return replace_state_in_call(args, kwargs, updated_state)

    def repair_messages(self, messages: list[Any]) -> list[Any]:
        repaired: list[Any] = []
        pending: dict[str, dict[str, Any]] = {}
        changed = False

        for message in messages:
            if isinstance(message, ToolMessage):
                call_id = _tool_message_call_id(message)
                if pending and call_id not in pending:
                    repaired.extend(self._missing_tool_messages(pending.values()))
                    pending.clear()
                    changed = True
                elif call_id in pending:
                    pending.pop(call_id, None)
                repaired.append(message)
                continue

            if pending:
                repaired.extend(self._missing_tool_messages(pending.values()))
                pending.clear()
                changed = True

            repaired.append(message)
            if isinstance(message, AIMessage):
                pending = _pending_tool_calls(message)

        if pending and self.repair_trailing:
            repaired.extend(self._missing_tool_messages(pending.values()))
            changed = True

        return repaired if changed else list(messages)

    def _missing_tool_messages(self, calls: Iterable[dict[str, Any]]) -> list[ToolMessage]:
        return [self._missing_tool_message(call) for call in calls]

    def _missing_tool_message(self, call: dict[str, Any]) -> ToolMessage:
        tool_name = str(call.get("name") or "tool")
        payload = {
            "status": "error",
            "tool": tool_name,
            "args": call.get("args") or {},
            "error": self.error_message,
        }
        return ToolMessage(
            content=json.dumps(payload, ensure_ascii=False, default=str),
            tool_call_id=str(call["id"]),
            name=tool_name,
            status="error",
            artifact={
                "runtime": {
                    "dangling_tool_call_repaired": True,
                    "cache_hit": False,
                    "fallback_used": False,
                },
                "tool_name": tool_name,
            },
        )


def _pending_tool_calls(message: AIMessage) -> dict[str, dict[str, Any]]:
    pending: dict[str, dict[str, Any]] = {}
    for index, raw_call in enumerate(getattr(message, "tool_calls", []) or []):
        if not isinstance(raw_call, dict):
            continue
        call_id = str(raw_call.get("id") or "").strip() or f"dangling-tool-call-{index + 1}"
        args = raw_call.get("args")
        if not isinstance(args, dict):
            args = {"_raw_args": args} if args is not None else {}
        pending[call_id] = {
            "id": call_id,
            "name": str(raw_call.get("name") or "tool").strip() or "tool",
            "args": args,
        }
    return pending


def _tool_message_call_id(message: ToolMessage) -> str:
    return str(getattr(message, "tool_call_id", "") or "")


def _same_message_objects(left: list[Any], right: list[Any]) -> bool:
    return len(left) == len(right) and all(a is b for a, b in zip(left, right))


__all__ = ["DanglingToolCallMiddleware"]
