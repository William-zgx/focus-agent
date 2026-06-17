from __future__ import annotations

import functools
import inspect
from dataclasses import dataclass
from typing import Any

from ...core.tool_call_protocol import repair_dangling_tool_call_messages
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
        return repair_dangling_tool_call_messages(
            messages,
            repair_trailing=self.repair_trailing,
            error_message=self.error_message,
        )


def _same_message_objects(left: list[Any], right: list[Any]) -> bool:
    return len(left) == len(right) and all(a is b for a, b in zip(left, right))


__all__ = ["DanglingToolCallMiddleware"]
