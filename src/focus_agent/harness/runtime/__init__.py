"""Runtime lifecycle and configuration primitives for the Focus Agent harness."""

from .config import HarnessConfig, RuntimeFeatures
from .recovery import (
    HARNESS_RUN_RECOVERY_KIND,
    HarnessRunRecovery,
    RunHydrationResult,
)
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
    "HARNESS_RUN_RECOVERY_KIND",
    "DisconnectMode",
    "HarnessConfig",
    "HarnessRunRecovery",
    "CheckpointRollbackResult",
    "CheckpointRollbackTarget",
    "MultitaskStrategy",
    "RunManager",
    "RunLifecyclePublisher",
    "RunRecord",
    "RunConflictError",
    "RunHydrationResult",
    "RunRequest",
    "RunStatus",
    "RuntimeFeatures",
    "UnsupportedStrategyError",
    "capture_checkpoint_rollback_target",
    "restore_graph_rollback_target",
]
