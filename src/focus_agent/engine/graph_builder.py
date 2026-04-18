from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, Literal

from langchain.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from ..capabilities import ToolRegistry, build_tool_registry
from ..config import Settings
from ..core.context_policy import assemble_context as build_context_slice
from ..core.request_context import RequestContext
from ..core.state import AgentState
from ..core.types import PromptMode
from ..memory import MemoryRetriever, render_memory_block
from ..model_registry import create_chat_model
from ..skills import SkillRegistry
from ..storage.namespaces import conversation_namespace_for_context

_MAX_CONSECUTIVE_TOOL_CALL_ROUNDS = 2
_TOOL_EXHAUSTION_NOTE = (
    "You have enough tool results for this turn. Do not call more tools. "
    "Answer the user directly using the information already gathered, and state any uncertainty plainly."
)
_TOOL_CALL_PROTOCOL_REPAIR_NOTE = (
    "If you need a tool, emit a real tool call through the tool-calling interface. "
    "Do not write DSML tags, XML, or function-call payloads into the assistant text. "
    "If no tool is needed, answer directly in natural language."
)
_TOOL_CALL_MARKUP_REPAIR_NOTE = (
    "Do not emit tool-call markup, XML, JSON function-call payloads, or DSML tags. "
    "Write only the final user-facing answer in natural language."
)


def _has_tool_calls(message: Any) -> bool:
    return bool(getattr(message, "tool_calls", None))


def _find_trailing_tool_span_start(messages: list[Any]) -> int | None:
    if not messages:
        return None

    index = len(messages) - 1
    while index >= 0 and isinstance(messages[index], ToolMessage):
        index -= 1

    if index < 0:
        return None
    if _has_tool_calls(messages[index]):
        return index
    return None


def _messages_for_model(state: AgentState) -> list[Any]:
    recent_messages = list(state.get("recent_messages") or [])
    messages = list(state.get("messages", []) or [])
    trailing_tool_span_start = _find_trailing_tool_span_start(messages)
    if trailing_tool_span_start is None:
        return recent_messages or messages
    return [*recent_messages, *messages[trailing_tool_span_start:]]


def _count_tool_call_rounds_since_latest_human(messages: list[Any]) -> int:
    rounds = 0
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            break
        if isinstance(message, AIMessage) and getattr(message, "tool_calls", None):
            rounds += 1
    return rounds


def _should_force_tool_free_answer(messages: list[Any]) -> bool:
    if not messages or not isinstance(messages[-1], ToolMessage):
        return False
    return _count_tool_call_rounds_since_latest_human(messages) >= _MAX_CONSECUTIVE_TOOL_CALL_ROUNDS


def _message_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, list):
        return json.dumps(content, ensure_ascii=False)
    return str(content)


def _looks_like_textual_tool_call_artifact(message: Any) -> bool:
    text = _message_text(message).lower()
    if not text:
        return False
    markers = (
        "function_calls",
        "invoke name=",
        "<｜dsml｜",
        "<tool_call",
        '"tool_name"',
    )
    return any(marker in text for marker in markers)


