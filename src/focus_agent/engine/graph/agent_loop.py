from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from langchain.messages import AIMessage, SystemMessage, ToolMessage
from langgraph.runtime import Runtime

from ...agent_delegation import build_failure_records, build_review_queue
from ...agent_roles import AgentRole
from ...capabilities import ToolRegistry
from ...capabilities.tool_registry import ToolRuntimeMeta
from ...capabilities.tool_router import build_tool_route_plan, infer_tool_router_role
from ...config import Settings
from ...core.context.policy import apply_prompt_budget_guard
from ...core.repo_call import has_repo_method
from ...core.request_context import RequestContext
from ...core.state import AgentState, append_agent_state_record
from ...core.types import Plan
from ...skills import SkillRegistry
from ...transport.stream_events import STREAM_VISIBILITY_QUARANTINE, STREAM_VISIBILITY_VISIBLE
from ..graph_evidence import (
    evidence_bundle_to_citation_refs,
    normalize_evidence_bundle,
    normalize_evidence_ledger,
)
from ..graph_execution_contract import (
    build_execution_contract,
    evaluate_execution_contract,
    tool_result_names,
    verify_answer_against_evidence,
)
from ..graph_plan_nodes import _format_plan_block
from ..graph_tool_result_fallback import _should_replace_unfound_workspace_answer
from ..graph_turn_helpers import (
    _TOOL_EXHAUSTION_NOTE,
    _context_budget_from_state,
    _ensure_reasoning_content_for_tool_call_history,
    _fallback_answer_from_tool_results,
    _invoke_with_tool_result_fallback,
    _known_tool_names,
    _latest_human_message_text,
    _latest_turn_messages,
    _live_web_research_should_start_with_search,
    _looks_like_textual_tool_call_artifact,
    _messages_for_model,
    _repair_and_dedupe_tool_calls,
    _repair_textual_tool_call_response,
    _repair_tool_free_answer_response,
    _should_force_tool_free_answer,
    _tool_policy_note,
    _tools_for_policy,
    _workspace_lookup_should_start_with_search,
    _workspace_search_query,
)
from .policy import (
    _is_tool_carryover_confirmation,
    _temporal_live_web_search_args,
    _tool_intent_plan_requires_temporal_anchor,
    _turn_tool_exposure_from_intent_plan,
    build_tool_intent_plan,
)


def _with_stream_phase(model: Any, phase: str) -> Any:
    if not has_repo_method(model, "with_config"):
        return model
    return model.with_config(
        {
            "metadata": {"stream_phase": phase},
            "tags": [f"stream_phase:{phase}"],
        }
    )


def _model_for_stream_phase(
    model_for: Callable[[str, str], Any], phase: str
) -> Callable[[str, str], Any]:
    def wrapped(model_id: str, thinking_mode: str) -> Any:
        return _with_stream_phase(model_for(model_id, thinking_mode), phase)

    return wrapped


def _model_with_tools_for_stream_phase(
    model_with_tools_for: Callable[[str, str, list[Any] | None], Any],
    phase: str,
) -> Callable[[str, str, list[Any] | None], Any]:
    def wrapped(model_id: str, thinking_mode: str, available_tools: list[Any] | None) -> Any:
        return _with_stream_phase(
            model_with_tools_for(model_id, thinking_mode, available_tools), phase
        )

    return wrapped


