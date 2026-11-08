from __future__ import annotations

from typing import Any

from ..capabilities import ToolRegistry
from ..config import Settings
from ..memory import MemoryExtractor, MemoryPolicy, MemoryRetriever, MemoryWriter
from ..model_registry import create_chat_model
from ..skills import SkillRegistry
from .graph.tool_execution import HarnessToolServices
from .loop.builder import build_loop_graph


def build_graph(
    *,
    settings: Settings,
    checkpointer: Any = None,
    store: Any = None,
    memory_retriever: MemoryRetriever | None = None,
    memory_policy: MemoryPolicy | None = None,
    memory_writer: MemoryWriter | None = None,
    memory_extractor: MemoryExtractor | None = None,
    skill_registry: SkillRegistry | None = None,
    tool_registry: ToolRegistry | None = None,
    approval_queue: Any | None = None,
    harness_services: HarnessToolServices | None = None,
    run_manager: Any | None = None,
    agent_definition_registry: Any | None = None,
):
    return build_loop_graph(
        settings=settings,
        checkpointer=checkpointer,
        store=store,
        memory_retriever=memory_retriever,
        memory_policy=memory_policy,
        memory_writer=memory_writer,
        memory_extractor=memory_extractor,
        skill_registry=skill_registry,
        tool_registry=tool_registry,
        approval_queue=approval_queue,
        harness_services=harness_services,
        run_manager=run_manager,
        agent_definition_registry=agent_definition_registry,
        chat_model_factory=create_chat_model,
    )


__all__ = ["build_graph", "create_chat_model"]
