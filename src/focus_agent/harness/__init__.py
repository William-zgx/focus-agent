"""Harness utilities for Focus Agent runtime experiments."""

from importlib import import_module
from typing import Any

_MODULE_EXPORTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        ".agents.facade",
        (
            "FocusAgent",
            "StreamResult",
        ),
    ),
    (
        ".agents.mention",
        (
            "Mention",
            "extract_primary_agent",
            "list_available_agents",
            "parse_mentions",
            "resolve_mentions",
            "strip_mentions",
        ),
    ),
    (
        ".middleware",
        (
            "AgentMiddleware",
            "BaseAgentMiddleware",
            "CircuitBreaker",
            "CircuitBreakerOpenError",
            "CircuitBreakerSnapshot",
            "DanglingToolCallMiddleware",
            "LLMErrorHandlingMiddleware",
            "LoopDetectedError",
            "LoopDetectionMiddleware",
            "LoopDetectionResult",
            "MiddlewareError",
            "MiddlewareHandler",
            "MiddlewareStack",
        ),
    ),
    (
        ".observability",
        (
            "InMemoryRunJournal",
            "JournaledStreamBridge",
            "JournalEvent",
            "JournalRun",
            "JournalToolEvent",
            "PostgresRunJournal",
            "RunJournal",
            "SQLiteRunJournal",
            "trajectory_summary_from_snapshot",
        ),
    ),
    (
        ".runtime",
        (
            "ConflictError",
            "DisconnectMode",
            "MultitaskStrategy",
            "RunConflictError",
            "RunLifecyclePublisher",
            "RunManager",
            "RunRecord",
            "RunRequest",
            "RunStatus",
            "UnsupportedStrategyError",
        ),
    ),
    (
        ".schemas",
        (
            "AgentStateSlices",
            "BranchStateSlice",
            "CircuitBreakerConfig",
            "ConversationStateSlice",
            "GovernanceStateSlice",
            "HarnessSchemaModel",
            "MemoryStateSlice",
            "ObservabilityStateSlice",
            "RetryConfig",
            "RuntimeFeatures",
            "StateSlice",
            "StateSliceSpec",
            "StreamingConfig",
            "SubagentConfig",
            "build_state_slices",
            "state_slice_dict",
            "state_slice_model",
        ),
    ),
    (
        ".streaming",
        (
            "END_SENTINEL",
            "HEARTBEAT_SENTINEL",
            "AgentEventPublisher",
            "InMemoryStreamBridge",
            "MemoryStreamBridge",
            "StreamEvent",
            "StreamProxy",
            "StreamProxyConfig",
        ),
    ),
    (
        ".subagents",
        ("AgentTeamSubagentRunner",),
    ),
)

_EXPORTS = {
    export_name: (module_name, export_name)
    for module_name, module_exports in _MODULE_EXPORTS
    for export_name in module_exports
}
_EXPORTS.update(
    {
        "FocusAgentHarness": (".agents.factory", "FocusAgentHarness"),
        "HarnessConfig": (".schemas.config", "HarnessConfig"),
        "RuntimeFeatureFlags": (".runtime", "RuntimeFeatures"),
        "RuntimeHarnessConfig": (".runtime", "HarnessConfig"),
    }
)
_LAZY_SUBMODULES = frozenset(
    {
        "agents",
        "middleware",
        "observability",
        "runtime",
        "schemas",
        "streaming",
        "subagents",
    }
)


def create_focus_agent(*args: Any, **kwargs: Any) -> Any:
    from .agents.factory import create_focus_agent as factory

    return factory(*args, **kwargs)


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is not None:
        module_name, attribute_name = target
        value = getattr(import_module(module_name, __name__), attribute_name)
        globals()[name] = value
        return value
    if name in _LAZY_SUBMODULES:
        value = import_module(f".{name}", __name__)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__, *_LAZY_SUBMODULES})


__all__ = [
    "AgentMiddleware",
    "AgentEventPublisher",
    "AgentStateSlices",
    "AgentTeamSubagentRunner",
    "BaseAgentMiddleware",
    "BranchStateSlice",
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitBreakerOpenError",
    "CircuitBreakerSnapshot",
    "ConflictError",
    "ConversationStateSlice",
    "DanglingToolCallMiddleware",
    "DisconnectMode",
    "END_SENTINEL",
    "FocusAgent",
    "FocusAgentHarness",
    "GovernanceStateSlice",
    "HEARTBEAT_SENTINEL",
    "HarnessConfig",
    "HarnessSchemaModel",
    "InMemoryRunJournal",
    "InMemoryStreamBridge",
    "JournalEvent",
    "JournalRun",
    "JournalToolEvent",
    "JournaledStreamBridge",
    "PostgresRunJournal",
    "LLMErrorHandlingMiddleware",
    "LoopDetectedError",
    "LoopDetectionMiddleware",
    "LoopDetectionResult",
    "MemoryStateSlice",
    "MemoryStreamBridge",
    "Mention",
    "MiddlewareError",
    "MiddlewareHandler",
    "MiddlewareStack",
    "MultitaskStrategy",
    "ObservabilityStateSlice",
    "RetryConfig",
    "RunLifecyclePublisher",
    "RunManager",
    "RunRecord",
    "RunJournal",
    "RunConflictError",
    "RunRequest",
    "RunStatus",
    "RuntimeFeatureFlags",
    "RuntimeFeatures",
    "RuntimeHarnessConfig",
    "SQLiteRunJournal",
    "StateSlice",
    "StateSliceSpec",
    "StreamEvent",
    "StreamProxy",
    "StreamProxyConfig",
    "StreamResult",
    "StreamingConfig",
    "SubagentConfig",
    "UnsupportedStrategyError",
    "build_state_slices",
    "create_focus_agent",
    "extract_primary_agent",
    "list_available_agents",
    "parse_mentions",
    "resolve_mentions",
    "state_slice_dict",
    "state_slice_model",
    "strip_mentions",
    "trajectory_summary_from_snapshot",
]
