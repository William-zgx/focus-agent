"""Shared graph helpers used by the model-driven agent loop."""

from importlib import import_module
from typing import Any

_EXPORT_MODULES = {
    "HarnessToolServices": ".tool_execution",
    "_apply_result_hooks": ".tool_execution",
    "_patch_tool_message_content": ".tool_execution",
    "_patch_tool_message_error": ".tool_execution",
    "make_tool_executor_node": ".tool_execution",
}
__all__ = list(_EXPORT_MODULES)


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})
