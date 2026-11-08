"""Typed exceptions for controlled multi-agent coordination failures."""

from __future__ import annotations


class MultiAgentError(Exception):
    """Base class for controlled multi-agent coordination errors."""


class DeadlockDetected(MultiAgentError):  # noqa: N818 - public compatibility name
    """Raised when resource wait relationships form a cycle."""


__all__ = ["DeadlockDetected", "MultiAgentError"]