def make_agent_loop_node(
    *,
    settings: Settings,
    tools: Sequence[Any],
    tool_registry: ToolRegistry,
    skill_registry: SkillRegistry | None = None,
    model_for: Callable[[str, str], Any],
    model_with_tools_for: Callable[[str, str, list[Any] | None], Any],
) -> Any:
    all_tools = list(tools)

    def agent_loop(
        state: AgentState,
        runtime: Runtime[RequestContext],
    ) -> dict[str, Any]:
        del runtime
        state_messages = list(state.get("messages", []) or [])
        messages = _messages_for_model(state)
        fallback_messages = _latest_turn_messages(state_messages or messages)
        selected_model = str(state.get("selected_model") or settings.model)
        selected_thinking_mode = str(state.get("selected_thinking_mode") or "")
        assembled = state.get("assembled_context", "")
        latest_user = _latest_human_message_text(state_messages)
        if not latest_user:
            latest_user = _latest_human_message_text(messages) or str(state.get("task_brief") or "")
        tool_intent_text = _tool_intent_text(state, latest_user)
        context_budget = _context_budget_from_state(state)
        pending_tool_action = _pending_live_web_search_action_from_state(
            state,
            latest_user=tool_intent_text,
        )
        tool_intent_plan = build_tool_intent_plan(
            tool_intent_text,
            active_skill_ids=list(state.get("active_skill_ids", []) or ()),
            pending_tool_action=pending_tool_action,
        )
        tool_policy = tool_intent_plan.policy
        temporal_anchor_required = _tool_intent_plan_requires_temporal_anchor(tool_intent_plan)
        current_utc_time_result = _latest_tool_result_content(state_messages, "current_utc_time")
        if tool_policy == "live_web_research" and current_utc_time_result:
            anchored_args = _temporal_live_web_search_args(
                tool_intent_plan.preferred_first_args,
                fallback_query=tool_intent_text,
                current_utc_time=current_utc_time_result,
            )
            if anchored_args and anchored_args != tool_intent_plan.preferred_first_args:
                tool_intent_plan = tool_intent_plan.model_copy(
                    update={"preferred_first_args": anchored_args}
                )
        tool_exposure = _turn_tool_exposure_from_intent_plan(tool_intent_plan)
        temporal_anchor_forced = False
        available_tools = _tools_for_policy_compat(
            tool_policy,
            all_tools,
            tool_intent_text,
            exposure=tool_exposure,
        )
        available_tools = _merge_active_skill_recommended_tools(
            available_tools,
            all_tools,
            skill_registry=skill_registry,
            active_skill_ids=list(state.get("active_skill_ids", []) or ()),
            tool_policy=tool_policy,
        )
        tool_route_plan = None
        if settings.agent_tool_router_enabled:
            router_role = infer_tool_router_role(
                state.get("role_route_plan"),
                fallback=_tool_router_fallback_role(tool_policy, tool_exposure),
            )
            tool_route_plan = build_tool_route_plan(
                tool_registry=tool_registry,
                role=router_role,
                tool_policy=tool_policy,
                available_tool_names=_registered_tool_names(tool_registry, all_tools),
                exposed_tool_names=[str(getattr(tool, "name", "")) for tool in available_tools],
                confidence=getattr(tool_exposure, "confidence", None),
                reason_codes=getattr(tool_exposure, "reason_codes", None),
                intent_source=tool_intent_plan.source,
                preferred_first_tool=tool_intent_plan.preferred_first_tool,
                preferred_first_args=tool_intent_plan.preferred_first_args,
                enforce=bool(settings.agent_tool_router_enforce),
            )
            if settings.agent_tool_router_enforce:
                allowed = set(tool_route_plan.allowed_tools)
                available_tools = [
                    tool for tool in available_tools if str(getattr(tool, "name", "")) in allowed
                ]
        known_names = _known_tool_names(available_tools)
        execution_contract = build_execution_contract(
            policy=tool_policy,
            temporal_anchor_required=temporal_anchor_required,
            available_tool_names=known_names,
        )
        quarantined_model_for = _model_for_stream_phase(model_for, STREAM_VISIBILITY_QUARANTINE)
        quarantined_model_with_tools_for = _model_with_tools_for_stream_phase(
            model_with_tools_for,
            STREAM_VISIBILITY_QUARANTINE,
        )
        tool_protocol_repair_count = 0
        tool_protocol_repair_reason = ""
        policy_note = _tool_policy_note(tool_policy)
        plan = state.get("plan")
        if isinstance(plan, Plan) and plan.steps:
            plan_block = _format_plan_block(plan, state.get("current_step_id", ""))
            if plan_block and plan_block not in assembled:
                assembled = f"{assembled}\n\n{plan_block}".strip()
        prompt_messages = [SystemMessage(content=assembled), *messages]
        if policy_note:
            prompt_messages = [
                prompt_messages[0],
                SystemMessage(content=policy_note),
                *prompt_messages[1:],
            ]
        prompt_messages = apply_prompt_budget_guard(prompt_messages, budget=context_budget)
        prompt_messages = _ensure_reasoning_content_for_tool_call_history(
            prompt_messages,
            model_id=selected_model,
            thinking_mode=selected_thinking_mode,
            settings=settings,
        )
        if _should_force_tool_free_answer(state_messages):
            forced_prompt = apply_prompt_budget_guard(
                [
                    prompt_messages[0],
                    SystemMessage(content=_TOOL_EXHAUSTION_NOTE),
                    *prompt_messages[1:],
                ],
                budget=context_budget,
            )
            forced_prompt = _ensure_reasoning_content_for_tool_call_history(
                forced_prompt,
                model_id=selected_model,
                thinking_mode=selected_thinking_mode,
                settings=settings,
            )
            response = _invoke_with_tool_result_fallback(
                _with_stream_phase(
                    model_for(selected_model, selected_thinking_mode),
                    STREAM_VISIBILITY_VISIBLE,
                ),
                forced_prompt,
                fallback_messages=fallback_messages,
                known_tool_names=known_names,
            )
            if _looks_like_textual_tool_call_artifact(response, known_tool_names=known_names):
                tool_protocol_repair_count += 1
                tool_protocol_repair_reason = "textual_tool_marker"
            response = _repair_tool_free_answer_response(
                response=response,
                prompt_messages=prompt_messages,
                fallback_messages=fallback_messages,
                context_budget=context_budget,
                selected_model=selected_model,
                selected_thinking_mode=selected_thinking_mode,
                model_for=quarantined_model_for,
            )
        elif (
            tool_policy == "live_web_research"
            and temporal_anchor_required
            and _has_tool_named(available_tools, "current_utc_time")
            and not _latest_turn_has_tool_result(state_messages, "current_utc_time")
        ):
            temporal_anchor_forced = True
            response = AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": f"current-utc-time-{state.get('llm_calls', 0) + 1}",
                        "name": "current_utc_time",
                        "args": {},
                    }
                ],
            )
        elif (
            tool_policy == "live_web_research"
            and _has_tool_named(available_tools, "web_search")
            and _live_web_contract_needs_search(state_messages)
        ):
            response = AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": f"live-web-search-{state.get('llm_calls', 0) + 1}",
                        "name": "web_search",
                        "args": tool_intent_plan.preferred_first_args
                        or {"query": tool_intent_text},
                    }
                ],
            )
        elif (
            tool_policy == "live_web_research"
            and _live_web_research_should_start_with_search_compat(
                tool_intent_text,
                state_messages,
                available_tools,
                exposure=tool_exposure,
            )
        ):
            response = AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": f"live-web-search-{state.get('llm_calls', 0) + 1}",
                        "name": "web_search",
                        "args": tool_intent_plan.preferred_first_args
                        or {"query": tool_intent_text},
                    }
                ],
            )
        elif (
            tool_policy == "workspace_lookup"
            and tool_intent_plan.preferred_first_tool == "skills_search"
            and _has_tool_named(available_tools, "skills_search")
            and not _latest_turn_has_tool_result(state_messages, "skills_search")
        ):
            response = AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": f"skills-search-{state.get('llm_calls', 0) + 1}",
                        "name": "skills_search",
                        "args": tool_intent_plan.preferred_first_args
                        or {"query": tool_intent_text},
                    }
                ],
            )
        elif (
            tool_policy == "workspace_lookup"
            and _workspace_lookup_should_start_with_search_compat(
                tool_intent_text,
                state_messages,
                available_tools,
                exposure=tool_exposure,
            )
        ):
            response = AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": f"workspace-search-{state.get('llm_calls', 0) + 1}",
                        "name": "search_code",
                        "args": tool_intent_plan.preferred_first_args
                        or {"query": _workspace_search_query(tool_intent_text)},
                    }
                ],
            )
        elif not available_tools:
            response = _invoke_with_tool_result_fallback(
                _with_stream_phase(
                    model_for(selected_model, selected_thinking_mode),
                    STREAM_VISIBILITY_VISIBLE,
                ),
                prompt_messages,
                fallback_messages=fallback_messages,
                known_tool_names=known_names,
            )
            if _looks_like_textual_tool_call_artifact(response, known_tool_names=known_names):
                tool_protocol_repair_count += 1
                tool_protocol_repair_reason = "textual_tool_marker"
            response = _repair_tool_free_answer_response(
                response=response,
                prompt_messages=prompt_messages,
                fallback_messages=fallback_messages,
                context_budget=context_budget,
                selected_model=selected_model,
                selected_thinking_mode=selected_thinking_mode,
                model_for=quarantined_model_for,
            )
        else:
            response = _invoke_with_tool_result_fallback(
                _with_stream_phase(
                    model_with_tools_for(selected_model, selected_thinking_mode, available_tools),
                    STREAM_VISIBILITY_QUARANTINE,
                ),
                prompt_messages,
                fallback_messages=fallback_messages,
                known_tool_names=known_names,
            )
            if _looks_like_textual_tool_call_artifact(response, known_tool_names=known_names):
                tool_protocol_repair_count += 1
                tool_protocol_repair_reason = "textual_tool_marker"
            response = _repair_textual_tool_call_response(
                response=response,
                prompt_messages=prompt_messages,
                fallback_messages=fallback_messages,
                context_budget=context_budget,
                selected_model=selected_model,
                selected_thinking_mode=selected_thinking_mode,
                available_tools=available_tools,
                model_for=quarantined_model_for,
                model_with_tools_for=quarantined_model_with_tools_for,
            )
        response = _repair_and_dedupe_tool_calls(response)
        completed_turn_messages = _latest_turn_messages([*state_messages, response])
        if not getattr(response, "tool_calls", None) and _should_replace_unfound_workspace_answer(
            _message_content_text(response),
            completed_turn_messages,
        ):
            response = AIMessage(
                content=_fallback_answer_from_tool_results(completed_turn_messages)
            )
            completed_turn_messages = _latest_turn_messages([*state_messages, response])
            tool_protocol_repair_reason = (
                tool_protocol_repair_reason or "workspace_evidence_fallback"
            )
        observed_at = _latest_tool_result_content(completed_turn_messages, "current_utc_time")
        evidence_bundle = normalize_evidence_bundle(
            completed_turn_messages,
            observed_at=observed_at or None,
            user_query=tool_intent_text,
        )
        evidence_ledger = normalize_evidence_ledger(
            completed_turn_messages,
            observed_at=observed_at or None,
            user_query=tool_intent_text,
        )
        execution_contract = evaluate_execution_contract(
            execution_contract,
            tool_results_seen=tool_result_names(completed_turn_messages),
            evidence_ledger=evidence_ledger,
            available_tool_names=known_names,
            observed_at=observed_at or None,
            user_query=tool_intent_text,
        )
        answer_verification = verify_answer_against_evidence(
            answer=_message_content_text(response)
            if not getattr(response, "tool_calls", None)
            else "",
            contract=execution_contract,
            evidence_ledger=evidence_ledger,
        )
        live_web_repair_count = _live_web_answer_repair_count(state)
        live_web_repair_taken = ""
        if (
            tool_policy == "live_web_research"
            and not getattr(response, "tool_calls", None)
            and _live_web_answer_needs_repair(answer_verification)
        ):
            repair_response = _live_web_repair_response(
                state=state,
                available_tools=available_tools,
                tool_intent_plan=tool_intent_plan.model_dump(mode="json"),
                fallback_query=tool_intent_text,
                current_utc_time=observed_at or current_utc_time_result,
                repair_count=live_web_repair_count,
                verification=answer_verification,
                execution_contract=execution_contract,
            )
            if repair_response is not None:
                response = repair_response
                completed_turn_messages = _latest_turn_messages([*state_messages, response])
                answer_verification = {
                    **answer_verification,
                    "repair_action_taken": "retry_web_search",
                }
                live_web_repair_taken = "retry_web_search"
            else:
                response = AIMessage(
                    content=_live_web_failure_answer(
                        verification=answer_verification,
                        execution_contract=execution_contract,
                        evidence_ledger=evidence_ledger,
                    )
                )
                completed_turn_messages = _latest_turn_messages([*state_messages, response])
                answer_verification = {
                    **answer_verification,
                    "repair_action_taken": "answer_with_uncertainty",
                }
                live_web_repair_taken = "answer_with_uncertainty"
        citation_refs = _new_citation_refs(
            evidence_bundle_to_citation_refs(evidence_bundle),
            existing=list(state.get("citations", []) or []),
        )
        web_tool_result_seen = _latest_turn_has_tool_result(
            state_messages, "web_search"
        ) or _latest_turn_has_tool_result(
            state_messages,
            "web_fetch",
        )
        external_answer_missing_citation = bool(
            tool_policy == "live_web_research"
            and web_tool_result_seen
            and not getattr(response, "tool_calls", None)
            and _message_content_text(response)
            and not citation_refs
            and not state.get("citations")
        )
        updates: dict[str, Any] = {
            "messages": [response],
            "llm_calls": state.get("llm_calls", 0) + 1,
            "evidence_bundle": evidence_bundle,
            "evidence_ledger": evidence_ledger,
            "execution_contract": execution_contract,
            "answer_verification": answer_verification,
        }
        if citation_refs:
            updates["citations"] = citation_refs
        intent_dumped = tool_intent_plan.model_dump(mode="json")
        if temporal_anchor_required:
            intent_dumped["temporal_anchor_required"] = True
        if temporal_anchor_forced:
            intent_dumped["temporal_anchor_forced"] = True
        if external_answer_missing_citation:
            intent_dumped["external_answer_missing_citation"] = True
        if live_web_repair_taken:
            intent_dumped["live_web_answer_repair_action_taken"] = live_web_repair_taken
            if live_web_repair_taken == "retry_web_search":
                intent_dumped["live_web_answer_repair_count"] = live_web_repair_count + 1
        updates["pending_tool_action"] = _next_pending_tool_action(
            state=state,
            tool_intent_plan=intent_dumped,
            response=response,
            web_tool_result_seen=web_tool_result_seen,
        )
        append_agent_state_record(
            updates,
            "tool_intent_plan",
            intent_dumped,
            source="agent_loop",
        )
        append_agent_state_record(
            updates,
            "execution_contract",
            execution_contract,
            source="agent_loop",
            domain="observability",
        )
        append_agent_state_record(
            updates,
            "answer_verification",
            answer_verification,
            source="agent_loop",
            domain="observability",
        )
        updates["plan_meta"] = {
            **(state.get("plan_meta") or {}),
            "tool_intent_plan": intent_dumped,
            "execution_contract": execution_contract,
            "evidence_ledger": evidence_ledger,
            "answer_verification": answer_verification,
        }
        if live_web_repair_taken == "retry_web_search":
            updates["plan_meta"]["live_web_answer_repair_count"] = live_web_repair_count + 1
        if tool_route_plan is not None:
            dumped = tool_route_plan.model_dump(mode="json")
            append_agent_state_record(
                updates,
                "tool_route_plan",
                dumped,
                source="agent_loop",
            )
            plan_meta = {
                **(updates.get("plan_meta") or state.get("plan_meta") or {}),
                "tool_route_plan": dumped,
            }
            if settings.agent_self_repair_enabled:
                failures = [
                    item.model_dump(mode="json")
                    for item in build_failure_records(
                        delegation_plan=state.get("agent_delegation_plan"),
                        tool_route_plan=dumped,
                        model_route_decision=state.get("model_route_decision"),
                    )
                ]
                append_agent_state_record(
                    updates,
                    "agent_failure_records",
                    failures,
                    source="agent_loop",
                )
                plan_meta["agent_failure_records"] = failures
            if settings.agent_review_queue_enabled:
                review_items = [
                    item.model_dump(mode="json")
                    for item in build_review_queue(
                        settings=settings,
                        memory_curator_decision=state.get("memory_curator_decision"),
                        tool_route_plan=dumped,
                        model_route_decision=state.get("model_route_decision"),
                        agent_failure_records=updates.get("agent_failure_records")
                        or state.get("agent_failure_records")
                        or [],
                    )
                ]
                append_agent_state_record(
                    updates,
                    "agent_review_queue",
                    review_items,
                    source="agent_loop",
                )
                plan_meta["agent_review_queue"] = review_items
            if updates.get("governance_records"):
                plan_meta["governance_records"] = [
                    *list(plan_meta.get("governance_records") or []),
                    *list(updates.get("governance_records") or []),
                ]
            updates["plan_meta"] = plan_meta
        if tool_protocol_repair_count:
            current_plan_meta = updates.get("plan_meta") or state.get("plan_meta") or {}
            plan_meta = {
                **current_plan_meta,
                "tool_protocol_repair_count": int(
                    current_plan_meta.get("tool_protocol_repair_count", 0)
                )
                + tool_protocol_repair_count,
                "tool_protocol_repair_reason": tool_protocol_repair_reason,
            }
            updates["plan_meta"] = plan_meta
        return updates

    return agent_loop


