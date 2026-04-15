"""Compatibility shim.

Canonical import:
    from focus_agent.core.state import (
        AgentState,
        initial_agent_state,
        normalize_agent_state,
        serialize_agent_state,
    )
"""

from .core.state import AgentState, initial_agent_state, normalize_agent_state, serialize_agent_state

__all__ = [
    "AgentState",
    "initial_agent_state",
    "normalize_agent_state",
    "serialize_agent_state",
]
