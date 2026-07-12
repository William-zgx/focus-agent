from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from threading import RLock
from typing import Any

from langchain.messages import AIMessage, ToolMessage

from ...agent_roles import AgentRole
from ...capabilities import ToolRegistry
from ...capabilities.tool_router import SkillExecutionPlan, ToolIntentPlan
from ...core.state import AgentState
from ...skills import SkillRegistry
from ..graph_turn_helpers import (
    _live_web_research_should_start_with_search,
    _tools_for_policy,
    _workspace_lookup_should_start_with_search,
)
from . import agent_loop_helpers_skill_planning as _skill_planning
from .policy import (
    _is_tool_carryover_confirmation,
    _temporal_live_web_search_args,
    build_tool_intent_plan,
)

_SKILL_SUPPORTING_TOOL_DEFAULTS = _skill_planning._SKILL_SUPPORTING_TOOL_DEFAULTS
_ACTIVE_EXECUTE_CONTINUATION_MARKERS = _skill_planning._ACTIVE_EXECUTE_CONTINUATION_MARKERS
_LIVE_WEB_DOMAIN_MARKERS = _skill_planning._LIVE_WEB_DOMAIN_MARKERS
_FINANCE_ENTITY_HINTS = _skill_planning._FINANCE_ENTITY_HINTS
_FINANCE_PERFORMANCE_MARKERS = _skill_planning._FINANCE_PERFORMANCE_MARKERS
_STOCK_CODE_RE = _skill_planning._STOCK_CODE_RE
_active_skill_recommended_tool_names = _skill_planning._active_skill_recommended_tool_names
_is_explicit_skill_lookup_policy = _skill_planning._is_explicit_skill_lookup_policy
_active_skill_match_score = _skill_planning._active_skill_match_score
_skill_match_terms = _skill_planning._skill_match_terms
_looks_like_active_execute_continuation = _skill_planning._looks_like_active_execute_continuation
_active_execute_continuation_allowed = _skill_planning._active_execute_continuation_allowed
_explicit_live_web_domains = _skill_planning._explicit_live_web_domains
_skill_supports_live_web_domains = _skill_planning._skill_supports_live_web_domains
_skill_live_web_domains = _skill_planning._skill_live_web_domains
_query_matches_live_web_domain = _skill_planning._query_matches_live_web_domain
_skill_primary_tools = _skill_planning._skill_primary_tools
_skill_supporting_tools = _skill_planning._skill_supporting_tools
_normalized_skill_tool_names = _skill_planning._normalized_skill_tool_names
_skill_runtime_cwd = _skill_planning._skill_runtime_cwd
_recommended_tool_allowed_for_policy = _skill_planning._recommended_tool_allowed_for_policy

_SKILL_PLANNING_SEAM_NAMES = (
    "_SKILL_SUPPORTING_TOOL_DEFAULTS",
    "_ACTIVE_EXECUTE_CONTINUATION_MARKERS",
    "_LIVE_WEB_DOMAIN_MARKERS",
    "_FINANCE_ENTITY_HINTS",
    "_FINANCE_PERFORMANCE_MARKERS",
    "_STOCK_CODE_RE",
    "_active_skill_recommended_tool_names",
    "_is_explicit_skill_lookup_policy",
    "_active_skill_match_score",
    "_skill_match_terms",
    "_looks_like_active_execute_continuation",
    "_active_execute_continuation_allowed",
    "_explicit_live_web_domains",
    "_skill_supports_live_web_domains",
    "_skill_live_web_domains",
    "_query_matches_live_web_domain",
    "_skill_primary_tools",
    "_skill_supporting_tools",
    "_normalized_skill_tool_names",
    "_skill_runtime_cwd",
    "_recommended_tool_allowed_for_policy",
)
_SKILL_PLANNING_DEFAULTS = {name: globals()[name] for name in _SKILL_PLANNING_SEAM_NAMES}
_SKILL_PLANNING_IMPLEMENTATIONS = {
    "_merge_active_skill_recommended_tools": _skill_planning._merge_active_skill_recommended_tools,
    "build_active_skill_execution_plan": _skill_planning.build_active_skill_execution_plan,
    "apply_skill_execution_plan": _skill_planning.apply_skill_execution_plan,
    "skill_execution_policy_note": _skill_planning.skill_execution_policy_note,
}
_SKILL_PLANNING_PATCH_LOCK = RLock()


def _call_skill_planning_implementation(
    name: str,
    /,
    *args: Any,
    **kwargs: Any,
) -> Any:
    implementation = _SKILL_PLANNING_IMPLEMENTATIONS[name]
    if all(globals()[symbol] is value for symbol, value in _SKILL_PLANNING_DEFAULTS.items()):
        return implementation(*args, **kwargs)
    with _SKILL_PLANNING_PATCH_LOCK:
        implementation_module = getattr(
            _skill_planning,
            "_implementation_module",
            _skill_planning,
        )
        previous = {
            symbol: getattr(_skill_planning, symbol) for symbol in _SKILL_PLANNING_SEAM_NAMES
        }
        try:
            for symbol in _SKILL_PLANNING_SEAM_NAMES:
                setattr(implementation_module, symbol, globals()[symbol])
            return implementation(*args, **kwargs)
        finally:
            for symbol, value in previous.items():
                setattr(implementation_module, symbol, value)