def _tools_for_policy_compat(
    tool_policy: str,
    tools: list[Any],
    latest_user: str,
    *,
    exposure: Any | None,
) -> list[Any]:
    if exposure is not None and _accepts_keyword(_tools_for_policy, "exposure"):
        return _tools_for_policy(tool_policy, tools, latest_user, exposure=exposure)
    return _tools_for_policy(tool_policy, tools, latest_user)


def _merge_active_skill_recommended_tools(
    available_tools: list[Any],
    all_tools: list[Any],
    *,
    skill_registry: SkillRegistry | None,
    active_skill_ids: list[Any],
    tool_policy: str,
) -> list[Any]:
    recommended_names = _active_skill_recommended_tool_names(skill_registry, active_skill_ids)
    if not recommended_names:
        return available_tools
    by_name = {str(getattr(tool, "name", "")): tool for tool in all_tools}
    merged = list(available_tools)
    seen = {str(getattr(tool, "name", "")) for tool in merged}
    for tool_name in recommended_names:
        if tool_name in seen:
            continue
        tool = by_name.get(tool_name)
        if tool is None or not _recommended_tool_allowed_for_policy(tool, tool_policy):
            continue
        merged.append(tool)
        seen.add(tool_name)
    return merged


def _active_skill_recommended_tool_names(
    skill_registry: SkillRegistry | None,
    active_skill_ids: list[Any],
) -> tuple[str, ...]:
    if skill_registry is None:
        return ()
    names: list[str] = []
    seen: set[str] = set()
    for raw_skill_id in active_skill_ids:
        skill_id = str(raw_skill_id).strip()
        if not skill_id:
            continue
        skill = skill_registry.resolve(skill_id)
        if skill is None:
            continue
        for raw_tool_name in skill.recommended_tools:
            tool_name = str(raw_tool_name).strip()
            if tool_name and tool_name not in seen:
                seen.add(tool_name)
                names.append(tool_name)
    return tuple(names)


