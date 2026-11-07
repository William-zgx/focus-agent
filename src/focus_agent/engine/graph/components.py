"""Registries, memory services and tool execution shared by every agent core."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ...capabilities import ToolRegistry, build_tool_registry
from ...capabilities.tool_runtime import ToolResultCacheStore
from ...config import Settings
from ...memory import MemoryExtractor, MemoryPolicy, MemoryRetriever, MemoryWriter
from ...skills import SkillRegistry
from ..model_factory import GraphModelFactory
from .tool_execution import HarnessToolServices, make_tool_executor_node


@dataclass(frozen=True)
class GraphComponents:
    skill_registry: SkillRegistry
    tool_registry: ToolRegistry
    tools: list[Any]
    memory_retriever: MemoryRetriever
    memory_writer: MemoryWriter
    memory_extractor: MemoryExtractor
    model_factory: GraphModelFactory

    def model_for(self, model_id: str, thinking_mode: str) -> Any:
        return self.model_factory.model_for(model_id, thinking_mode)

    def model_with_tools_for(
        self, model_id: str, thinking_mode: str, available_tools: list[Any] | None = None
    ) -> Any:
        return self.model_factory.model_with_tools_for(
            model_id,
            thinking_mode,
            default_tools=self.tools,
            available_tools=available_tools,
        )


def resolve_graph_components(
    *,
    settings: Settings,
    checkpointer: Any,
    store: Any,
    memory_retriever: MemoryRetriever | None,
    memory_policy: MemoryPolicy | None,
    memory_writer: MemoryWriter | None,
    memory_extractor: MemoryExtractor | None,
    skill_registry: SkillRegistry | None,
    tool_registry: ToolRegistry | None,
    chat_model_factory: Callable[..., Any],
) -> GraphComponents:
    effective_skill_registry = skill_registry or SkillRegistry.from_settings(settings)
    effective_tool_registry = tool_registry or build_tool_registry(
        settings=settings,
        skill_registry=effective_skill_registry,
        store=store,
        checkpointer=checkpointer,
    )
    effective_memory_policy = (
        memory_policy or getattr(memory_retriever, "policy", None) or MemoryPolicy()
    )
    return GraphComponents(
        skill_registry=effective_skill_registry,
        tool_registry=effective_tool_registry,
        tools=list(effective_tool_registry.tools),
        memory_retriever=memory_retriever
        or MemoryRetriever(store=store, policy=effective_memory_policy),
        memory_writer=memory_writer or MemoryWriter(store=store, policy=effective_memory_policy),
        memory_extractor=memory_extractor or MemoryExtractor(),
        model_factory=GraphModelFactory(settings=settings, chat_model_factory=chat_model_factory),
    )


def make_graph_tool_executor(
    *,
    settings: Settings,
    components: GraphComponents,
    approval_queue: Any | None,
    harness_services: HarnessToolServices | None,
) -> Any:
    return make_tool_executor_node(
        tools_by_name=components.tool_registry.by_name,
        tool_runtime_by_name=components.tool_registry.runtime_by_name,
        tool_result_cache=ToolResultCacheStore(),
        max_parallel_workers=settings.tool_max_parallel_workers,
        multi_agent_async_approval_enabled=bool(
            settings.multi_agent_v2_enabled and settings.multi_agent_async_approval_enabled
        ),
        multi_agent_approval_timeout_seconds=settings.multi_agent_approval_timeout_seconds,
        approval_queue=approval_queue,
        harness_services=harness_services,
    )


__all__ = ["GraphComponents", "make_graph_tool_executor", "resolve_graph_components"]
