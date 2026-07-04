from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

from langchain.messages import HumanMessage
from langgraph.graph import END, START, StateGraph

from ...capabilities import ToolRegistry, build_tool_registry
from ...capabilities.tool_runtime import ToolResultCacheStore
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
from ..graph_governance_nodes import (
    make_delegation_governance_node,
    make_role_route_dry_run_node,
)
from ..graph_memory_nodes import (
    make_assemble_context_node,
    make_extract_memories_node,
    make_retrieve_memory_node,
    make_write_memories_node,
    maybe_interrupt_for_merge,
    summarize_turn as _summarize_turn_impl,
)
from ..graph_plan_nodes import (
    _format_plan_block,
    _parse_plan_json,
    _parse_reflection_json,
    _should_plan,
    make_plan_node,
    make_reflect_node,
    make_should_continue_after_reflect,
)
from ..graph_turn_helpers import (
    TurnToolExposure,
    _canonicalize_tool_call_args,
    _classify_turn_tool_exposure,
    _classify_turn_tool_policy,
    _count_tool_call_rounds_since_latest_human,
    _ensure_reasoning_content_for_tool_call_history,
    _fallback_answer_from_tool_results,
    _live_web_research_should_start_with_search,
    _looks_like_textual_tool_call_artifact,
    _messages_for_model,
    _repair_and_dedupe_tool_calls,
    _repair_tool_free_answer_response,
    _should_force_tool_free_answer,
    _tool_policy_note,
    _tools_for_policy,
    build_tool_intent_plan,
)
from ..model_factory import GraphModelFactory
from .agent_loop import make_agent_loop_node
from .context_pipeline_node import make_context_pipeline_node
from .tool_execution import HarnessToolServices, make_tool_executor_node

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# System agent trigger helper (fire-and-forget from sync nodes)
# ------------------------------------------------------------------
def _fire_system_agent(
    runner: Any | None,
    trigger_name: str,
    ctx: dict[str, Any],
) -> None:
    """Fire system agents for ``trigger_name`` as fire-and-forget background tasks.

    Safe to call from a sync node. Never raises; if no running event loop is
    available (e.g. tests invoking the graph synchronously) the trigger is
    silently skipped.
    """

    if runner is None:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    try:
        loop.create_task(runner.trigger(trigger_name, ctx))
    except Exception:  # noqa: BLE001
        logger.debug(
            "Failed to fire system agent trigger '%s'",
            trigger_name,
            exc_info=True,
        )