def _recommended_tool_allowed_for_policy(tool: Any, tool_policy: str) -> bool:
    if tool_policy == "direct_answer":
        return False
    runtime = ToolRuntimeMeta.from_tool(tool)
    if tool_policy == "workspace_lookup":
        return not (
            runtime.requires_network or runtime.requires_workspace_write or runtime.side_effect
        )
    if tool_policy == "live_web_research":
        return not runtime.requires_workspace_write
    return True


def _live_web_research_should_start_with_search_compat(
    latest_user: str,
    state_messages: list[Any],
    available_tools: list[Any],
    *,
    exposure: Any | None,
) -> bool:
    if exposure is not None and _accepts_keyword(
        _live_web_research_should_start_with_search,
        "exposure",
    ):
        return _live_web_research_should_start_with_search(
            latest_user,
            state_messages,
            available_tools,
            exposure=exposure,
        )
    return _live_web_research_should_start_with_search(
        latest_user,
        state_messages,
        available_tools,
    )


def _workspace_lookup_should_start_with_search_compat(
    latest_user: str,
    state_messages: list[Any],
    available_tools: list[Any],
    *,
    exposure: Any | None,
) -> bool:
    if exposure is not None and _accepts_keyword(
        _workspace_lookup_should_start_with_search,
        "exposure",
    ):
        return _workspace_lookup_should_start_with_search(
            latest_user,
            state_messages,
            available_tools,
            exposure=exposure,
        )
    return _workspace_lookup_should_start_with_search(
        latest_user,
        state_messages,
        available_tools,
    )


