"""Controlled multi-agent coordination primitives.

The package is intentionally feature-flag friendly: pure in-memory
implementations live here first so Agent Team can opt in without changing the
legacy execution path.
"""

from .approval_queue import InMemoryApprovalQueue, PostgresApprovalQueue
from .conflict_detector import MergeConflictDetector
from .dag_scheduler import DAGScheduler
from .failure_handler import FailureHandler
from .maintenance import run_multi_agent_maintenance
from .message_bus import InMemoryAgentMessageBus, PostgresAgentMessageBus
from .resource_lock import InMemoryResourceLockManager, PostgresResourceLockManager

__all__ = [
    "DAGScheduler",
    "FailureHandler",
    "InMemoryAgentMessageBus",
    "InMemoryApprovalQueue",
    "InMemoryResourceLockManager",
    "MergeConflictDetector",
    "PostgresAgentMessageBus",
    "PostgresApprovalQueue",
    "PostgresResourceLockManager",
    "run_multi_agent_maintenance",
]
