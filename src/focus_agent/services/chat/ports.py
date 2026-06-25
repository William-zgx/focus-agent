from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..coordination import CoordinationBackend


@dataclass(frozen=True)
class ChatServicePorts:
    settings: Any
    graph: Any
    repo: Any
    branch_service: Any | None = None
    branch_decision_service: Any | None = None
    skill_registry: Any | None = None
    trajectory_recorder: Any | None = None
    retrieval_index: Any | None = None
    memory_embedding_provider: Any | None = None
    checkpointer: Any | None = None
    background_work: Any | None = None
    coordination_backend: CoordinationBackend | None = None

    @classmethod
    def from_runtime(cls, runtime: Any) -> ChatServicePorts:
        return cls(
            settings=runtime.settings,
            graph=runtime.graph,
            repo=runtime.repo,
            branch_service=getattr(runtime, "branch_service", None),
            branch_decision_service=getattr(runtime, "branch_decision_service", None),
            skill_registry=getattr(runtime, "skill_registry", None),
            trajectory_recorder=getattr(runtime, "trajectory_recorder", None),
            retrieval_index=getattr(runtime, "retrieval_index", None),
            memory_embedding_provider=getattr(runtime, "memory_embedding_provider", None),
            checkpointer=getattr(runtime, "checkpointer", None),
            background_work=getattr(runtime, "background_work", None),
            coordination_backend=getattr(runtime, "coordination_backend", None),
        )