def _tool_router_fallback_role(tool_policy: str, exposure: Any | None) -> AgentRole:
    if tool_policy == "live_web_research":
        return AgentRole.PLANNER
    if set(getattr(exposure, "allowed_toolsets", ()) or ()) == {"skill"}:
        return AgentRole.SKILL_SCOUT
    if tool_policy == "execution" and set(getattr(exposure, "allowed_toolsets", ()) or ()) == {
        "web",
        "workspace",
    }:
        return AgentRole.PLANNER
    return AgentRole.EXECUTOR


def _tool_intent_text(state: AgentState, latest_user: str) -> str:
    task_brief = str(state.get("task_brief") or "").strip()
    if task_brief and state.get("active_skill_ids"):
        return task_brief
    return latest_user


def _pending_live_web_search_action_from_state(
    state: AgentState,
    *,
    latest_user: str,
) -> Mapping[str, Any] | None:
    if not _is_tool_carryover_confirmation(latest_user):
        return None
    pending = state.get("pending_tool_action")
    if isinstance(pending, Mapping) and not _pending_tool_action_expired(pending, state):
        return pending
    prior_plan = state.get("tool_intent_plan")
    if _is_pending_live_web_search_mapping(prior_plan):
        return prior_plan
    return _prior_live_web_search_intent_from_messages(
        list(state.get("messages", []) or ()),
        active_skill_ids=list(state.get("active_skill_ids", []) or ()),
    )


