from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from langchain.messages import AIMessage, SystemMessage
from langgraph.runtime import Runtime

from ...agent_delegation import build_failure_records, build_review_queue
from ...capabilities import ToolRegistry
from ...capabilities.tool_router import build_tool_route_plan, infer_tool_router_role
from ...config import Settings
from ...core.context.policy import apply_prompt_budget_guard
from ...core.repo_call import has_repo_method
from ...core.request_context import RequestContext
from ...core.runtime_outcome import build_task_outcome
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
    skill_execution_evidence_facts,
    tool_result_names,
    verify_answer_against_evidence,
)
from ..graph_plan_nodes import _format_plan_block
from ..graph_tool_result_fallback import _should_replace_unfound_workspace_answer
from ..graph_turn_helpers import (
    _TOOL_EXHAUSTION_NOTE,
    _context_budget_from_state,
    _degraded_answer_from_tool_results,
    _ensure_reasoning_content_for_tool_call_history,
    _fallback_answer_from_tool_results,
    _invoke_with_tool_result_fallback,
    _known_tool_names,
    _latest_human_message_text,
    _latest_turn_messages,
    _looks_like_textual_tool_call_artifact,
    _messages_for_model,
    _repair_and_dedupe_tool_calls,
    _repair_textual_tool_call_response,
    _repair_tool_free_answer_response,
    _should_force_tool_free_answer,
    _tool_policy_note,
    _workspace_search_query,
)
from . import agent_loop_support as _agent_loop_support
from .agent_loop_helpers import (
    _has_tool_named,
    _latest_tool_result_content,
    _latest_turn_has_tool_result,
    _live_web_answer_needs_repair,
    _live_web_answer_repair_count,
    _live_web_contract_needs_search,
    _live_web_failure_answer,
    _live_web_repair_response,
    _live_web_research_should_start_with_search_compat,
    _merge_active_skill_recommended_tools,
    _message_content_text,
    _new_citation_refs,
    _next_pending_tool_action,
    _pending_live_web_search_action_from_state,
    _registered_tool_names,
    _skill_execution_answer_repair_count,
    _skill_execution_failure_answer,
    _skill_execution_repair_prompt,
    _tool_intent_text,
    _tool_router_fallback_role,
    _tools_for_policy_compat,
    _workspace_lookup_should_start_with_search_compat,
    apply_skill_execution_plan,
    build_active_skill_execution_plan,
    skill_execution_policy_note,
)
from .agent_loop_skill_helpers import _READ_ONLY_SKILL_TOOL_RE  # noqa: F401
from .agent_loop_skill_helpers import (
    explicit_skill_tools_satisfied as _explicit_skill_tools_satisfied,
)
from .agent_loop_skill_helpers import (
    skill_install_args_from_search_result as _skill_install_args_from_search_result,
)
from .agent_loop_support import (
    _ALTERNATIVE_OUTCOME_ROLES,  # noqa: F401
    _FAILED_OUTCOME_STATUSES,  # noqa: F401
    _HTTP_URL_RE,  # noqa: F401
    _PRIMARY_OUTCOME_ROLES,  # noqa: F401
    _SUCCESS_OUTCOME_STATUSES,  # noqa: F401
    _drain_steer_messages,
    _estimate_context_fullness,
    _filter_tools_by_agent_def,
    _fire_system_agent_trigger,
    _outcome_attempt_index,  # noqa: F401
    _outcome_max_attempts,  # noqa: F401
    _resolve_agent_definition,
    _should_force_degraded_skill_recovery_answer,
    _web_fetch_args,
    _with_focus_agent_turn_metadata,
)
from .agent_loop_updates import finalize_agent_loop_turn
from .policy import (
    _skill_install_name_from_text,
    _skill_view_name_from_text,
    _temporal_live_web_search_args,
    _tool_intent_plan_requires_temporal_anchor,
    _turn_tool_exposure_from_intent_plan,
    build_tool_intent_plan,
)

_logger = logging.getLogger(__name__)


def _with_stream_phase(model: Any, phase: str) -> Any:
    """Apply stream metadata while preserving the established patch seam."""

    return _agent_loop_support._with_stream_phase(
        model,
        phase,
        has_method=has_repo_method,
    )


def _model_for_stream_phase(
    model_for: Callable[[str, str], Any],
    phase: str,
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
            model_with_tools_for(model_id, thinking_mode, available_tools),
            phase,
        )

    return wrapped


