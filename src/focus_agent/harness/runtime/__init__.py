"""Runtime lifecycle and configuration primitives for the Focus Agent harness."""

from .config import HarnessConfig, RuntimeFeatures
from .rollback import (
    CheckpointRollbackResult,
    CheckpointRollbackTarget,
    capture_checkpoint_rollback_target,
    restore_graph_rollback_target,
)
from .runs import (
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

__all__ = [
    "DisconnectMode",
    "HarnessConfig",
    "CheckpointRollbackResult",
    "CheckpointRollbackTarget",
    "MultitaskStrategy",
    "RunManager",
    "RunLifecyclePublisher",
    "RunRecord",
    "RunConflictError",
    "RunRequest",
    "RunStatus",
    "RuntimeFeatures",
    "UnsupportedStrategyError",
    "capture_checkpoint_rollback_target",
    "restore_graph_rollback_target",
]