def _is_pending_live_web_search_mapping(raw: Any) -> bool:
    if not isinstance(raw, Mapping):
        return False
    return (
        str(raw.get("policy") or "").strip() == "live_web_research"
        and str(raw.get("preferred_first_tool") or "").strip() == "web_search"
    )


def _prior_live_web_search_intent_from_messages(
    messages: list[Any],
    *,
    active_skill_ids: list[Any],
) -> Mapping[str, Any] | None:
    latest_human_index = _latest_human_index(messages)
    if latest_human_index <= 0:
        return None
    for message in reversed(messages[:latest_human_index]):
        if getattr(message, "type", None) != "human":
            continue
        prior_text = str(getattr(message, "content", "") or "").strip()
        if not prior_text:
            continue
        prior_plan = build_tool_intent_plan(
            prior_text,
            active_skill_ids=active_skill_ids,
        )
        if (
            prior_plan.policy == "live_web_research"
            and prior_plan.preferred_first_tool == "web_search"
        ):
            return prior_plan.model_dump(mode="json")
        return None
    return None


def _latest_human_index(messages: list[Any]) -> int:
    latest = -1
    for index, message in enumerate(messages):
        if getattr(message, "type", None) == "human":
            latest = index
    return latest


def _current_turn_index(state: AgentState) -> int:
    return sum(
        1
        for message in list(state.get("messages", []) or ())
        if getattr(message, "type", None) == "human"
    )


