from __future__ import annotations

from typing import Literal, Protocol

from pydantic import Field

from .delegation_models import AgentArtifact, AgentRun, AgentTask
from .execution_modes import DelegationExecutionMode
from .roles import AgentRole
from ..core.types import StateModel


class SubagentConfig(StateModel):
    role: AgentRole
    model_id: str
    allowed_tools: list[str] = Field(default_factory=list)
    max_turns: int = 1
    timeout_seconds: int = 30
    max_depth: int = 1
    requires_workspace_write: bool = False
    requires_network: bool = False
    context_refs: list[dict[str, object]] = Field(default_factory=list)
    run_isolation_key: str = ""
    workspace_id: str | None = None
    workspace_path: str | None = None
    workspace_branch: str | None = None
    base_commit: str | None = None


class SubagentRunResult(StateModel):
    run_id: str
    task_id: str
    role: AgentRole
    status: Literal["completed", "failed", "skipped", "needs_review"] = "completed"
    summary: str = ""
    artifacts: list[AgentArtifact] = Field(default_factory=list)
    error: str | None = None
    tool_calls: int = 0
    cost: float = 0.0
    model_id: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    execution_mode: DelegationExecutionMode = "fake"
    workspace_id: str | None = None
    workspace_path: str | None = None
    workspace_branch: str | None = None
    base_commit: str | None = None
    changed_files: list[str] = Field(default_factory=list)
    diff_summary: str | None = None
    test_evidence: list[str] = Field(default_factory=list)
    workspace_status: str | None = None

    def to_agent_run(self) -> AgentRun:
        return AgentRun(
            run_id=self.run_id,
            task_id=self.task_id,
            role=self.role,
            status=self.status,
            model_id=self.model_id,
            started_at=self.started_at,
            finished_at=self.finished_at,
            tool_calls=self.tool_calls,
            cost=self.cost,
            artifacts=list(self.artifacts),
            error=self.error,
            execution_mode=self.execution_mode,
        )


class DelegatedRunExecutor(Protocol):
    mode: DelegationExecutionMode

    def execute(self, task: AgentTask, config: SubagentConfig) -> SubagentRunResult: ...


__all__ = [
    "DelegatedRunExecutor",
    "SubagentConfig",
    "SubagentRunResult",
]
