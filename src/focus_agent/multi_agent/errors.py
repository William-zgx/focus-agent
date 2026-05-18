"""Typed exceptions for controlled multi-agent coordination failures."""

from __future__ import annotations


class MultiAgentError(Exception):
    """Base class for controlled multi-agent coordination errors."""


class DAGValidationError(MultiAgentError):
    """Raised when task dependencies cannot form a valid DAG."""


class ResourceLockTimeout(MultiAgentError):  # noqa: N818 - public compatibility name
    """Raised when a resource lock cannot be acquired in time."""


class DeadlockDetected(MultiAgentError):  # noqa: N818 - public compatibility name
    """Raised when resource wait relationships form a cycle."""


class ApprovalTimeout(MultiAgentError):  # noqa: N818 - public compatibility name
    """Raised when an approval request reaches its timeout."""


class MergeConflictBlocking(MultiAgentError):  # noqa: N818 - public compatibility name
    """Raised when merge conflict detection finds a blocking conflict."""


__all__ = [
    "ApprovalTimeout",
    "DAGValidationError",
    "DeadlockDetected",
    "MergeConflictBlocking",
    "MultiAgentError",
    "ResourceLockTimeout",
]