def _pending_tool_action_expired(raw: Mapping[str, Any], state: AgentState) -> bool:
    expires_after_turns = _coerce_int(raw.get("expires_after_turns"), default=2)
    created_turn_index = _coerce_int(
        raw.get("created_turn_index"), default=_current_turn_index(state)
    )
    return (_current_turn_index(state) - created_turn_index) > expires_after_turns


def _coerce_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _has_tool_named(tools: list[Any], name: str) -> bool:
    return any(str(getattr(tool, "name", "")) == name for tool in tools)


def _latest_turn_has_tool_result(messages: list[Any], tool_name: str) -> bool:
    latest_human_index = _latest_human_index(messages)
    call_names_by_id: dict[str, str] = {}
    for message in messages[latest_human_index + 1 :]:
        for call in getattr(message, "tool_calls", None) or ():
            if not isinstance(call, Mapping):
                continue
            call_id = str(call.get("id") or "").strip()
            name = str(call.get("name") or "").strip()
            if call_id and name:
                call_names_by_id[call_id] = name
        if isinstance(message, ToolMessage):
            if call_names_by_id.get(str(message.tool_call_id or "").strip()) == tool_name:
                return True
    return False


def _live_web_contract_needs_search(messages: list[Any]) -> bool:
    return not (
        _latest_turn_has_tool_result(messages, "web_search")
        or _latest_turn_has_tool_result(messages, "web_fetch")
    )


def _latest_tool_result_content(messages: list[Any], tool_name: str) -> str:
    call_names_by_id: dict[str, str] = {}
    latest = ""
    for message in messages:
        for call in getattr(message, "tool_calls", None) or ():
            if not isinstance(call, Mapping):
                continue
            call_id = str(call.get("id") or "").strip()
            name = str(call.get("name") or "").strip()
            if call_id and name:
                call_names_by_id[call_id] = name
        if isinstance(message, ToolMessage):
            if call_names_by_id.get(str(message.tool_call_id or "").strip()) == tool_name:
                latest = _message_content_text(message)
    return latest


def _message_content_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content.strip()
    return str(content or "").strip()


def _new_citation_refs(
    citation_refs: list[dict[str, str | None]],
    *,
    existing: list[Any],
) -> list[dict[str, str | None]]:
    seen = {_citation_key(item) for item in existing}
    unique: list[dict[str, str | None]] = []
    for item in citation_refs:
        key = _citation_key(item)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _citation_key(item: Any) -> tuple[str, str]:
    if isinstance(item, Mapping):
        return (str(item.get("uri") or ""), str(item.get("label") or ""))
    return (
        str(getattr(item, "uri", "") or ""),
        str(getattr(item, "label", "") or ""),
    )


def _next_pending_tool_action(
    *,
    state: AgentState,
    tool_intent_plan: Mapping[str, Any],
    response: AIMessage,
    web_tool_result_seen: bool,
) -> dict[str, Any] | None:
    if getattr(response, "tool_calls", None) or web_tool_result_seen:
        return None
    if (
        str(tool_intent_plan.get("policy") or "") != "live_web_research"
        or str(tool_intent_plan.get("preferred_first_tool") or "") != "web_search"
    ):
        return None
    args = tool_intent_plan.get("preferred_first_args")
    query = ""
    if isinstance(args, Mapping):
        query = str(args.get("query") or "").strip()
    if not query:
        query = str(tool_intent_plan.get("normalized_text") or "").strip()
    if not query:
        return None
    return {
        "policy": "live_web_research",
        "tool": "web_search",
        "query": query,
        "preferred_first_tool": "web_search",
        "preferred_first_args": {"query": query},
        "requires_confirmation": True,
        "created_turn_index": _current_turn_index(state),
        "expires_after_turns": 2,
    }


def _live_web_answer_repair_count(state: AgentState) -> int:
    plan_meta = state.get("plan_meta")
    if isinstance(plan_meta, Mapping):
        return _coerce_int(plan_meta.get("live_web_answer_repair_count"), default=0)
    return 0


