"""Shared result contract for guarded Agent Team real execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from focus_agent.core.agent_team import AgentTeamTaskStatus


@dataclass(frozen=True, slots=True)
class RealAgentTeamTaskExecution:
    """Normalized real task outcome consumed by the legacy scheduler bridge."""

    final_status: AgentTeamTaskStatus
    run_status: str
    execution_status: str
    task_updates: dict[str, Any]
    output: dict[str, Any] | None
    error: str = ""
