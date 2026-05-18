from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, TypeAlias, runtime_checkable

MiddlewareHandler: TypeAlias = Callable[..., Any]


@runtime_checkable
class AgentMiddleware(Protocol):
    """Protocol for wrappers around graph or model callables."""

    def wrap(self, handler: MiddlewareHandler) -> MiddlewareHandler:
        """Return a callable with this middleware applied."""
        ...


class BaseAgentMiddleware:
    """No-op base class for middleware implementations."""

    def wrap(self, handler: MiddlewareHandler) -> MiddlewareHandler:
        return handler


@dataclass(frozen=True, slots=True)
class MiddlewareStack:
    """Apply middleware in declaration order around a callable."""

    middlewares: tuple[AgentMiddleware, ...] = ()

    def __init__(self, middlewares: Iterable[AgentMiddleware] = ()) -> None:
        object.__setattr__(self, "middlewares", tuple(middlewares))

    def wrap(self, handler: MiddlewareHandler) -> MiddlewareHandler:
        wrapped = handler
        for middleware in reversed(self.middlewares):
            wrapped = middleware.wrap(wrapped)
        return wrapped

    def invoke(self, handler: MiddlewareHandler, *args: Any, **kwargs: Any) -> Any:
        return self.wrap(handler)(*args, **kwargs)

    def __call__(self, handler: MiddlewareHandler) -> MiddlewareHandler:
        return self.wrap(handler)

    def append(self, middleware: AgentMiddleware) -> MiddlewareStack:
        return MiddlewareStack((*self.middlewares, middleware))

    def extend(self, middlewares: Iterable[AgentMiddleware]) -> MiddlewareStack:
        return MiddlewareStack((*self.middlewares, *tuple(middlewares)))


def state_from_call(args: tuple[Any, ...], kwargs: Mapping[str, Any]) -> Any | None:
    if "state" in kwargs:
        return kwargs["state"]
    if args:
        return args[0]
    return None


def replace_state_in_call(
    args: tuple[Any, ...],
    kwargs: Mapping[str, Any],
    state: Any,
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    updated_kwargs = dict(kwargs)
    if "state" in updated_kwargs:
        updated_kwargs["state"] = state
        return args, updated_kwargs
    if args:
        return (state, *args[1:]), updated_kwargs
    updated_kwargs["state"] = state
    return args, updated_kwargs


def messages_from_state(state: Any) -> list[Any] | None:
    if isinstance(state, Mapping):
        messages = state.get("messages")
    else:
        messages = getattr(state, "messages", None)
    if messages is None:
        return None
    return list(messages)


def copy_state_with_messages(state: Any, messages: list[Any]) -> Any:
    if isinstance(state, dict):
        updated = dict(state)
        updated["messages"] = messages
        return updated
    if isinstance(state, Mapping):
        updated = dict(state)
        updated["messages"] = messages
        return updated
    if hasattr(state, "model_copy"):
        return state.model_copy(update={"messages": messages})
    updated = state
    updated.messages = messages
    return updated


def messages_from_result(result: Any) -> list[Any]:
    if isinstance(result, Mapping):
        messages = result.get("messages")
        return list(messages or [])
    if isinstance(result, list):
        return list(result)
    if result is None:
        return []
    if getattr(result, "type", None) in {"ai", "human", "tool", "system"}:
        return [result]
    return []


__all__ = [
    "AgentMiddleware",
    "BaseAgentMiddleware",
    "MiddlewareHandler",
    "MiddlewareStack",
    "copy_state_with_messages",
    "messages_from_result",
    "messages_from_state",
    "replace_state_in_call",
    "state_from_call",
]
