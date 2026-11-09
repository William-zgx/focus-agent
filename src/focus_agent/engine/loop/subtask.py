"""Single-level sub-agent delegation for the model-driven core."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any
from uuid import uuid4

from langchain.messages import AIMessage, HumanMessage
from langchain.tools import tool
from langgraph.config import get_config
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import get_runtime

from ...capabilities.ask_user_question import ASK_USER_QUESTION_TOOL_NAME
from ...capabilities.tool_execution_types import (
    SELECTED_MODEL_CONFIG_KEY,
    SELECTED_THINKING_MODE_CONFIG_KEY,
    TOOL_CALL_ID_CONFIG_KEY,
)
from ...capabilities.tool_manifest import ToolManifest
from ...capabilities.tool_registry import ToolRegistry
from ...config import Settings
from ...core.request_context import RequestContext
from ...core.state import AgentState
from ...transport.stream_events import STREAM_VISIBILITY_QUARANTINE
from ..tools.evidence import evidence_bundle_to_citation_refs, normalize_evidence_bundle
from ..tools.execution import HarnessToolServices
from .agent import make_loop_agent_node
from .components import GraphComponents
from .messages import _message_content_text
from .tool_search import make_loop_tool_executor, with_tool_search

RUN_SUBTASK_TOOL_NAME = "run_subtask"
_SUBTASK_SOURCE_LIMIT = 5


def with_subtask_tool(
    *,
    settings: Settings,
    components: GraphComponents,
    harness_services: HarnessToolServices | None,
) -> GraphComponents:
    subtask_tool = _make_subtask_tool(
        settings=settings,
        components=components,
        harness_services=harness_services,
    )
    parent_tools = [
        item for item in components.tools if getattr(item, "name", "") != RUN_SUBTASK_TOOL_NAME
    ]
    registry = ToolRegistry(
        tools=(*parent_tools, subtask_tool),
        manifests=(
            *(
                manifest
                for manifest in components.tool_registry.manifests
                if manifest.name != RUN_SUBTASK_TOOL_NAME
            ),
            ToolManifest.from_tool(subtask_tool),
        ),
    )
    return replace(components, tools=list(registry.tools), tool_registry=registry)


def _make_subtask_tool(
    *,
    settings: Settings,
    components: GraphComponents,
    harness_services: HarnessToolServices | None,
) -> Any:
    subtask_tools = []
    for item in components.tools:
        name = str(getattr(item, "name", "") or "")
        runtime = components.tool_registry.runtime_by_name.get(name)
        if (
            name in {RUN_SUBTASK_TOOL_NAME, ASK_USER_QUESTION_TOOL_NAME}
            or runtime is None
            or runtime.requires_approval
        ):
            continue
        subtask_tools.append(item)
    subtask_registry = ToolRegistry(
        tools=tuple(subtask_tools),
        manifests=tuple(
            components.tool_registry.manifest_by_name[str(getattr(item, "name", ""))]
            for item in subtask_tools
        ),
    )
    subtask_components = with_tool_search(
        settings=settings,
        components=replace(
            components,
            tools=list(subtask_registry.tools),
            tool_registry=subtask_registry,
        ),
    )
    subgraph = _compile_subtask_graph(
        settings=settings,
        components=subtask_components,
        harness_services=harness_services,
    )

    @tool
    def run_subtask(description: str, prompt: str) -> str:
        """Delegate an independent task to a fresh sub-agent with its own context window.

        The sub-agent sees only the complete, self-contained prompt, not the parent
        conversation. It inherits the parent's tools except run_subtask (no nesting),
        tools requiring approval, and ask_user_question (it cannot pause for the user).
        Use it for broad research or independent investigations, not trivial lookups.
        Returns the sub-agent's final answer and any web sources it used.
        """
        label = description.strip()
        instructions = prompt.strip()
        if not label or not instructions:
            return _error_result(label, "description and prompt must both be non-empty.")
        try:
            config = get_config()
            request_context = get_runtime(RequestContext).context
            configurable = dict(config.get("configurable") or {})
            tool_call_id = str(configurable.get(TOOL_CALL_ID_CONFIG_KEY) or "")
            parent_thread_id = str(
                configurable.get("thread_id") or request_context.root_thread_id or ""
            )
            if not tool_call_id or not parent_thread_id:
                return _error_result(label, "trusted subtask invocation context is unavailable.")
            selected_model = str(configurable.get(SELECTED_MODEL_CONFIG_KEY) or settings.model)
            thinking_mode = str(configurable.get(SELECTED_THINKING_MODE_CONFIG_KEY) or "")
            # Do not forward the parent's __pregel_* internals. Child tools need only
            # this identity scope; observation persistence uses the derived thread ID.
            # checkpoint_ns is only a string used for nested stream attribution.
            subtask_configurable = {
                key: configurable[key]
                for key in ("user_id", "branch_id", "checkpoint_ns")
                if configurable.get(key)
            }
            subtask_configurable["thread_id"] = f"{parent_thread_id}:subtask:{tool_call_id}"
            if subtask_configurable.get("checkpoint_ns"):
                # A fresh task ID marks this as nested without forwarding the parent's
                # task identity, so PregelLoop retains the stream namespace above.
                subtask_configurable["__pregel_task_id"] = str(uuid4())
            human_message = HumanMessage(content=instructions)
            result = subgraph.invoke(
                {
                    "messages": [human_message],
                    "recent_messages": [human_message],
                    "task_brief": instructions,
                    "assembled_context": (
                        "You are a fresh sub-agent. Complete the delegated task independently "
                        "and return only the final answer. Do not ask the user questions.\n\n"
                        f"Task: {label}"
                    ),
                    "selected_model": selected_model,
                    "selected_thinking_mode": thinking_mode,
                },
                config={"configurable": subtask_configurable},
                context=request_context,
            )
            if (result.get("plan_meta") or {}).get("tool_budget_exhausted"):
                return _error_result(
                    label,
                    f"the sub-agent exhausted its {settings.agent_max_tool_rounds} tool-round budget.",
                )
            answer = _final_answer(result.get("messages") or [])
            if not answer:
                return _error_result(label, "the sub-agent returned an empty answer.")
            evidence = normalize_evidence_bundle(
                result.get("messages") or [], user_query=instructions
            )
            citations = evidence_bundle_to_citation_refs(evidence, limit=_SUBTASK_SOURCE_LIMIT)
            sources = [
                {"title": citation["label"], "url": citation["uri"]}
                for citation in citations
                if citation.get("uri")
            ]
            return json.dumps(
                {
                    "status": "success",
                    "description": label,
                    "answer": answer,
                    "sources": sources,
                },
                ensure_ascii=False,
            )
        except Exception as exc:  # noqa: BLE001
            return _error_result(label, f"sub-agent execution failed: {exc}")

    run_subtask.metadata = {
        "display_name": "Run Subtask",
        "parallel_safe": True,
        "cacheable": False,
        "requires_approval": False,
        "risk_level": "low",
        "toolset": "delegation",
        "intent_tags": ("delegation",),
    }
    return run_subtask


def _compile_subtask_graph(
    *,
    settings: Settings,
    components: GraphComponents,
    harness_services: HarnessToolServices | None,
) -> Any:
    builder = StateGraph(AgentState, context_schema=RequestContext)
    builder.add_node(
        "agent_loop",
        make_loop_agent_node(
            settings=settings,
            tools=components.tools,
            model_for=components.model_for,
            model_with_tools_for=components.model_with_tools_for,
            stream_phase=STREAM_VISIBILITY_QUARANTINE,
        ),
    )
    builder.add_node(
        "tool_executor",
        make_loop_tool_executor(
            settings=settings,
            components=components,
            approval_queue=None,
            harness_services=harness_services,
            allow_approval_interrupts=False,
        ),
    )
    builder.add_edge(START, "agent_loop")
    builder.add_conditional_edges("agent_loop", _route_after_agent, ["tool_executor", END])
    builder.add_edge("tool_executor", "agent_loop")
    return builder.compile(checkpointer=False)


def _route_after_agent(state: AgentState) -> str:
    if getattr(state["messages"][-1], "tool_calls", None):
        return "tool_executor"
    return END


def _final_answer(messages: list[Any]) -> str:
    for message in reversed(messages):
        if isinstance(message, AIMessage) and not getattr(message, "tool_calls", None):
            return _message_content_text(message).strip()
    return ""


def _error_result(description: str, error: str) -> str:
    return json.dumps(
        {
            "status": "error",
            "tool": RUN_SUBTASK_TOOL_NAME,
            "description": description,
            "error": error,
        },
        ensure_ascii=False,
    )


__all__ = ["RUN_SUBTASK_TOOL_NAME", "with_subtask_tool"]
