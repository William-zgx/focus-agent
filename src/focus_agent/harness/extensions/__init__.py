from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(slots=True)
class ToolInterceptionResult:
    """Returned by ``on_tool_call`` to modify or block a tool invocation."""

    block: bool = False
    reason: str | None = None
    patched_args: dict[str, Any] | None = None


@dataclass(slots=True)
class ToolResultInterception:
    """Returned by ``on_tool_result`` to modify or terminate after a tool call."""

    patched_content: Any = None
    patched_error: str | None = None
    terminate: bool = False


@dataclass(slots=True)
class CompactionInterception:
    """Returned by ``on_compaction`` to control context compaction."""

    cancel: bool = False
    custom_summary: str | None = None


@dataclass(slots=True)
class ExtensionContext:
    """Context passed to every extension hook."""

    thread_id: str
    run_id: str | None = None
    agent_name: str | None = None
    model: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Extension(Protocol):
    """Protocol that third-party extensions must implement.

    All hooks are optional; implement only what you need. The
    :class:`BaseExtension` class provides no-op defaults for every hook
    so subclasses can override selectively.
    """

    name: str
    version: str

    # ---- discovery ---------------------------------------------------
    def tools(self) -> list[Any]:
        """Return additional ``BaseTool`` instances to register."""
        ...

    def agent_definitions(self) -> list[Any]:
        """Return additional ``AgentDefinition`` instances to register."""
        ...

    # ---- lifecycle ---------------------------------------------------
    def on_agent_start(self, ctx: ExtensionContext) -> None: ...

    def on_agent_end(self, ctx: ExtensionContext) -> None: ...

    # ---- tool interception ------------------------------------------
    def on_tool_call(
        self,
        ctx: ExtensionContext,
        tool_name: str,
        args: dict[str, Any],
    ) -> ToolInterceptionResult | None: ...

    def on_tool_result(
        self,
        ctx: ExtensionContext,
        tool_name: str,
        result: Any,
    ) -> ToolResultInterception | None: ...

    # ---- message interception ---------------------------------------
    def on_message(
        self,
        ctx: ExtensionContext,
        role: str,
        content: Any,
    ) -> str | None:
        """Return a replacement string for *content*, or ``None`` to leave it."""
        ...

    # ---- compaction --------------------------------------------------
    def on_compaction(
        self,
        ctx: ExtensionContext,
        messages: list[Any],
    ) -> CompactionInterception | None: ...


class BaseExtension:
    """No-op default implementation of :class:`Extension`."""

    name: str = "base"
    version: str = "0.1.0"

    def tools(self) -> list[Any]:
        return []

    def agent_definitions(self) -> list[Any]:
        return []

    def on_agent_start(self, ctx: ExtensionContext) -> None:  # noqa: D401
        return None

    def on_agent_end(self, ctx: ExtensionContext) -> None:  # noqa: D401
        return None

    def on_tool_call(
        self,
        ctx: ExtensionContext,
        tool_name: str,
        args: dict[str, Any],
    ) -> ToolInterceptionResult | None:
        return None

    def on_tool_result(
        self,
        ctx: ExtensionContext,
        tool_name: str,
        result: Any,
    ) -> ToolResultInterception | None:
        return None

    def on_message(
        self,
        ctx: ExtensionContext,
        role: str,
        content: Any,
    ) -> str | None:
        return None

    def on_compaction(
        self,
        ctx: ExtensionContext,
        messages: list[Any],
    ) -> CompactionInterception | None:
        return None


class ExtensionRegistry:
    """Holds the set of active extensions and dispatches hooks."""

    def __init__(self) -> None:
        self._extensions: dict[str, Extension] = {}

    # ---- registration ------------------------------------------------
    def register(self, ext: Extension) -> None:
        if not hasattr(ext, "name") or not ext.name:
            raise ValueError("Extension must define a non-empty 'name' attribute")
        self._extensions[ext.name] = ext

    def unregister(self, name: str) -> None:
        self._extensions.pop(name, None)

    def get(self, name: str) -> Extension | None:
        return self._extensions.get(name)

    def list_all(self) -> list[Extension]:
        return list(self._extensions.values())

    # ---- collection helpers -----------------------------------------
    def collect_tools(self) -> list[Any]:
        tools: list[Any] = []
        for ext in self._extensions.values():
            try:
                tools.extend(ext.tools() or [])
            except Exception:  # pragma: no cover - defensive
                import logging

                logging.getLogger(__name__).exception(
                    "Extension %r failed to list tools", getattr(ext, "name", "?")
                )
        return tools

    def collect_agent_definitions(self) -> list[Any]:
        defs: list[Any] = []
        for ext in self._extensions.values():
            try:
                defs.extend(ext.agent_definitions() or [])
            except Exception:  # pragma: no cover - defensive
                import logging

                logging.getLogger(__name__).exception(
                    "Extension %r failed to list agent definitions",
                    getattr(ext, "name", "?"),
                )
        return defs

    # ---- hook dispatch ----------------------------------------------
    def fire_hook(
        self,
        event_name: str,
        ctx: ExtensionContext,
        **kwargs: Any,
    ) -> list[Any]:
        """Invoke ``event_name`` on every extension, collecting non-``None`` results."""
        results: list[Any] = []
        for ext in self._extensions.values():
            hook = getattr(ext, event_name, None)
            if hook is None or not callable(hook):
                continue
            try:
                result = hook(ctx, **kwargs)
            except Exception:
                import logging

                logging.getLogger(__name__).exception(
                    "Extension %r raised in hook %s",
                    getattr(ext, "name", "?"),
                    event_name,
                )
                continue
            if result is not None:
                results.append(result)
        return results


__all__ = [
    "BaseExtension",
    "CompactionInterception",
    "Extension",
    "ExtensionContext",
    "ExtensionRegistry",
    "ToolInterceptionResult",
    "ToolResultInterception",
]
