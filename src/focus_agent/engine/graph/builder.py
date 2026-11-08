from __future__ import annotations

from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from focus_agent.engine.graph.governance_nodes import (
    make_delegation_governance_node,
    make_role_route_dry_run_node,
)
from focus_agent.engine.graph.memory_nodes import (
    make_assemble_context_node,
    make_extract_memories_node,
    make_retrieve_memory_node,
    make_write_memories_node,
)
from focus_agent.engine.graph.plan_nodes import (
    _format_plan_block,
    _parse_plan_json,
    _parse_reflection_json,
    _should_plan,
    make_plan_node,
    make_reflect_node,
    make_should_continue_after_reflect,
)
from focus_agent.engine.graph.textual_tool_call_repair import (
    _looks_like_textual_tool_call_artifact,
    _repair_tool_free_answer_response,
)
from focus_agent.engine.graph.tool_call_repair import (
    _canonicalize_tool_call_args,
    _repair_and_dedupe_tool_calls,
)
from focus_agent.engine.graph.tool_history_repair import (
    _count_tool_call_rounds_since_latest_human,
    _ensure_reasoning_content_for_tool_call_history,
    _messages_for_model,
    _should_force_tool_free_answer,
)
from focus_agent.engine.graph.tool_result_fallback import _fallback_answer_from_tool_results

from ...capabilities import ToolRegistry
from ...config import Settings
from ...core.request_context import RequestContext
from ...core.state import AgentState
from ...core.types import Plan
from ...memory import (
    MemoryExtractor,
    MemoryPolicy,
    MemoryRetriever,
    MemoryWriter,
)
from ...model_registry import create_chat_model
from ...skills import SkillRegistry
from .agent_loop import make_agent_loop_node
from .components import make_graph_tool_executor, resolve_graph_components
from .policy import (
    TurnToolExposure,
    _classify_turn_tool_exposure,
    _classify_turn_tool_policy,
    build_tool_intent_plan,
)
from .policy_notes import _tool_policy_note
from .policy_tools import _live_web_research_should_start_with_search, _tools_for_policy
from .tool_execution import HarnessToolServices
from .turn_hooks import TurnLifecycle


def build_graph(
    *,
    settings: Settings,
    checkpointer=None,
    store=None,
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
    if settings.agent_core == "v2":
        from ..loop import build_loop_graph

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
            system_agent_runner=system_agent_runner,
            agent_definition_registry=agent_definition_registry,
            chat_model_factory=create_chat_model,
        )
    components = resolve_graph_components(
        settings=settings,
        checkpointer=checkpointer,
        store=store,
        memory_retriever=memory_retriever,
        memory_policy=memory_policy,
        memory_writer=memory_writer,
        memory_extractor=memory_extractor,
        skill_registry=skill_registry,
        tool_registry=tool_registry,
        chat_model_factory=create_chat_model,
    )
    tools = components.tools
    effective_skill_registry = components.skill_registry
    model_for = components.model_for
    model_with_tools_for = components.model_with_tools_for
    lifecycle = TurnLifecycle(
        harness_services=harness_services, system_agent_runner=system_agent_runner
    )

    retrieve_memory = make_retrieve_memory_node(components.memory_retriever)
    assemble_context = make_assemble_context_node(
        settings=settings,
        skill_registry=effective_skill_registry,
    )
    role_route_dry_run = make_role_route_dry_run_node(settings=settings, tools=tools)
    delegation_governance = make_delegation_governance_node(
        settings=settings,
        tools=tools,
        chat_model_factory=create_chat_model,
    )
    plan_node = make_plan_node(settings=settings, model_for=model_for, tools=tools)
    reflect_node = make_reflect_node(settings=settings, model_for=model_for)
    agent_loop = make_agent_loop_node(
        settings=settings,
        tools=tools,
        tool_registry=components.tool_registry,
        skill_registry=effective_skill_registry,
        model_for=model_for,
        model_with_tools_for=model_with_tools_for,
        run_manager=run_manager,
        agent_definition_registry=agent_definition_registry,
    )
    tool_executor = make_graph_tool_executor(
        settings=settings,
        components=components,
        approval_queue=approval_queue,
        harness_services=harness_services,
    )

    extract_memories = make_extract_memories_node(components.memory_extractor)
    write_memories = make_write_memories_node(components.memory_writer)

    def should_continue_after_act(
        state: AgentState,
    ) -> Literal["tool_executor", "reflect", "summarize_turn"]:
        last_message = state["messages"][-1]
        if getattr(last_message, "tool_calls", None):
            return "tool_executor"
        if settings.plan_act_reflect_enabled and isinstance(state.get("plan"), Plan):
            return "reflect"
        return "summarize_turn"

    builder = StateGraph(AgentState, context_schema=RequestContext)
    builder.add_node("bootstrap_turn", lifecycle.bootstrap_turn)
    builder.add_node("retrieve_memory", retrieve_memory)
    builder.add_node("assemble_context", assemble_context)
    builder.add_node("role_route_dry_run", role_route_dry_run)
    builder.add_node("delegation_governance", delegation_governance)
    builder.add_node("plan", plan_node)
    builder.add_node("agent_loop", agent_loop)
    builder.add_node("tool_executor", tool_executor)
    builder.add_node("reflect", reflect_node)
    builder.add_node("summarize_turn", lifecycle.summarize_turn)
    builder.add_node("extract_memories", extract_memories)
    builder.add_node("write_memories", write_memories)
    builder.add_node("maybe_interrupt_for_merge", lifecycle.maybe_interrupt_for_merge)

    builder.add_edge(START, "bootstrap_turn")
    builder.add_edge("bootstrap_turn", "retrieve_memory")
    builder.add_edge("retrieve_memory", "assemble_context")
    builder.add_edge("assemble_context", "role_route_dry_run")
    builder.add_edge("role_route_dry_run", "delegation_governance")
    builder.add_edge("delegation_governance", "plan")
    builder.add_edge("plan", "agent_loop")
    builder.add_conditional_edges(
        "agent_loop",
        should_continue_after_act,
        ["tool_executor", "reflect", "summarize_turn"],
    )
    builder.add_edge("tool_executor", "agent_loop")
    builder.add_conditional_edges(
        "reflect",
        make_should_continue_after_reflect,
        ["plan", "summarize_turn"],
    )
    builder.add_edge("summarize_turn", "extract_memories")
    builder.add_edge("extract_memories", "write_memories")
    builder.add_edge("write_memories", "maybe_interrupt_for_merge")
    builder.add_edge("maybe_interrupt_for_merge", END)

    return builder.compile(checkpointer=checkpointer, store=store)


__all__ = [
    "TurnToolExposure",
    "_canonicalize_tool_call_args",
    "_classify_turn_tool_exposure",
    "_classify_turn_tool_policy",
    "_count_tool_call_rounds_since_latest_human",
    "_ensure_reasoning_content_for_tool_call_history",
    "_fallback_answer_from_tool_results",
    "_format_plan_block",
    "build_tool_intent_plan",
    "_live_web_research_should_start_with_search",
    "_looks_like_textual_tool_call_artifact",
    "_messages_for_model",
    "_parse_plan_json",
    "_parse_reflection_json",
    "_repair_and_dedupe_tool_calls",
    "_repair_tool_free_answer_response",
    "_should_force_tool_free_answer",
    "_should_plan",
    "_tool_policy_note",
    "_tools_for_policy",
    "build_graph",
]
