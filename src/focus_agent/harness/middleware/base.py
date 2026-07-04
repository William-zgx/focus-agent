from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, TypeAlias, runtime_checkable

MiddlewareHandler: TypeAlias = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class ToolCallInterception:
    """Instruction returned by ``on_tool_call`` hooks to modify flow.

    Attributes:
        block: If True, the tool call is skipped entirely.
        reason: Human-readable reason for blocking (used in errors/logs).
        patched_args: If provided (and ``block`` is False), replaces the
            args dict passed to the tool.
    """

    block: bool = False
    reason: str | None = None
    patched_args: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ToolResultInterception:
    """Instruction returned by ``on_tool_result`` hooks to modify flow.

    Attributes:
        patched_content: Replacement content for the tool result.
        patched_error: Replacement error (string) for the tool result.
        terminate_loop: If True, signal the driver loop to stop after this tool.
    """

    patched_content: Any | None = None
    patched_error: str | None = None
    terminate_loop: bool = False


@runtime_checkable
class AgentMiddleware(Protocol):
    """Protocol for wrappers around graph or model callables."""

    def wrap(self, handler: MiddlewareHandler) -> MiddlewareHandler:
        """Return a callable with this middleware applied."""
        ...

    # ---- Optional tool-level and lifecycle hooks ---------------------
    # These are optional. ``BaseAgentMiddleware`` provides no-op defaults
    # so concrete middleware classes do not need to implement them.

    def on_tool_call(
        self, ctx: Any, tool_name: str, args: dict
    ) -> ToolCallInterception | None:
        """Intercept a tool call before it is executed.

        Return a ``ToolCallInterception`` to block or patch the call;
        return ``None`` to let the call proceed unchanged.
        """
        return None

    def on_tool_result(
        self, ctx: Any, tool_name: str, result: Any
    ) -> ToolResultInterception | None:
        """Intercept a tool result after execution.

        Return a ``ToolResultInterception`` to patch content/error or
        terminate the run loop; return ``None`` to leave the result
        unchanged.
        """
        return None

    def on_turn_start(self, ctx: Any) -> None:
        """Called at the beginning of an agent turn (before the LLM call)."""

    def on_turn_end(self, ctx: Any) -> None:
        """Called at the end of an agent turn (after LLM/tool chain completes)."""


class BaseAgentMiddleware:
    """No-op base class for middleware implementations."""

    def wrap(self, handler: MiddlewareHandler) -> MiddlewareHandler:
        return handler

    def on_tool_call(
        self, ctx: Any, tool_name: str, args: dict
    ) -> ToolCallInterception | None:
        return None

    def on_tool_result(
        self, ctx: Any, tool_name: str, result: Any
    ) -> ToolResultInterception | None:
        return None

    def on_turn_start(self, ctx: Any) -> None:
        return None

    def on_turn_end(self, ctx: Any) -> None:
        return None


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

    # ---- Tool / lifecycle interception --------------------------------

    def intercept_tool_call(
        self, tool_name: str, args: dict, *, ctx: Any = None
    ) -> ToolCallInterception:
        """Run all ``on_tool_call`` hooks and merge their decisions.

        Merging rules:
          * If any middleware returns ``block=True``, the call is blocked.
            The first block reason (earliest middleware in stack) wins.
          * ``patched_args`` are applied in order; later middleware
            override earlier ones (last-writer-wins).
        """
        block = False
        reason: str | None = None
        patched: dict[str, Any] | None = None
        for mw in self.middlewares:
            hook = getattr(mw, "on_tool_call", None)
            if hook is None:
                continue
            decision = hook(ctx, tool_name, args)
            if decision is None:
                continue
            if decision.block:
                if not block:
                    block = True
                    reason = decision.reason or f"blocked by {type(mw).__name__}"
                continue
            if decision.patched_args is not None:
                if patched is None:
                    patched = dict(decision.patched_args)
                else:
                    patched.update(decision.patched_args)
        if block:
            return ToolCallInterception(block=True, reason=reason)
        if patched is not None:
            return ToolCallInterception(patched_args=patched)
        return ToolCallInterception()

    def intercept_tool_result(
        self, tool_name: str, result: Any, *, ctx: Any = None
    ) -> ToolResultInterception:
        """Run all ``on_tool_result`` hooks and merge their decisions.

        Merging rules:
          * ``patched_content`` / ``patched_error``: last-writer-wins.
          * ``terminate_loop``: sticky (any True => True).
        """
        patched_content: Any = None
        patched_error: str | None = None
        terminate = False
        have_content_patch = False
        have_error_patch = False
        for mw in self.middlewares:
            hook = getattr(mw, "on_tool_result", None)
            if hook is None:
                continue
            decision = hook(ctx, tool_name, result)
            if decision is None:
                continue
            if decision.patched_content is not None:
                patched_content = decision.patched_content
                have_content_patch = True
            if decision.patched_error is not None:
                patched_error = decision.patched_error
                have_error_patch = True
            if decision.terminate_loop:
                terminate = True
        return ToolResultInterception(
            patched_content=patched_content if have_content_patch else None,
            patched_error=patched_error if have_error_patch else None,
            terminate_loop=terminate,
        )

    def on_turn_start(self, ctx: Any = None) -> None:
        """Notify every middleware that a turn is starting."""
        for mw in self.middlewares:
            hook = getattr(mw, "on_turn_start", None)
            if hook is not None:
                hook(ctx)

    def on_turn_end(self, ctx: Any = None) -> None:
        """Notify every middleware that a turn has ended."""
        for mw in self.middlewares:
            hook = getattr(mw, "on_turn_end", None)
            if hook is not None:
                hook(ctx)


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
    "ToolCallInterception",
    "ToolResultInterception",
    "copy_state_with_messages",
    "messages_from_result",
    "messages_from_state",
    "replace_state_in_call",
    "state_from_call",
]