def _agent_loop_update_hooks(
    model_with_tools_for: Callable[[str, str, list[Any] | None], Any],
) -> dict[str, Any]:
    """Resolve finalization dependencies at turn time for patch compatibility."""

    hooks = {
        "_degraded_answer_from_tool_results": _degraded_answer_from_tool_results,
        "_message_content_text": _message_content_text,
        "_fallback_answer_from_tool_results": _fallback_answer_from_tool_results,
        "_should_replace_unfound_workspace_answer": _should_replace_unfound_workspace_answer,
        "_latest_tool_result_content": _latest_tool_result_content,
        "normalize_evidence_bundle": normalize_evidence_bundle,
        "normalize_evidence_ledger": normalize_evidence_ledger,
        "skill_execution_evidence_facts": skill_execution_evidence_facts,
        "tool_result_names": tool_result_names,
        "evaluate_execution_contract": evaluate_execution_contract,
        "verify_answer_against_evidence": verify_answer_against_evidence,
        "_live_web_answer_repair_count": _live_web_answer_repair_count,
        "_skill_execution_answer_repair_count": _skill_execution_answer_repair_count,
        "_live_web_answer_needs_repair": _live_web_answer_needs_repair,
        "apply_prompt_budget_guard": apply_prompt_budget_guard,
        "_skill_execution_repair_prompt": _skill_execution_repair_prompt,
        "_ensure_reasoning_content_for_tool_call_history": (
            _ensure_reasoning_content_for_tool_call_history
        ),
        "_invoke_with_tool_result_fallback": _invoke_with_tool_result_fallback,
        "_with_stream_phase": _with_stream_phase,
        "_looks_like_textual_tool_call_artifact": _looks_like_textual_tool_call_artifact,
        "_repair_textual_tool_call_response": _repair_textual_tool_call_response,
        "_repair_and_dedupe_tool_calls": _repair_and_dedupe_tool_calls,
        "_skill_execution_failure_answer": _skill_execution_failure_answer,
        "_live_web_repair_response": _live_web_repair_response,
        "_live_web_failure_answer": _live_web_failure_answer,
        "evidence_bundle_to_citation_refs": evidence_bundle_to_citation_refs,
        "_new_citation_refs": _new_citation_refs,
        "_latest_turn_has_tool_result": _latest_turn_has_tool_result,
        "build_task_outcome": build_task_outcome,
        "_with_focus_agent_turn_metadata": _with_focus_agent_turn_metadata,
        "_next_pending_tool_action": _next_pending_tool_action,
        "append_agent_state_record": append_agent_state_record,
        "build_failure_records": build_failure_records,
        "build_review_queue": build_review_queue,
        "_latest_turn_messages": _latest_turn_messages,
        "STREAM_VISIBILITY_QUARANTINE": STREAM_VISIBILITY_QUARANTINE,
        "model_with_tools_for": model_with_tools_for,
    }
    return hooks