def _build_system_agent_ctx(state: AgentState, runtime: Any) -> dict[str, Any]:
    """Build a minimal context dict for system agent handlers."""

    ctx = getattr(runtime, "context", None)
    return {
        "state": dict(state),
        "context": ctx,
        "user_id": getattr(ctx, "user_id", None),
        "root_thread_id": getattr(ctx, "root_thread_id", None),
    }


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
    effective_skill_registry = skill_registry or SkillRegistry.from_settings(settings)
    effective_tool_registry = tool_registry or build_tool_registry(
        settings=settings,
        skill_registry=effective_skill_registry,
        store=store,
        checkpointer=checkpointer,
    )
    tools = list(effective_tool_registry.tools)
    tools_by_name = effective_tool_registry.by_name
    tool_runtime_by_name = effective_tool_registry.runtime_by_name
    effective_memory_policy = (
        memory_policy or getattr(memory_retriever, "policy", None) or MemoryPolicy()
    )
    effective_memory_retriever = memory_retriever or MemoryRetriever(
        store=store, policy=effective_memory_policy
    )
    effective_memory_writer = memory_writer or MemoryWriter(
        store=store, policy=effective_memory_policy
    )
    effective_memory_extractor = memory_extractor or MemoryExtractor()
    model_factory = GraphModelFactory(settings=settings, chat_model_factory=create_chat_model)
    tool_result_cache = ToolResultCacheStore()

    def model_for(model_id: str, thinking_mode: str):
        return model_factory.model_for(model_id, thinking_mode)

    def model_with_tools_for(
        model_id: str, thinking_mode: str, available_tools: list[Any] | None = None
    ):
        return model_factory.model_with_tools_for(
            model_id,
            thinking_mode,
            default_tools=tools,
            available_tools=available_tools,
        )

    # ------------------------------------------------------------------
    # Turn-lifecycle hook helpers (on_turn_start / on_turn_end)
    # ------------------------------------------------------------------
    _agent_start_fired_threads: set[str] = set()

    def _turn_ctx(state: AgentState) -> dict[str, Any]:
        thread_id = state.get("thread_id") if isinstance(state, dict) else None
        return {
            "thread_id": thread_id,
            "run_id": harness_services.run_id if harness_services else None,
            "agent_name": (harness_services.active_agent_name if harness_services else None)
            or "focus_agent",
            "state": state,
        }

    def _fire_on_turn_start(state: AgentState) -> None:
        nonlocal _agent_start_fired_threads
        if harness_services is not None and harness_services.extension_registry is not None:
            thread_id = str(state.get("thread_id", "") or "")
            if thread_id not in _agent_start_fired_threads:
                try:
                    from ...harness.extensions import ExtensionContext

                    ctx = ExtensionContext(
                        thread_id=thread_id,
                        run_id=harness_services.run_id,
                        agent_name=harness_services.active_agent_name or "focus_agent",
                    )
                    harness_services.extension_registry.fire_hook("on_agent_start", ctx)
                    _agent_start_fired_threads.add(thread_id)
                except Exception:  # noqa: BLE001
                    logger.warning("extension on_agent_start failed", exc_info=True)
        if harness_services is None or harness_services.middleware_stack is None:
            return
        try:
            harness_services.middleware_stack.on_turn_start(_turn_ctx(state))
        except Exception:  # noqa: BLE001
            logger.warning("middleware.on_turn_start failed", exc_info=True)

    def _fire_on_turn_end(state: AgentState) -> None:
        if harness_services is None or harness_services.middleware_stack is None:
            return
        try:
            harness_services.middleware_stack.on_turn_end(_turn_ctx(state))
        except Exception:  # noqa: BLE001
            logger.warning("middleware.on_turn_end failed", exc_info=True)

    def bootstrap_turn(state: AgentState, runtime) -> dict[str, Any]:
        _fire_on_turn_start(state)
        # Fire first_user_message trigger when this is the first human turn.
        human_count = sum(
            1 for m in state.get("messages", []) or [] if isinstance(m, HumanMessage)
        )
        if human_count <= 1:
            _fire_system_agent(
                system_agent_runner,
                "first_user_message",
                _build_system_agent_ctx(state, runtime),
            )
        return {"llm_calls": state.get("llm_calls", 0)}

    retrieve_memory = make_retrieve_memory_node(effective_memory_retriever)
    assemble_context = make_assemble_context_node(
        settings=settings,
        skill_registry=effective_skill_registry,
    )
    # ContextPipeline augment node: runs between retrieve_memory and
    # assemble_context. It receives the same dependencies as the legacy
    # nodes but operates in "augment" mode so it never double-emits blocks
    # already produced by assemble_context. If it raises, the node returns
    # {} and the legacy path is unaffected.
    context_pipeline_node = make_context_pipeline_node(
        memory_retriever=effective_memory_retriever,
        skill_registry=effective_skill_registry,
        agent_registry=agent_definition_registry,
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
        tool_registry=effective_tool_registry,
        skill_registry=effective_skill_registry,
        model_for=model_for,
        model_with_tools_for=model_with_tools_for,
        run_manager=run_manager,
        system_agent_runner=system_agent_runner,
        agent_definition_registry=agent_definition_registry,
    )
    tool_executor = make_tool_executor_node(
        tools_by_name=tools_by_name,
        tool_runtime_by_name=tool_runtime_by_name,
        tool_result_cache=tool_result_cache,
        max_parallel_workers=settings.tool_max_parallel_workers,
        multi_agent_async_approval_enabled=bool(
            settings.multi_agent_v2_enabled and settings.multi_agent_async_approval_enabled
        ),
        multi_agent_approval_timeout_seconds=settings.multi_agent_approval_timeout_seconds,
        approval_queue=approval_queue,
        harness_services=harness_services,
    )

    extract_memories = make_extract_memories_node(effective_memory_extractor)
    write_memories = make_write_memories_node(effective_memory_writer)

    def should_continue_after_act(
        state: AgentState,
    ) -> Literal["tool_executor", "reflect", "summarize_turn"]:
        last_message = state["messages"][-1]
        if getattr(last_message, "tool_calls", None):
            return "tool_executor"
        if settings.plan_act_reflect_enabled and isinstance(state.get("plan"), Plan):
            return "reflect"
        return "summarize_turn"

    def summarize_turn(state: AgentState, runtime) -> dict[str, Any]:
        result = _summarize_turn_impl(state)
        # Fire turn_end system agents (fire-and-forget); best-effort.
        _fire_system_agent(
            system_agent_runner,
            "turn_end",
            {
                **_build_system_agent_ctx(state, runtime),
                "rolling_summary": result.get("rolling_summary", ""),
            },
        )
        return result

    # Wrap the tail node to fire on_turn_end right before the graph exits.
    def _merge_node_with_turn_end(state: AgentState) -> dict[str, Any]:
        _fire_on_turn_end(state)
        return maybe_interrupt_for_merge(state)

    builder = StateGraph(AgentState, context_schema=RequestContext)
    builder.add_node("bootstrap_turn", bootstrap_turn)
    builder.add_node("retrieve_memory", retrieve_memory)
    builder.add_node("context_pipeline", context_pipeline_node)
    builder.add_node("assemble_context", assemble_context)
    builder.add_node("role_route_dry_run", role_route_dry_run)
    builder.add_node("delegation_governance", delegation_governance)
    builder.add_node("plan", plan_node)
    builder.add_node("agent_loop", agent_loop)
    builder.add_node("tool_executor", tool_executor)
    builder.add_node("reflect", reflect_node)
    builder.add_node("summarize_turn", summarize_turn)
    builder.add_node("extract_memories", extract_memories)
    builder.add_node("write_memories", write_memories)
    builder.add_node("maybe_interrupt_for_merge", _merge_node_with_turn_end)

    builder.add_edge(START, "bootstrap_turn")
    builder.add_edge("bootstrap_turn", "retrieve_memory")
    builder.add_edge("retrieve_memory", "context_pipeline")
    builder.add_edge("context_pipeline", "assemble_context")
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