def _merge_active_skill_recommended_tools(
    available_tools: list[Any],
    all_tools: list[Any],
    *,
    skill_registry: SkillRegistry | None,
    active_skill_ids: list[Any],
    tool_policy: str,
) -> list[Any]:
    return _call_skill_planning_implementation(
        "_merge_active_skill_recommended_tools",
        available_tools,
        all_tools,
        skill_registry=skill_registry,
        active_skill_ids=active_skill_ids,
        tool_policy=tool_policy,
    )


def build_active_skill_execution_plan(
    *,
    skill_registry: SkillRegistry | None,
    active_skill_ids: list[Any],
    text: str,
    workspace_root: Path,
    base_intent_plan: ToolIntentPlan,
) -> SkillExecutionPlan | None:
    return _call_skill_planning_implementation(
        "build_active_skill_execution_plan",
        skill_registry=skill_registry,
        active_skill_ids=active_skill_ids,
        text=text,
        workspace_root=workspace_root,
        base_intent_plan=base_intent_plan,
    )


def apply_skill_execution_plan(
    intent_plan: ToolIntentPlan,
    skill_execution_plan: SkillExecutionPlan | None,
) -> ToolIntentPlan:
    return _call_skill_planning_implementation(
        "apply_skill_execution_plan",
        intent_plan,
        skill_execution_plan,
    )


def skill_execution_policy_note(skill_execution_plan: SkillExecutionPlan | None) -> str:
    return _call_skill_planning_implementation(
        "skill_execution_policy_note",
        skill_execution_plan,
    )


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


def _skill_execution_answer_repair_count(state: AgentState) -> int:
    plan_meta = state.get("plan_meta")
    if isinstance(plan_meta, Mapping):
        return _coerce_int(plan_meta.get("skill_execution_answer_repair_count"), default=0)
    return 0


def _live_web_answer_needs_repair(verification: Mapping[str, Any]) -> bool:
    status = str(verification.get("status") or "")
    repair_action = str(verification.get("repair_action") or "")
    return status in {"unsupported", "blocked"} or repair_action in {
        "call_missing_tool",
        "refresh_stale_evidence",
    }


def _skill_execution_repair_prompt(
    *,
    verification: Mapping[str, Any],
    execution_contract: Mapping[str, Any],
) -> str:
    required_tools = [
        str(item)
        for item in execution_contract.get("required_tools", []) or []
        if str(item).strip()
    ]
    selected_skills = [
        str(item)
        for item in execution_contract.get("selected_skill_ids", []) or []
        if str(item).strip()
    ]
    missing = [
        str(item) for item in execution_contract.get("missing", []) or [] if str(item).strip()
    ]
    return (
        "Skill execution contract repair:\n"
        f"- selected skills: {', '.join(selected_skills) or 'none'}\n"
        f"- required primary tools: {', '.join(required_tools) or 'none'}\n"
        f"- missing tool results: {', '.join(missing) or 'none'}\n"
        f"- verification status: {verification.get('status') or 'unknown'}\n"
        "Do not provide a final answer yet. Call one of the required primary tools now. "
        "Use the active Skill runtime cwd shown in the previous policy note when a workspace "
        "command is needed."
    )


def _skill_execution_failure_answer(
    *,
    verification: Mapping[str, Any],
    execution_contract: Mapping[str, Any],
) -> str:
    selected_skills = [
        str(item)
        for item in execution_contract.get("selected_skill_ids", []) or []
        if str(item).strip()
    ]
    missing = [
        str(item) for item in execution_contract.get("missing", []) or [] if str(item).strip()
    ]
    blocked_reason = str(execution_contract.get("blocked_reason") or "").strip()
    unsupported = [
        str(item) for item in verification.get("unsupported_claims", []) or [] if str(item).strip()
    ]
    reason = blocked_reason or (f"缺少必要工具结果：{', '.join(missing)}" if missing else "")
    if not reason and unsupported:
        reason = unsupported[0]
    if not reason:
        reason = "已激活 Skill 的执行证据不足"
    skill_part = f"（{', '.join(selected_skills)}）" if selected_skills else ""
    return "\n".join(
        [
            f"我还不能可靠回答这个 Skill 任务{skill_part}。",
            f"原因：{reason}。",
            "本轮没有拿到必需 primary tool 的结构化结果，所以我不会用搜索片段或猜测数据代替 Skill 执行结果。",
        ]
    )


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
        str(item) for item in verification.get("unsupported_claims", []) or [] if str(item).strip()
    ]
    missing = [
        str(item) for item in execution_contract.get("missing", []) or [] if str(item).strip()
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
