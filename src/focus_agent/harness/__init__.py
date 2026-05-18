"""Harness utilities for Focus Agent runtime experiments."""

from typing import Any

from . import schemas as _schemas
from .middleware import (
    AgentMiddleware,
    BaseAgentMiddleware,
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitBreakerSnapshot,
    DanglingToolCallMiddleware,
    LLMErrorHandlingMiddleware,
    LoopDetectedError,
    LoopDetectionMiddleware,
    LoopDetectionResult,
    MiddlewareError,
    MiddlewareHandler,
    MiddlewareStack,
)
from .observability import (
    InMemoryRunJournal,
    JournaledStreamBridge,
    JournalEvent,
    JournalRun,
    JournalToolEvent,
    PostgresRunJournal,
    RunJournal,
    SQLiteRunJournal,
    trajectory_summary_from_snapshot,
)
from .runtime import (
    ConflictError,
    DisconnectMode,
    MultitaskStrategy,
    RunConflictError,
    RunLifecyclePublisher,
    RunManager,
    RunRecord,
    RunRequest,
    RunStatus,
    UnsupportedStrategyError,
)
from .runtime import (
    HarnessConfig as RuntimeHarnessConfig,
)
from .runtime import (
    RuntimeFeatures as RuntimeFeatureFlags,
)
from .schemas import (
    AgentStateSlices,
    BranchStateSlice,
    CircuitBreakerConfig,
    ConversationStateSlice,
    GovernanceStateSlice,
    HarnessSchemaModel,
    MemoryStateSlice,
    ObservabilityStateSlice,
    RetryConfig,
    RuntimeFeatures,
    StateSlice,
    StateSliceSpec,
    StreamingConfig,
    SubagentConfig,
    build_state_slices,
    state_slice_dict,
    state_slice_model,
)
from .schemas.config import HarnessConfig
from .streaming import (
    END_SENTINEL,
    HEARTBEAT_SENTINEL,
    InMemoryStreamBridge,
    MemoryStreamBridge,
    StreamEvent,
)
from .subagents import AgentTeamSubagentRunner

if not hasattr(_schemas, "HarnessConfig"):
    _schemas.HarnessConfig = HarnessConfig


def create_focus_agent(*args: Any, **kwargs: Any) -> Any:
    from .agents.factory import create_focus_agent as factory

    return factory(*args, **kwargs)


def __getattr__(name: str) -> Any:
    if name == "FocusAgentHarness":
        from .agents.factory import FocusAgentHarness

        return FocusAgentHarness
    raise AttributeError(name)


__all__ = [
    "AgentMiddleware",
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
    "StreamingConfig",
    "SubagentConfig",
    "UnsupportedStrategyError",
    "build_state_slices",
    "create_focus_agent",
    "state_slice_dict",
    "state_slice_model",
    "trajectory_summary_from_snapshot",
]
