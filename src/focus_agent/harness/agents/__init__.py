"""Public harness agent APIs with lazy compatibility exports."""

from importlib import import_module
from typing import Any

_EXPORTS = {
    "FocusAgent": (".facade", "FocusAgent"),
    "FocusAgentHarness": (".factory", "FocusAgentHarness"),
    "Mention": (".mention", "Mention"),
    "StreamResult": (".facade", "StreamResult"),
    "create_focus_agent": (".factory", "create_focus_agent"),
    "extract_primary_agent": (".mention", "extract_primary_agent"),
    "list_available_agents": (".mention", "list_available_agents"),
    "parse_mentions": (".mention", "parse_mentions"),
    "resolve_mentions": (".mention", "resolve_mentions"),
    "strip_mentions": (".mention", "strip_mentions"),
}

__all__ = [
    "FocusAgent",
    "FocusAgentHarness",
    "Mention",
    "StreamResult",
    "create_focus_agent",
    "extract_primary_agent",
    "list_available_agents",
    "parse_mentions",
    "resolve_mentions",
    "strip_mentions",
]


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})
