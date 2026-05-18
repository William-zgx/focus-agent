"""Typed exceptions for controlled multi-agent coordination failures."""

from __future__ import annotations


class MultiAgentError(Exception):
    """Base class for controlled multi-agent coordination errors."""


class DAGValidationError(MultiAgentError):
    """Raised when task dependencies cannot form a valid DAG."""


class ResourceLockTimeout(MultiAgentError):
    """Raised when a resource lock cannot be acquired in time."""


class DeadlockDetected(MultiAgentError):
    """Raised when resource wait relationships form a cycle."""


class ApprovalTimeout(MultiAgentError):
    """Raised when an approval request reaches its timeout."""


class MergeConflictBlocking(MultiAgentError):
    """Raised when merge conflict detection finds a blocking conflict."""


__all__ = [
    "ApprovalTimeout",
    "DAGValidationError",
    "DeadlockDetected",
    "MergeConflictBlocking",
    "MultiAgentError",
    "ResourceLockTimeout",
]
