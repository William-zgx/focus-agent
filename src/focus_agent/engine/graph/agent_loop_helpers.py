from __future__ import annotations

import inspect
import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from langchain.messages import AIMessage, ToolMessage

from ...agent_roles import AgentRole
from ...capabilities import ToolRegistry
from ...capabilities.tool_registry import ToolRuntimeMeta
from ...capabilities.tool_router import SkillExecutionPlan, ToolIntentPlan
from ...core.state import AgentState
from ...skills import SkillRegistry
from ...skills.models import SkillDefinition
from ..graph_turn_helpers import (
    _live_web_research_should_start_with_search,
    _tools_for_policy,
    _workspace_lookup_should_start_with_search,
)
from .policy import (
    _is_tool_carryover_confirmation,
    _temporal_live_web_search_args,
    build_tool_intent_plan,
)

_SKILL_SUPPORTING_TOOL_DEFAULTS = {
    "web_search",
    "web_fetch",
    "read_file",
    "write_text_artifact",
}
_ACTIVE_EXECUTE_CONTINUATION_MARKERS = (
    "今天",
    "昨天",
    "本周",
    "这周",
    "近一周",
    "最近",
    "近期",
    "走势",
    "表现",
    "行情",
    "数据",
    "查询",
    "分析",
    "quote",
    "price",
    "history",
    "recent",
)
_LIVE_WEB_DOMAIN_MARKERS: Mapping[str, tuple[str, ...]] = {
    "weather": (
        "天气",
        "气温",
        "温度",
        "降雨",
        "下雨",
        "预报",
        "weather",
        "forecast",
        "temperature",
    ),
    "finance": (
        "股票",
        "股价",
        "行情",
        "走势",
        "涨跌",
        "大盘",
        "沪指",
        "上证",
        "深证",
        "创业板",
        "a股",
        "证券",
        "stock",
        "stocks",
        "share price",
        "ticker",
        "quote",
        "market",
        "finance",
    ),
    "news": (
        "新闻",
        "资讯",
        "事件",
        "公告",
        "news",
    ),
    "currency": (
        "汇率",
        "美元",
        "人民币",
        "日元",
        "欧元",
        "currency",
        "exchange rate",
        "fx",
    ),
    "sports": (
        "世界杯",
        "赛程",
        "比赛",
        "球队",
        "足球",
        "篮球",
        "sports",
        "schedule",
        "match",
    ),
    "aerospace": (
        "spacex",
        "发射",
        "火箭",
        "航天",
        "launch",
        "rocket",
    ),
    "entertainment": (
        "电影",
        "上映",
        "票房",
        "movie",
        "film",
        "release",
    ),
}
_FINANCE_ENTITY_HINTS = (
    "能源",
    "矿业",
    "股份",
    "科技",
    "银行",
    "证券",
    "汽车",
    "医药",
    "药业",
    "电力",
    "新能源",
    "公司",
    "集团",
    "工业",
    "控股",
)
_FINANCE_PERFORMANCE_MARKERS = (
    "走势",
    "表现",
    "行情",
    "涨跌",
    "涨幅",
    "跌幅",
    "成交",
    "市值",
    "财报",
)
_STOCK_CODE_RE = re.compile(r"(?<!\d)(?:[036]\d{5}|\d{6}\.(?:ss|sz|sh))(?!\d)", re.I)


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


