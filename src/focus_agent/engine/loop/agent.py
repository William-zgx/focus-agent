"""Model-driven agent node: the model picks tools; code enforces budgets only."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from langchain.messages import AIMessage, HumanMessage
from langgraph.runtime import Runtime

from ...config import Settings
from ...core.branch_messages import branch_context_messages
from ...core.context_request import ContextRequest, build_context_request
from ...core.request_context import RequestContext
from ...core.runtime_outcome import build_task_outcome
from ...core.state import AgentState, append_agent_state_record
from ...transport.stream_events import STREAM_VISIBILITY_QUARANTINE, STREAM_VISIBILITY_VISIBLE
from ..tools.call_repair import _known_tool_names, _repair_and_dedupe_tool_calls
from ..tools.evidence import (
    evidence_bundle_to_citation_refs,
    normalize_evidence_bundle,
    normalize_evidence_ledger,
)
from ..tools.history_repair import (
    _ensure_reasoning_content_for_tool_call_history,
    _latest_human_message_text,
    _latest_turn_messages,
    _messages_for_model,
    _should_force_tool_free_answer,
)
from ..tools.result_fallback import (
    _context_budget_from_state,
    _has_tool_result_messages,
    _invoke_with_tool_result_fallback,
    _tool_result_fallback_message,
)
from ..tools.textual_repair import (
    _looks_like_textual_tool_call_artifact,
    _repair_textual_tool_call_response,
    _repair_tool_free_answer_response,
)
from .messages import (
    _apply_agent_definition,
    _build_prompt_messages,
    _context_overflow_execution_contract,
    _context_overflow_response,
    _latest_tool_result_content,
    _message_content_text,
    _new_citation_refs,
    _root_thread_id,
    _steer_block,
)
from .prompt import operating_note
from .support import (
    _drain_steer_messages,
    _filter_tools_by_agent_def,
    _model_for_stream_phase,
    _model_with_tools_for_stream_phase,
    _resolve_agent_definition,
    _with_focus_agent_turn_metadata,
    _with_stream_phase,
)
from .todos import todos_block

AGENT_CORE_V2 = "v2"
_MODEL_DRIVEN_POLICY = "model_driven"


def make_loop_agent_node(
    *,
    settings: Settings,
    tools: Sequence[Any],
    model_for: Callable[[str, str], Any],
    model_with_tools_for: Callable[[str, str, list[Any] | None], Any],
    run_manager: Any | None = None,
    agent_definition_registry: Any | None = None,
    stream_phase: str = STREAM_VISIBILITY_VISIBLE,
) -> Any:
    all_tools = list(tools)
    max_tool_rounds = max(1, int(settings.agent_max_tool_rounds))
    final_answer_model_for = _model_for_stream_phase(model_for, stream_phase)
    quarantined_model_for = _model_for_stream_phase(model_for, STREAM_VISIBILITY_QUARANTINE)
    quarantined_model_with_tools_for = _model_with_tools_for_stream_phase(
        model_with_tools_for, STREAM_VISIBILITY_QUARANTINE
    )

    def agent_loop(state: AgentState, runtime: Runtime[RequestContext]) -> dict[str, Any]:
        state_messages = list(state.get("messages", []) or [])
        fallback_messages = _latest_turn_messages(state_messages)
        selected_model = str(state.get("selected_model") or settings.model)
        thinking_mode = str(state.get("selected_thinking_mode") or "")
        agent_def, agent_name = _resolve_agent_definition(agent_definition_registry, state)
        selected_model, assembled = _apply_agent_definition(
            agent_def,
            agent_name,
            selected_model=selected_model,
            assembled=state.get("assembled_context", ""),
        )
        user_goal = _latest_human_message_text(state_messages) or str(state.get("task_brief") or "")
        context_budget = _context_budget_from_state(state)
        if not context_budget.tokenizer_id and selected_model:
            context_budget = context_budget.model_copy(update={"tokenizer_id": selected_model})

        available_tools = _filter_tools_by_agent_def(all_tools, agent_def)
        tool_budget_exhausted = bool(available_tools) and _should_force_tool_free_answer(
            state_messages, max_rounds=max_tool_rounds
        )
        if tool_budget_exhausted:
            available_tools = []
        known_names = _known_tool_names(available_tools or all_tools)
        history = _messages_for_model(state)
        steer_block = _steer_block(_drain_steer_messages(run_manager, _root_thread_id(runtime)))
        # Todos come from the full branch transcript; the model view may be compacted.
        todos_note = todos_block(branch_context_messages(state_messages, values=state))

        def request_with(offered_tools: list[Any]) -> ContextRequest:
            prompt = _build_prompt_messages(
                assembled,
                history,
                steer_block=steer_block,
                policy_note="\n\n".join(
                    part
                    for part in (
                        operating_note(
                            _known_tool_names(offered_tools) if offered_tools else (),
                            tool_budget_exhausted=tool_budget_exhausted,
                        ),
                        todos_note,
                    )
                    if part
                ),
            )
            return build_context_request(
                prompt,
                budget=context_budget,
                available_tools=offered_tools,
                output_reserve_tokens=state.get("output_token_reserve"),
                preserve_required_messages=True,
            )

        context_request = request_with(available_tools)
        tools_withheld_for_context = False
        if context_request.required_overflow and available_tools:
            # Tool schemas share the prompt allowance; a text answer beats refusing the turn.
            tool_free_request = request_with([])
            if not tool_free_request.required_overflow:
                context_request = tool_free_request
                available_tools = []
                tools_withheld_for_context = True
        prompt_messages = context_request.messages
        context_overflow = context_request.required_overflow
        repair_reason = ""
        if context_overflow:
            response: Any = _context_overflow_response(user_goal)
        else:
            prompt_messages = _ensure_reasoning_content_for_tool_call_history(
                prompt_messages,
                model_id=selected_model,
                thinking_mode=thinking_mode,
                settings=settings,
            )
            model = (
                model_with_tools_for(selected_model, thinking_mode, available_tools)
                if available_tools
                else model_for(selected_model, thinking_mode)
            )
            response = _invoke_with_tool_result_fallback(
                _with_stream_phase(model, stream_phase),
                prompt_messages,
                fallback_messages=fallback_messages,
                known_tool_names=known_names,
                budget=context_budget,
            )
            if (tool_budget_exhausted or tools_withheld_for_context) and getattr(
                response, "tool_calls", None
            ):
                repair_reason = "tool_free_tool_call"
                response = _repair_tool_free_answer_response(
                    response=response.model_copy(update={"tool_calls": []}),
                    prompt_messages=prompt_messages,
                    fallback_messages=fallback_messages,
                    context_budget=context_budget,
                    selected_model=selected_model,
                    selected_thinking_mode=thinking_mode,
                    model_for=final_answer_model_for,
                    known_tool_names=known_names,
                )
            elif _looks_like_textual_tool_call_artifact(response, known_tool_names=known_names):
                repair_reason = "textual_tool_marker"
                response = (
                    _repair_textual_tool_call_response(
                        response=response,
                        prompt_messages=prompt_messages,
                        fallback_messages=fallback_messages,
                        context_budget=context_budget,
                        selected_model=selected_model,
                        selected_thinking_mode=thinking_mode,
                        available_tools=available_tools,
                        model_for=quarantined_model_for,
                        model_with_tools_for=quarantined_model_with_tools_for,
                    )
                    if available_tools
                    else _repair_tool_free_answer_response(
                        response=response,
                        prompt_messages=prompt_messages,
                        fallback_messages=fallback_messages,
                        context_budget=context_budget,
                        selected_model=selected_model,
                        selected_thinking_mode=thinking_mode,
                        model_for=quarantined_model_for,
                        known_tool_names=known_names,
                    )
                )
            elif (
                not getattr(response, "tool_calls", None)
                and not _message_content_text(response).strip()
                and _has_tool_result_messages(fallback_messages)
            ):
                # Nothing reached the user yet, so the synthesized answer streams visibly.
                repair_reason = "empty_final_answer"
                response = _repair_tool_free_answer_response(
                    response=response,
                    prompt_messages=prompt_messages,
                    fallback_messages=fallback_messages,
                    context_budget=context_budget,
                    selected_model=selected_model,
                    selected_thinking_mode=thinking_mode,
                    model_for=final_answer_model_for,
                    known_tool_names=known_names,
                )
                if not _message_content_text(response).strip():
                    response = _tool_result_fallback_message(fallback_messages)
            response = _repair_and_dedupe_tool_calls(response)

        updates: dict[str, Any] = {"llm_calls": int(state.get("llm_calls", 0) or 0) + 1}
        if getattr(response, "tool_calls", None):
            updates["messages"] = [response]
            return updates
        return {
            **updates,
            **_final_answer_updates(
                state=state,
                state_messages=state_messages,
                response=response,
                user_goal=user_goal,
                context_overflow=context_overflow,
                tool_budget_exhausted=tool_budget_exhausted,
                tools_withheld_for_context=tools_withheld_for_context,
                repair_reason=repair_reason,
            ),
        }

    return agent_loop


def _final_answer_updates(
    *,
    state: AgentState,
    state_messages: list[Any],
    response: AIMessage,
    user_goal: str,
    context_overflow: bool,
    tool_budget_exhausted: bool,
    tools_withheld_for_context: bool,
    repair_reason: str,
) -> dict[str, Any]:
    completed_turn = _latest_turn_messages([*state_messages, response])
    observed_at = _latest_tool_result_content(completed_turn, "current_utc_time") or None
    evidence_bundle = normalize_evidence_bundle(
        completed_turn, observed_at=observed_at, user_query=user_goal
    )
    evidence_ledger = normalize_evidence_ledger(
        completed_turn, observed_at=observed_at, user_query=user_goal
    )
    execution_contract: dict[str, Any] = {
        "policy": _MODEL_DRIVEN_POLICY,
        "status": "not_required",
        "user_query": user_goal,
    }
    if context_overflow:
        execution_contract = _context_overflow_execution_contract(execution_contract)
    human_turn_index = sum(1 for m in state_messages if isinstance(m, HumanMessage)) or 1
    tool_outcomes = list(state.get("tool_outcomes") or [])
    task_outcome = build_task_outcome(
        user_goal=user_goal,
        execution_contract=execution_contract,
        answer_verification=None,
        evidence_ledger=evidence_ledger,
        tool_outcomes=tool_outcomes,
        final_answer=_message_content_text(response),
        repair_action_taken=repair_reason,
        current_turn_id=str(human_turn_index),
        current_human_turn_index=human_turn_index,
    )
    updates: dict[str, Any] = {
        "messages": [_with_focus_agent_turn_metadata(response, {"task_outcome": task_outcome})],
        "evidence_bundle": evidence_bundle,
        "evidence_ledger": evidence_ledger,
        "execution_contract": execution_contract,
        "answer_verification": None,
        "task_outcome": task_outcome,
    }
    citations = _new_citation_refs(
        evidence_bundle_to_citation_refs(evidence_bundle),
        existing=list(state.get("citations", []) or []),
    )
    if citations:
        updates["citations"] = citations
    append_agent_state_record(
        updates, "task_outcome", task_outcome, source="agent_loop", domain="observability"
    )
    plan_meta = {
        **(state.get("plan_meta") or {}),
        "agent_core": AGENT_CORE_V2,
        "answer_verification": None,
        "execution_contract": execution_contract,
        "evidence_ledger": evidence_ledger,
        "tool_outcomes": tool_outcomes,
        "task_outcome": task_outcome,
    }
    if tool_budget_exhausted:
        plan_meta["tool_budget_exhausted"] = True
    if tools_withheld_for_context:
        plan_meta["tools_withheld_for_context"] = True
    if context_overflow:
        plan_meta["context_budget_exhausted"] = True
    if repair_reason:
        plan_meta["tool_protocol_repair_count"] = (
            int(plan_meta.get("tool_protocol_repair_count", 0) or 0) + 1
        )
        plan_meta["tool_protocol_repair_reason"] = repair_reason
    updates["plan_meta"] = plan_meta
    return updates


__all__ = ["AGENT_CORE_V2", "make_loop_agent_node"]