def make_agent_loop_node(
    *,
    settings: Settings,
    tools: Sequence[Any],
    tool_registry: ToolRegistry,
    skill_registry: SkillRegistry | None = None,
    model_for: Callable[[str, str], Any],
    model_with_tools_for: Callable[[str, str, list[Any] | None], Any],
    run_manager: Any | None = None,
    system_agent_runner: Any | None = None,
    agent_definition_registry: Any | None = None,
) -> Any:
    all_tools = list(tools)

    def agent_loop(
        state: AgentState,
        runtime: Runtime[RequestContext],
    ) -> dict[str, Any]:
        state_messages = list(state.get("messages", []) or [])
        messages = _messages_for_model(state)
        fallback_messages = _latest_turn_messages(state_messages or messages)
        selected_model = str(state.get("selected_model") or settings.model)
        selected_thinking_mode = str(state.get("selected_thinking_mode") or "")

        # Resolve AgentDefinition overrides (model / tools / system prompt).
        agent_def, agent_name = _resolve_agent_definition(agent_definition_registry, state)
        agent_system_prompt_extra = ""
        if agent_def is not None:
            try:
                if getattr(agent_def, "model", None):
                    selected_model = str(agent_def.model)
                agent_system_prompt_extra = str(
                    getattr(agent_def, "system_prompt", "") or ""
                ).strip()
            except Exception:  # noqa: BLE001
                _logger.debug("Failed to apply AgentDefinition '%s'", agent_name, exc_info=True)
                agent_system_prompt_extra = ""

        assembled = state.get("assembled_context", "")
        if agent_system_prompt_extra and agent_system_prompt_extra not in assembled:
            assembled = f"{agent_system_prompt_extra}\n\n{assembled}".strip()

        # Drain the steer queue for this thread and collect any mid-turn guidance.
        thread_id = None
        try:
            ctx = getattr(runtime, "context", None)
            thread_id = getattr(ctx, "root_thread_id", None)
        except Exception:  # noqa: BLE001
            thread_id = None
        steer_messages = _drain_steer_messages(run_manager, thread_id)
        steer_block = ""
        if steer_messages:
            joined = "\n\n".join(m.strip() for m in steer_messages if str(m).strip())
            if joined:
                steer_block = f"[User guidance]\n{joined}"
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
        skill_execution_plan = build_active_skill_execution_plan(
            skill_registry=skill_registry,
            active_skill_ids=list(state.get("active_skill_ids", []) or ()),
            text=tool_intent_text,
            workspace_root=Path(settings.workspace_root or ".").expanduser().resolve(),
            base_intent_plan=tool_intent_plan,
        )
        tool_intent_plan = apply_skill_execution_plan(tool_intent_plan, skill_execution_plan)
        tool_policy = tool_intent_plan.policy
        temporal_anchor_required = _tool_intent_plan_requires_temporal_anchor(tool_intent_plan)
        current_utc_time_result = _latest_tool_result_content(state_messages, "current_utc_time")
        if (
            tool_policy == "live_web_research"
            and tool_intent_plan.preferred_first_tool == "web_search"
            and current_utc_time_result
        ):
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
        forced_degraded_skill_recovery = False
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
        if tool_policy == "workspace_lookup" and _explicit_skill_tools_satisfied(
            tool_intent_text,
            state_messages,
            latest_turn_has_tool_result=_latest_turn_has_tool_result,
        ):
            available_tools = []
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
        # Apply AgentDefinition tool policy filter (allow/deny fnmatch) last.
        if agent_def is not None:
            available_tools = _filter_tools_by_agent_def(available_tools, agent_def)
        known_names = _known_tool_names(available_tools)
        execution_contract = build_execution_contract(
            policy=tool_policy,
            temporal_anchor_required=temporal_anchor_required,
            available_tool_names=known_names,
            preferred_first_tool=tool_intent_plan.preferred_first_tool,
            skill_execution_plan=tool_intent_plan.skill_execution_plan.model_dump(mode="json")
            if tool_intent_plan.skill_execution_plan is not None
            else None,
        )
        quarantined_model_for = _model_for_stream_phase(model_for, STREAM_VISIBILITY_QUARANTINE)
        quarantined_model_with_tools_for = _model_with_tools_for_stream_phase(
            model_with_tools_for,
            STREAM_VISIBILITY_QUARANTINE,
        )
        tool_protocol_repair_count = 0
        tool_protocol_repair_reason = ""
        policy_note = _tool_policy_note(tool_policy)
        skill_policy_note = skill_execution_policy_note(tool_intent_plan.skill_execution_plan)
        if skill_policy_note:
            policy_note = f"{policy_note}\n\n{skill_policy_note}".strip()
        # Efficiency guidance for multi-part questions: minimize tool calls by
        # reusing one tool result to answer multiple sub-questions.
        _multipart_note = (
            "For multi-part questions (e.g. asking about status, history, and "
            "branches at once), minimize tool calls:\n"
            "- If one tool result can answer multiple sub-questions, use it once.\n"
            "- Prefer the most specific tool (e.g. git_status covers both status and branches).\n"
            "- If you have already called a tool whose output can answer a sub-question, "
            "do not call another tool for that sub-question.\n"
            "- If the user asks a simple question that one tool call can answer, "
            "just call that tool directly -- do not follow the full multi-step workflow."
        )
        if _multipart_note not in (policy_note or ""):
            policy_note = (
                f"{policy_note}\n\n{_multipart_note}".strip() if policy_note else _multipart_note
            )
        plan = state.get("plan")
        if isinstance(plan, Plan) and plan.steps:
            plan_block = _format_plan_block(plan, state.get("current_step_id", ""))
            if plan_block and plan_block not in assembled:
                assembled = f"{assembled}\n\n{plan_block}".strip()
        prompt_messages = [SystemMessage(content=assembled), *messages]
        # Inject drained steer messages as an additional system-style block so
        # they are visible to the LLM but don't replace any user message.
        if steer_block:
            try:
                # Insert steer block right after the first system message so it
                # sits near the top of context and is easy to attend to.
                prompt_messages = [
                    prompt_messages[0],
                    SystemMessage(content=steer_block),
                    *prompt_messages[1:],
                ]
            except Exception:  # noqa: BLE001
                _logger.debug("Failed to inject steer block", exc_info=True)
        if policy_note:
            prompt_messages = [
                prompt_messages[0],
                SystemMessage(content=policy_note),
                *prompt_messages[1:],
            ]
        # Detect context overflow BEFORE budget guard trims — if the prompt is
        # already past ~85% of budget, fire the context_overflow system agent
        # so compact_context / summarize can kick in.
        try:
            fullness = _estimate_context_fullness(prompt_messages)
            if fullness >= 0.85:
                _fire_system_agent_trigger(
                    system_agent_runner,
                    "context_overflow",
                    {
                        "state": dict(state),
                        "context": getattr(runtime, "context", None),
                        "thread_id": thread_id,
                        "fullness": fullness,
                        "message_count": len(prompt_messages),
                    },
                )
        except Exception:  # noqa: BLE001
            _logger.debug("context_overflow trigger failed", exc_info=True)
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
            and tool_intent_plan.preferred_first_tool == "web_fetch"
            and _has_tool_named(available_tools, "web_fetch")
            and not _latest_turn_has_tool_result(state_messages, "web_fetch")
        ):
            response = AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": f"live-web-fetch-{state.get('llm_calls', 0) + 1}",
                        "name": "web_fetch",
                        "args": _web_fetch_args(
                            tool_intent_plan.preferred_first_args,
                            tool_intent_text,
                        ),
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
            tool_policy in {"workspace_lookup", "execution"}
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
            tool_policy == "execution"
            and "skill_install_intent" in tool_intent_plan.reason_codes
            and _has_tool_named(available_tools, "skill_install")
            and _latest_turn_has_tool_result(state_messages, "skills_search")
            and not _latest_turn_has_tool_result(state_messages, "skill_install")
            and (
                skill_install_args := _skill_install_args_from_search_result(
                    tool_intent_text,
                    state_messages,
                    latest_tool_result_content=_latest_tool_result_content,
                    skill_install_name_from_text=_skill_install_name_from_text,
                )
            )
        ):
            response = AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": f"skill-install-{state.get('llm_calls', 0) + 1}",
                        "name": "skill_install",
                        "args": skill_install_args,
                    }
                ],
            )
        elif (
            tool_policy == "execution"
            and tool_intent_plan.preferred_first_tool == "skill_install"
            and _has_tool_named(available_tools, "skill_install")
            and not _latest_turn_has_tool_result(state_messages, "skill_install")
            and tool_intent_plan.preferred_first_args.get("skill_id")
        ):
            response = AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": f"skill-install-{state.get('llm_calls', 0) + 1}",
                        "name": "skill_install",
                        "args": tool_intent_plan.preferred_first_args,
                    }
                ],
            )
        elif (
            tool_policy == "workspace_lookup"
            and tool_intent_plan.preferred_first_tool == "skill_view"
            and _has_tool_named(available_tools, "skill_view")
            and not _latest_turn_has_tool_result(state_messages, "skill_view")
            and tool_intent_plan.preferred_first_args.get("name")
        ):
            response = AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": f"skill-view-{state.get('llm_calls', 0) + 1}",
                        "name": "skill_view",
                        "args": tool_intent_plan.preferred_first_args,
                    }
                ],
            )
        elif (
            tool_policy == "workspace_lookup"
            and "skill_view" in tool_intent_text.lower()
            and _has_tool_named(available_tools, "skill_view")
            and _latest_turn_has_tool_result(state_messages, "skills_search")
            and not _latest_turn_has_tool_result(state_messages, "skill_view")
            and (skill_view_name := _skill_view_name_from_text(tool_intent_text))
        ):
            response = AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": f"skill-view-{state.get('llm_calls', 0) + 1}",
                        "name": "skill_view",
                        "args": {"name": skill_view_name},
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
        if (
            getattr(response, "tool_calls", None)
            and tool_policy == "execution"
            and tool_intent_plan.skill_execution_plan is not None
            and _should_force_degraded_skill_recovery_answer(
                state,
                primary_tool_names=tool_intent_plan.skill_execution_plan.primary_tools,
            )
        ):
            response = AIMessage(
                content=_degraded_answer_from_tool_results(_latest_turn_messages(state_messages))
            )
            forced_degraded_skill_recovery = True
        return finalize_agent_loop_turn(
            state=state,
            state_messages=state_messages,
            response=response,
            hooks=_agent_loop_update_hooks(model_with_tools_for),
            settings=settings,
            tool_intent_plan=tool_intent_plan,
            tool_route_plan=tool_route_plan,
            tool_policy=tool_policy,
            tool_intent_text=tool_intent_text,
            available_tools=available_tools,
            known_names=known_names,
            execution_contract=execution_contract,
            prompt_messages=prompt_messages,
            fallback_messages=fallback_messages,
            context_budget=context_budget,
            selected_model=selected_model,
            selected_thinking_mode=selected_thinking_mode,
            quarantined_model_for=quarantined_model_for,
            quarantined_model_with_tools_for=quarantined_model_with_tools_for,
            current_utc_time_result=current_utc_time_result,
            temporal_anchor_required=temporal_anchor_required,
            temporal_anchor_forced=temporal_anchor_forced,
            forced_degraded_skill_recovery=forced_degraded_skill_recovery,
            tool_protocol_repair_count=tool_protocol_repair_count,
            tool_protocol_repair_reason=tool_protocol_repair_reason,
        )

    return agent_loop


__all__ = ["make_agent_loop_node"]