def _live_web_answer_needs_repair(verification: Mapping[str, Any]) -> bool:
    status = str(verification.get("status") or "")
    repair_action = str(verification.get("repair_action") or "")
    return status in {"unsupported", "blocked"} or repair_action in {
        "call_missing_tool",
        "refresh_stale_evidence",
    }


def _live_web_repair_response(
    *,
    state: AgentState,
    available_tools: list[Any],
    tool_intent_plan: Mapping[str, Any],
    fallback_query: str,
    current_utc_time: str | None,
    repair_count: int,
    verification: Mapping[str, Any],
    execution_contract: Mapping[str, Any],
) -> AIMessage | None:
    if repair_count >= 1:
        return None
    if not _has_tool_named(available_tools, "web_search"):
        return None
    contract_status = str(execution_contract.get("status") or "")
    repair_action = str(verification.get("repair_action") or "")
    if contract_status == "blocked":
        return None
    if repair_action not in {"call_missing_tool", "refresh_stale_evidence"}:
        return None
    if repair_action == "call_missing_tool":
        state_messages = list(state.get("messages", []) or [])
        if _latest_turn_has_tool_result(
            state_messages, "web_search"
        ) or _latest_turn_has_tool_result(state_messages, "web_fetch"):
            return None
    preferred_args = tool_intent_plan.get("preferred_first_args")
    search_args = _temporal_live_web_search_args(
        preferred_args if isinstance(preferred_args, Mapping) else None,
        fallback_query=fallback_query,
        current_utc_time=current_utc_time,
    ) or {"query": fallback_query}
    query = str(search_args.get("query") or fallback_query).strip()
    if repair_action == "refresh_stale_evidence" and "刷新过期证据" not in query:
        query = f"{query}（刷新过期证据；只返回与原始查询直接相关的最新来源）"
    return AIMessage(
        content="",
        tool_calls=[
            {
                "id": f"live-web-repair-search-{_current_turn_index(state) + 1}",
                "name": "web_search",
                "args": {"query": query},
            }
        ],
    )


def _live_web_failure_answer(
    *,
    verification: Mapping[str, Any],
    execution_contract: Mapping[str, Any],
    evidence_ledger: Sequence[Mapping[str, Any]],
) -> str:
    user_query = str(execution_contract.get("user_query") or "").strip()
    unsupported = [
        str(item)
        for item in verification.get("unsupported_claims", []) or []
        if str(item).strip()
    ]
    missing = [
        str(item)
        for item in execution_contract.get("missing", []) or []
        if str(item).strip()
    ]
    if verification.get("stale_evidence"):
        reason = "检索结果没有提供足够新的证据"
    elif missing:
        reason = f"缺少必要工具结果：{', '.join(missing)}"
    elif unsupported:
        reason = unsupported[0]
    else:
        reason = "检索证据不足以支撑一个可靠结论"
    evidence_dates = _evidence_date_summary(evidence_ledger)
    parts = [
        "我不能可靠确认这个实时问题的答案。",
        f"原因：{reason}。",
    ]
    if user_query:
        parts.append(f"原始问题：{user_query}。")
    if evidence_dates:
        parts.append(f"已见证据时间：{evidence_dates}。")
    parts.append("建议稍后重新检索，或提供一个明确来源让我核对。")
    return "\n".join(parts)


def _evidence_date_summary(evidence_ledger: Sequence[Mapping[str, Any]]) -> str:
    dates: list[str] = []
    for item in evidence_ledger:
        if not isinstance(item, Mapping):
            continue
        value = str(item.get("published_at") or item.get("observed_at") or "").strip()
        if value and value not in dates:
            dates.append(value)
        if len(dates) >= 3:
            break
    return ", ".join(dates)


def _registered_tool_names(tool_registry: ToolRegistry, tools: Sequence[Any]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()

    def add(raw_name: Any) -> None:
        name = str(raw_name or "").strip()
        if not name or name in seen:
            return
        seen.add(name)
        names.append(name)

    for tool in tuple(getattr(tool_registry, "tools", ()) or ()):
        add(getattr(tool, "name", ""))
    for mapping_name in ("by_name", "runtime_by_name", "manifest_by_name"):
        mapping = getattr(tool_registry, mapping_name, None)
        if isinstance(mapping, dict):
            for name in mapping:
                add(name)
    for tool in tools:
        add(getattr(tool, "name", ""))
    return names


def _accepts_keyword(function: Callable[..., Any], keyword: str) -> bool:
    try:
        signature = inspect.signature(function)
    except (TypeError, ValueError):
        return False
    return keyword in signature.parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )


__all__ = ["make_agent_loop_node"]
