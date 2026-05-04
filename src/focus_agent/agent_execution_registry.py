from __future__ import annotations

from typing import Any

from pydantic import Field

from .agent_delegation_models import AgentTask
from .agent_execution_modes import DelegationExecutionMode, ModelFactory
from .agent_execution_types import DelegatedRunExecutor, SubagentConfig
from .agent_roles import AgentRole, RoleModelResolver
from .config import Settings
from .core.types import StateModel


class SubagentRegistry(StateModel):
    configs: dict[AgentRole, SubagentConfig] = Field(default_factory=dict)

    @classmethod
    def from_settings(
        cls, settings: Settings | Any, *, context_refs: list[dict[str, Any]] | None = None
    ) -> "SubagentRegistry":
        resolver = RoleModelResolver(settings)
        refs = list(context_refs or [])
        configs = {
            role: SubagentConfig(
                role=role,
                model_id=resolver.resolve(role),
                max_turns=_safe_positive_int(
                    getattr(settings, "agent_subagent_max_turns", 1), default=1
                ),
                timeout_seconds=_safe_positive_int(
                    getattr(settings, "agent_subagent_timeout_seconds", 30),
                    default=30,
                ),
                max_depth=_safe_non_negative_int(
                    getattr(settings, "agent_subagent_max_depth", 1), default=1
                ),
                context_refs=refs,
                run_isolation_key=f"role:{role.value}",
            )
            for role in AgentRole
        }
        return cls(configs=configs)

    def config_for(self, task: AgentTask) -> SubagentConfig:
        base = self.configs.get(task.role) or SubagentConfig(
            role=task.role, model_id="", run_isolation_key=f"role:{task.role.value}"
        )
        return base.model_copy(
            update={
                "allowed_tools": list(task.allowed_tools),
                "max_turns": task.max_turns,
                "timeout_seconds": task.timeout_seconds,
                "max_depth": task.max_depth,
                "requires_workspace_write": task.requires_workspace_write,
                "requires_network": task.requires_network,
                "context_refs": list(task.context_refs),
                "run_isolation_key": task.run_isolation_key or base.run_isolation_key,
            }
        )


def executor_for_mode(
    mode: DelegationExecutionMode,
    *,
    model: Any | None = None,
    model_factory: ModelFactory | None = None,
    settings: Settings | None = None,
    max_workers: int | None = None,
) -> DelegatedRunExecutor | None:
    from .agent_execution_executors import (
        BackgroundDelegatedRunExecutor,
        FakeDelegatedRunExecutor,
        InlineDelegatedRunExecutor,
    )

    if mode == "observe":
        return None
    if mode == "fake":
        return FakeDelegatedRunExecutor()
    if mode == "inline":
        return InlineDelegatedRunExecutor(
            model=model, model_factory=model_factory, settings=settings
        )
    return BackgroundDelegatedRunExecutor(
        model=model, model_factory=model_factory, settings=settings, max_workers=max_workers
    )


def _safe_positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, parsed)


def _safe_non_negative_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, parsed)


__all__ = [
    "SubagentRegistry",
    "executor_for_mode",
]
