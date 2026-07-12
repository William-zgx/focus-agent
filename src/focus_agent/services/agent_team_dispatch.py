"""Compatibility forwarding for the canonical Agent Team dispatch implementation."""

from .agent_team.service import _DEFAULT_DISPATCH_TASKS, AgentTeamDispatchMixin

__all__ = ["AgentTeamDispatchMixin", "_DEFAULT_DISPATCH_TASKS"]