def _latest_human_message_text(messages: list[Any]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return _message_text(message)
    return ""


def _latest_final_ai_text(messages: list[Any]) -> str:
    for message in reversed(messages):
        if isinstance(message, AIMessage) and not getattr(message, "tool_calls", None):
            return _message_text(message)
    return ""


def _repair_textual_tool_call_response(
    *,
    response: Any,
    prompt_messages: list[Any],
    selected_model: str,
    selected_thinking_mode: str,
    model_for,
    model_with_tools_for,
) -> Any:
    if not _looks_like_textual_tool_call_artifact(response):
        return response

    repaired = model_with_tools_for(selected_model, selected_thinking_mode).invoke(
        [
            prompt_messages[0],
            SystemMessage(content=_TOOL_CALL_PROTOCOL_REPAIR_NOTE),
            *prompt_messages[1:],
            AIMessage(content=_message_text(response)),
        ]
    )
    if not _looks_like_textual_tool_call_artifact(repaired):
        return repaired

    return model_for(selected_model, selected_thinking_mode).invoke(
        [
            prompt_messages[0],
            SystemMessage(content=_TOOL_CALL_MARKUP_REPAIR_NOTE),
            *prompt_messages[1:],
            AIMessage(content=_message_text(repaired)),
        ]
    )


def _resolve_prompt_mode(state: AgentState) -> PromptMode:
    stored = state.get("prompt_mode")
    if isinstance(stored, PromptMode):
        return stored
    if isinstance(stored, str):
        try:
            return PromptMode(stored)
        except ValueError:
            pass
    if state.get("merge_proposal") and not state.get("merge_decision"):
        return PromptMode.BRANCH_REVIEW
    return PromptMode.EXPLORE


def build_graph(
    *,
    settings: Settings,
    checkpointer=None,
    store=None,
    memory_retriever: MemoryRetriever | None = None,
    skill_registry: SkillRegistry | None = None,
    tool_registry: ToolRegistry | None = None,
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
    base_model_cache: dict[str, Any] = {}
    model_cache: dict[str, Any] = {}
    model_with_tools_cache: dict[str, Any] = {}

    def base_model_for(model_id: str, thinking_mode: str):
        cache_key = f"{model_id}|{thinking_mode or ''}"
        cached = base_model_cache.get(cache_key)
        if cached is not None:
            return cached
        model = create_chat_model(
            model_id,
            temperature=settings.temperature,
            thinking_mode=thinking_mode or None,
            settings=settings,
        )
        base_model_cache[cache_key] = model
        return model

    def model_for(model_id: str, thinking_mode: str):
        cache_key = f"{model_id}|{thinking_mode or ''}"
        cached = model_cache.get(cache_key)
        if cached is not None:
            return cached
        model = base_model_for(model_id, thinking_mode).with_config({"run_name": "focus_agent_model"})
        model_cache[cache_key] = model
        return model

    def model_with_tools_for(model_id: str, thinking_mode: str):
        cache_key = f"{model_id}|{thinking_mode or ''}"
        cached = model_with_tools_cache.get(cache_key)
        if cached is not None:
            return cached
        bound = base_model_for(model_id, thinking_mode).bind_tools(tools).with_config({"run_name": "focus_agent_model"})
        model_with_tools_cache[cache_key] = bound
        return bound

    def bootstrap_turn(state: AgentState) -> dict[str, Any]:
        return {"llm_calls": state.get("llm_calls", 0)}

    def retrieve_memory(
        state: AgentState,
        runtime: Runtime[RequestContext],
    ) -> dict[str, Any]:
        latest_user = _latest_human_message_text(state.get("messages", []))
        prompt_mode = _resolve_prompt_mode(state)
        if memory_retriever is not None:
            bundle = memory_retriever.retrieve_for_turn(
                context=runtime.context,
                state=dict(state),
                query=latest_user,
                prompt_mode=prompt_mode,
            )
            return {
                "retrieved_memories": [
                    {
                        **hit.record.model_dump(mode="json"),
                        "score": hit.score,
                        "matched_terms": hit.matched_terms,
                    }
                    for hit in bundle.hits
                ],
                "memory_prompt_block": render_memory_block(bundle),
                "prompt_mode": prompt_mode,
            }

        memories = (
            runtime.store.search(
                conversation_namespace_for_context(runtime.context),
                query=latest_user,
                limit=4,
            )
            if runtime.store
            else []
        )
        memory_texts = [
            str(item.value.get("summary") or item.value.get("text") or item.value)
            for item in memories
        ]
        return {
            "retrieved_memories": [
                {"summary": text, "namespace": list(conversation_namespace_for_context(runtime.context))}
                for text in memory_texts
            ],
            "memory_prompt_block": render_memory_block(
                type(
                    "_Bundle",
                    (),
                    {
                        "hits": [],
                    },
                )()
            )
            if not memory_texts
            else "## Retrieved long-term memories\n" + "\n".join(f"- {text}" for text in memory_texts),
            "prompt_mode": prompt_mode,
        }

    def assemble_context(
        state: AgentState,
        runtime: Runtime[RequestContext],
    ) -> dict[str, Any]:
        latest_user = _latest_human_message_text(state.get("messages", []))
        prompt_mode = _resolve_prompt_mode(state)
        active_skill_ids = tuple(
            runtime.context.skill_hints
            or tuple(str(item) for item in state.get("active_skill_ids", []) or ())
        )
        active_skills_block = effective_skill_registry.render_active_skills_block(active_skill_ids)
        available_skills_block = effective_skill_registry.render_available_skills_block()
        context_slice = build_context_slice(
            {
                **dict(state),
                "pinned_items": deepcopy(state.get("pinned_items", [])),
                "merge_queue": deepcopy(state.get("merge_queue", [])),
                "_memory_lines": [
                    item.get("summary") or item.get("content") or str(item)
                    for item in state.get("retrieved_memories", [])
                ],
                "_scene": runtime.context.scene,
                "_active_skills_block": active_skills_block,
                "_available_skills_block": available_skills_block,
            },
            prompt_mode,
        )
        task_brief = state.get("task_brief")
        if not task_brief and latest_user:
            task_brief = latest_user[:300]
        return {
            "recent_messages": context_slice.recent_messages,
            "assembled_context": context_slice.render_prompt(),
            "task_brief": task_brief or state.get("task_brief", ""),
            "prompt_mode": prompt_mode,
            "active_skill_ids": list(active_skill_ids),
            "active_skills_block": active_skills_block,
            "available_skills_block": available_skills_block,
        }

    def agent_loop(
        state: AgentState,
        runtime: Runtime[RequestContext],
    ) -> dict[str, Any]:
        del runtime
        messages = _messages_for_model(state)
        selected_model = str(state.get("selected_model") or settings.model)
        selected_thinking_mode = str(state.get("selected_thinking_mode") or "")
        prompt_messages = [SystemMessage(content=state.get("assembled_context", "")), *messages]
        if _should_force_tool_free_answer(list(state.get("messages", []) or [])):
            response = model_for(selected_model, selected_thinking_mode).invoke(
                [
                    prompt_messages[0],
                    SystemMessage(content=_TOOL_EXHAUSTION_NOTE),
                    *prompt_messages[1:],
                ]
            )
            if _looks_like_textual_tool_call_artifact(response):
                response = model_for(selected_model, selected_thinking_mode).invoke(
                    [
                        prompt_messages[0],
                        SystemMessage(content=_TOOL_EXHAUSTION_NOTE),
                        SystemMessage(content=_TOOL_CALL_MARKUP_REPAIR_NOTE),
                        *prompt_messages[1:],
                        AIMessage(content=_message_text(response)),
                    ]
                )
        else:
            response = model_with_tools_for(selected_model, selected_thinking_mode).invoke(prompt_messages)
            response = _repair_textual_tool_call_response(
                response=response,
                prompt_messages=prompt_messages,
                selected_model=selected_model,
                selected_thinking_mode=selected_thinking_mode,
                model_for=model_for,
                model_with_tools_for=model_with_tools_for,
            )
        return {
            "messages": [response],
            "llm_calls": state.get("llm_calls", 0) + 1,
        }

    def tool_executor(state: AgentState) -> dict[str, Any]:
        result_messages: list[ToolMessage] = []
        last_message = state["messages"][-1]
        for tool_call in getattr(last_message, "tool_calls", []) or []:
            tool = tools_by_name[tool_call["name"]]
            observation = tool.invoke(tool_call["args"])
            result_messages.append(ToolMessage(content=str(observation), tool_call_id=tool_call["id"]))
        return {"messages": result_messages}

    def summarize_turn(state: AgentState) -> dict[str, Any]:
        last_user = _latest_human_message_text(state.get("messages", []))
        last_ai = _latest_final_ai_text(state.get("messages", []))
        previous_summary = state.get("rolling_summary", "")
        candidate_lines = [
            line
            for line in [previous_summary, f"User: {last_user}", f"Assistant: {last_ai}"]
            if line
        ]
        joined = "\n".join(candidate_lines)
        if len(joined) > 4000:
            joined = joined[-4000:]
        return {"rolling_summary": joined}

    def maybe_interrupt_for_merge(state: AgentState) -> dict[str, Any]:
        if state.get("merge_proposal") and not state.get("merge_decision"):
            decision = interrupt(
                {
                    "kind": "merge_review",
                    "proposal": state["merge_proposal"],
                    "message": "Review the branch proposal and choose whether to import it into the parent thread.",
                }
            )
            return {"merge_decision": decision}
        return {}

    def should_continue(state: AgentState) -> Literal["tool_executor", "summarize_turn"]:
        last_message = state["messages"][-1]
        if getattr(last_message, "tool_calls", None):
            return "tool_executor"
        return "summarize_turn"

    builder = StateGraph(AgentState, context_schema=RequestContext)
    builder.add_node("bootstrap_turn", bootstrap_turn)
    builder.add_node("retrieve_memory", retrieve_memory)
    builder.add_node("assemble_context", assemble_context)
    builder.add_node("agent_loop", agent_loop)
    builder.add_node("tool_executor", tool_executor)
    builder.add_node("summarize_turn", summarize_turn)
    builder.add_node("maybe_interrupt_for_merge", maybe_interrupt_for_merge)

    builder.add_edge(START, "bootstrap_turn")
    builder.add_edge("bootstrap_turn", "retrieve_memory")
    builder.add_edge("retrieve_memory", "assemble_context")
    builder.add_edge("assemble_context", "agent_loop")
    builder.add_conditional_edges("agent_loop", should_continue, ["tool_executor", "summarize_turn"])
    builder.add_edge("tool_executor", "agent_loop")
    builder.add_edge("summarize_turn", "maybe_interrupt_for_merge")
    builder.add_edge("maybe_interrupt_for_merge", END)

    return builder.compile(checkpointer=checkpointer, store=store)