def build_active_skill_execution_plan(
    *,
    skill_registry: SkillRegistry | None,
    active_skill_ids: list[Any],
    text: str,
    workspace_root: Path,
    base_intent_plan: ToolIntentPlan,
) -> SkillExecutionPlan | None:
    if skill_registry is None:
        return None
    if "explicit_no_tool" in set(base_intent_plan.reason_codes):
        return None
    if _is_explicit_skill_lookup_policy(base_intent_plan):
        return None

    matches: list[tuple[float, SkillDefinition, list[str]]] = []
    active_ids = [str(skill_id).strip() for skill_id in active_skill_ids if str(skill_id).strip()]
    for skill_id in active_ids:
        skill = skill_registry.resolve(skill_id)
        if skill is None or not skill_registry.is_skill_enabled(skill.skill_id):
            continue
        if str(skill.prompt_mode or "").strip().lower() != "execute":
            continue
        if str(skill.trust_level or "").strip().lower() not in {"", "trusted"}:
            continue
        score, reasons = _active_skill_match_score(
            skill,
            text,
            active_count=len(active_ids),
            base_intent_plan=base_intent_plan,
        )
        if score <= 0:
            continue
        matches.append((score, skill, reasons))
    if not matches:
        return None

    matches.sort(key=lambda item: (-item[0], item[1].skill_id))
    selected_skill_ids: list[str] = []
    primary_tools: list[str] = []
    supporting_tools: list[str] = []
    runtime_cwds: dict[str, str] = {}
    reason_codes = ["skill_execution_plan", "active_trusted_execute_skill"]
    _MAX_PRIMARY_TOOL_SKILLS = 2
    for idx, (_, skill, reasons) in enumerate(matches):
        selected_skill_ids.append(skill.skill_id)
        skill_primary = _skill_primary_tools(skill)
        skill_supporting = _skill_supporting_tools(skill, primary_tools=skill_primary)
        # Cap: only the top-N matched skills (by score) contribute primary
        # tools.  Additional matches still surface in selected_skill_ids and
        # their tools become supporting, so the model sees them but is not
        # forced to call every skill's primary tool before answering.
        if idx < _MAX_PRIMARY_TOOL_SKILLS:
            for tool_name in skill_primary:
                if tool_name not in primary_tools:
                    primary_tools.append(tool_name)
        else:
            for tool_name in skill_primary:
                if tool_name not in supporting_tools:
                    supporting_tools.append(tool_name)
            reason_codes.append(f"skill_primary_demoted:{skill.skill_id}")
        for tool_name in skill_supporting:
            if tool_name not in supporting_tools:
                supporting_tools.append(tool_name)
        cwd = _skill_runtime_cwd(skill, workspace_root=workspace_root)
        if cwd:
            runtime_cwds[skill.skill_id] = cwd
        reason_codes.extend(reasons)
        if skill_primary and not getattr(skill, "primary_tools", ()):
            reason_codes.append("skill_primary_tool_inferred")
    return SkillExecutionPlan(
        selected_skill_ids=selected_skill_ids,
        match_source="active",
        prompt_mode="execute",
        primary_tools=primary_tools,
        supporting_tools=supporting_tools,
        runtime_cwds=runtime_cwds,
        policy_override="execution",
        reason_codes=list(dict.fromkeys(reason_codes)),
    )


def apply_skill_execution_plan(
    intent_plan: ToolIntentPlan,
    skill_execution_plan: SkillExecutionPlan | None,
) -> ToolIntentPlan:
    if skill_execution_plan is None:
        return intent_plan
    if skill_execution_plan.policy_override != "execution":
        return intent_plan
    if "explicit_no_tool" in set(intent_plan.reason_codes):
        return intent_plan
    primary_tool = next(iter(skill_execution_plan.primary_tools), None)
    return intent_plan.model_copy(
        update={
            "policy": "execution",
            "confidence": max(float(intent_plan.confidence or 0.0), 0.92),
            "reason_codes": list(
                dict.fromkeys(
                    [
                        *intent_plan.reason_codes,
                        "active_skill_execution",
                        *skill_execution_plan.reason_codes,
                    ]
                )
            ),
            "preferred_first_tool": primary_tool,
            "preferred_first_args": {},
            "allowed_toolsets": list(
                dict.fromkeys([*intent_plan.allowed_toolsets, "workspace", "web", "skill"])
            ),
            "denied_toolsets": [],
            "source": "skill:active_execution",
            "temporal_anchor_required": False,
            "skill_execution_plan": skill_execution_plan,
        }
    )


def skill_execution_policy_note(skill_execution_plan: SkillExecutionPlan | None) -> str:
    if skill_execution_plan is None:
        return ""
    skills = ", ".join(skill_execution_plan.selected_skill_ids)
    primary = ", ".join(skill_execution_plan.primary_tools) or "none"
    supporting = ", ".join(skill_execution_plan.supporting_tools) or "none"
    cwd_lines = [
        f"- {skill_id}: {cwd}"
        for skill_id, cwd in sorted(skill_execution_plan.runtime_cwds.items())
    ]
    cwd_block = "\n".join(cwd_lines) if cwd_lines else "- none"
    return (
        "Active Skill execution plan:\n"
        f"- selected skills: {skills}\n"
        f"- required primary tools: {primary}\n"
        f"- supporting tools: {supporting}\n"
        "- before answering, call at least one selected Skill primary tool and use its "
        "structured tool result as evidence\n"
        "- Skill runtime cwd values for run_workspace_command:\n"
        f"{cwd_block}"
    )


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
        for raw_tool_name in (*skill.primary_tools, *skill.recommended_tools):
            tool_name = str(raw_tool_name).strip()
            if tool_name and tool_name not in seen:
                seen.add(tool_name)
                names.append(tool_name)
    return tuple(names)


def _is_explicit_skill_lookup_policy(intent_plan: ToolIntentPlan) -> bool:
    tool_name = str(intent_plan.preferred_first_tool or "").strip()
    if tool_name in {"skills_search", "skill_view", "skill_install"}:
        return True
    return set(intent_plan.allowed_toolsets) == {"skill"}


