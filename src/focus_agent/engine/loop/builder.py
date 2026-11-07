"""Graph for the model-driven core (``AGENT_CORE=v2``).

bootstrap_turn -> retrieve_memory -> assemble_context -> agent_loop
agent_loop <-> tool_executor
agent_loop -> summarize_turn -> extract_memories -> write_memories
           -> maybe_interrupt_for_merge -> END
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from ...capabilities import ToolRegistry
from ...capabilities.tool_manifest import ToolManifest
from ...config import Settings
from ...core.request_context import RequestContext
from ...core.state import AgentState
from ...memory import MemoryExtractor, MemoryPolicy, MemoryRetriever, MemoryWriter
from ...skills import SkillRegistry
from ..graph.components import (
    GraphComponents,
    make_graph_tool_executor,
    resolve_graph_components,
)
from ..graph.memory_nodes import (
    make_assemble_context_node,
    make_extract_memories_node,
    make_retrieve_memory_node,
    make_write_memories_node,
)
from ..graph.tool_call_repair import _known_tool_names
from ..graph.tool_execution import HarnessToolServices
from ..graph.turn_hooks import TurnLifecycle
from .agent import make_loop_agent_node
from .compaction import make_model_compaction_summarizer
from .todos import TODO_WRITE_TOOL_NAME, build_todo_write_tool


def _route_after_agent(state: AgentState) -> Literal["tool_executor", "summarize_turn"]:
    if getattr(state["messages"][-1], "tool_calls", None):
        return "tool_executor"
    return "summarize_turn"


def _with_todo_write(components: GraphComponents) -> GraphComponents:
    registry = components.tool_registry
    if TODO_WRITE_TOOL_NAME in registry.by_name:
        return components
    todo_write = build_todo_write_tool()
    registry = ToolRegistry(
        tools=(*registry.tools, todo_write),
        manifests=(*registry.manifests, ToolManifest.from_tool(todo_write)),
    )
    return replace(components, tool_registry=registry, tools=list(registry.tools))


def build_loop_graph(
    *,
    settings: Settings,
    chat_model_factory: Callable[..., Any],
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
    system_agent_runner: Any | None = None,
    agent_definition_registry: Any | None = None,
):
    components = _with_todo_write(
        resolve_graph_components(
            settings=settings,
            checkpointer=checkpointer,
            store=store,
            memory_retriever=memory_retriever,
            memory_policy=memory_policy,
            memory_writer=memory_writer,
            memory_extractor=memory_extractor,
            skill_registry=skill_registry,
            tool_registry=tool_registry,
            chat_model_factory=chat_model_factory,
        )
    )
    lifecycle = TurnLifecycle(
        harness_services=harness_services,
        system_agent_runner=system_agent_runner,
        summarize=make_model_compaction_summarizer(
            settings=settings,
            model_for=components.model_for,
            known_tool_names=_known_tool_names(components.tools),
            available_tools=components.tools,
        ),
    )

    builder = StateGraph(AgentState, context_schema=RequestContext)
    builder.add_node("bootstrap_turn", lifecycle.bootstrap_turn)
    builder.add_node("retrieve_memory", make_retrieve_memory_node(components.memory_retriever))
    builder.add_node(
        "assemble_context",
        make_assemble_context_node(settings=settings, skill_registry=components.skill_registry),
    )
    builder.add_node(
        "agent_loop",
        make_loop_agent_node(
            settings=settings,
            tools=components.tools,
            model_for=components.model_for,
            model_with_tools_for=components.model_with_tools_for,
            run_manager=run_manager,
            agent_definition_registry=agent_definition_registry,
        ),
    )
    builder.add_node(
        "tool_executor",
        make_graph_tool_executor(
            settings=settings,
            components=components,
            approval_queue=approval_queue,
            harness_services=harness_services,
        ),
    )
    builder.add_node("summarize_turn", lifecycle.summarize_turn)
    builder.add_node("extract_memories", make_extract_memories_node(components.memory_extractor))
    builder.add_node("write_memories", make_write_memories_node(components.memory_writer))
    builder.add_node("maybe_interrupt_for_merge", lifecycle.maybe_interrupt_for_merge)

    builder.add_edge(START, "bootstrap_turn")
    builder.add_edge("bootstrap_turn", "retrieve_memory")
    builder.add_edge("retrieve_memory", "assemble_context")
    builder.add_edge("assemble_context", "agent_loop")
    builder.add_conditional_edges(
        "agent_loop", _route_after_agent, ["tool_executor", "summarize_turn"]
    )
    builder.add_edge("tool_executor", "agent_loop")
    builder.add_edge("summarize_turn", "extract_memories")
    builder.add_edge("extract_memories", "write_memories")
    builder.add_edge("write_memories", "maybe_interrupt_for_merge")
    builder.add_edge("maybe_interrupt_for_merge", END)

    return builder.compile(checkpointer=checkpointer, store=store)


__all__ = ["build_loop_graph"]