def _active_skill_match_score(
    skill: SkillDefinition,
    text: str,
    *,
    active_count: int,
    base_intent_plan: ToolIntentPlan,
) -> tuple[float, list[str]]:
    normalized = " ".join(str(text or "").strip().split())
    if not normalized:
        return 0.0, []
    lowered = normalized.lower()
    score = 0.0
    reasons: list[str] = []
    for raw_term in _skill_match_terms(skill):
        term = str(raw_term or "").strip()
        if len(term) < 2:
            continue
        if term.lower() in lowered:
            score += 1.0 if term in skill.aliases else 0.7
            reasons.append(f"skill_term_match:{skill.skill_id}:{term}")
    if score > 0:
        return score, reasons
    if (
        active_count == 1
        and _looks_like_active_execute_continuation(normalized)
        and _active_execute_continuation_allowed(skill, normalized, base_intent_plan)
    ):
        return 0.45, [f"active_execute_skill_continuation:{skill.skill_id}"]
    return 0.0, []


def _skill_match_terms(skill: SkillDefinition) -> tuple[str, ...]:
    terms: list[str] = []
    for values in (
        skill.aliases,
        skill.domains,
        skill.intents,
        skill.when_to_use,
        skill.localized_triggers,
        skill.triggers,
    ):
        for item in values:
            text = str(item or "").strip()
            if text:
                terms.append(text)
    return tuple(dict.fromkeys(terms))


def _looks_like_active_execute_continuation(text: str) -> bool:
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in _ACTIVE_EXECUTE_CONTINUATION_MARKERS)


def _active_execute_continuation_allowed(
    skill: SkillDefinition,
    text: str,
    base_intent_plan: ToolIntentPlan,
) -> bool:
    if base_intent_plan.policy != "live_web_research":
        return True
    domains = _explicit_live_web_domains(text)
    if not domains:
        return any(
            _query_matches_live_web_domain(text, domain)
            for domain in _skill_live_web_domains(skill)
        )
    return _skill_supports_live_web_domains(skill, domains)


def _explicit_live_web_domains(text: str) -> set[str]:
    lowered = text.lower()
    return {
        domain
        for domain, markers in _LIVE_WEB_DOMAIN_MARKERS.items()
        if any(marker.lower() in lowered for marker in markers)
    }


def _skill_supports_live_web_domains(
    skill: SkillDefinition,
    domains: set[str],
) -> bool:
    skill_domains = _skill_live_web_domains(skill)
    return bool(skill_domains.intersection(domains))


def _skill_live_web_domains(skill: SkillDefinition) -> set[str]:
    haystack = " ".join(
        str(value or "").strip()
        for value in (
            skill.skill_id,
            getattr(skill, "name", ""),
            skill.description,
            *_skill_match_terms(skill),
        )
        if str(value or "").strip()
    ).lower()
    if not haystack:
        return set()
    return {
        domain
        for domain, markers in _LIVE_WEB_DOMAIN_MARKERS.items()
        if any(marker.lower() in haystack for marker in markers)
    }


def _query_matches_live_web_domain(text: str, domain: str) -> bool:
    lowered = text.lower()
    markers = _LIVE_WEB_DOMAIN_MARKERS.get(domain, ())
    if any(marker.lower() in lowered for marker in markers):
        return True
    if domain != "finance":
        return False
    if _STOCK_CODE_RE.search(text):
        return True
    has_finance_entity = any(hint in text for hint in _FINANCE_ENTITY_HINTS)
    has_performance_marker = any(marker in text for marker in _FINANCE_PERFORMANCE_MARKERS)
    return has_finance_entity or has_performance_marker


def _skill_primary_tools(skill: SkillDefinition) -> list[str]:
    explicit = [
        tool_name
        for tool_name in _normalized_skill_tool_names(getattr(skill, "primary_tools", ()))
        if tool_name
    ]
    if getattr(skill, "entrypoints", ()):
        return [
            "run_skill_entrypoint",
            *[tool_name for tool_name in explicit if tool_name != "run_skill_entrypoint"],
        ]
    if explicit:
        return explicit
    recommended = _normalized_skill_tool_names(skill.recommended_tools)
    primary = [
        tool_name
        for tool_name in recommended
        if tool_name not in _SKILL_SUPPORTING_TOOL_DEFAULTS
    ]
    if primary:
        return primary
    return recommended[:1]


def _skill_supporting_tools(
    skill: SkillDefinition,
    *,
    primary_tools: list[str],
) -> list[str]:
    primary = set(primary_tools)
    return [
        tool_name
        for tool_name in _normalized_skill_tool_names(skill.recommended_tools)
        if tool_name and tool_name not in primary
    ]


def _normalized_skill_tool_names(raw_values: Sequence[Any]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for raw_value in raw_values:
        name = str(raw_value or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def _skill_runtime_cwd(skill: SkillDefinition, *, workspace_root: Path) -> str:
    try:
        root = workspace_root.expanduser().resolve()
        skill_dir = skill.path.parent.expanduser().resolve()
        relative = skill_dir.relative_to(root)
    except ValueError:
        return ""
    except OSError:
        return ""
    return relative.as_posix() or "."


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
        str(item)
        for item in verification.get("unsupported_claims", []) or []
        if str(item).strip()
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
