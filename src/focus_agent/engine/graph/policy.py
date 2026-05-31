from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from langchain.messages import ToolMessage

from ...agent_roles import AgentRole
from ...capabilities.tool_registry import ToolRuntimeMeta
from ...capabilities.tool_router import CapabilityPolicyEngine, ToolIntentPlan
from .policy_intent import (
    is_tool_carryover_confirmation as _is_tool_carryover_confirmation,
)
from .policy_intent import (
    pending_live_web_search_intent as _pending_live_web_search_intent,
)
from .policy_intent import (
    requires_temporal_anchor as _requires_temporal_anchor,
)
from .policy_markers import (
    _ALL_FILTERABLE_TOOLSETS,
    _BARE_CURRENT_MARKERS,
    _CODE_OR_FILE_REFERENCE_RE,
    _CODE_SEARCH_TOOL_INTENT_MARKERS,
    _CREATIVE_DIRECT_MARKERS,
    _EXECUTION_INTENT_MARKERS,
    _EXPLICIT_WORKSPACE_CONTEXT_MARKERS,
    _FILE_BROWSE_INTENT_MARKERS,
    _FRESH_EXTERNAL_INTENT_MARKERS,
    _LIVE_WEB_INTENT_MARKERS,
    _LIVE_WEB_SEARCH_FIRST_MARKERS,
    _LOCAL_WORKSPACE_QUALIFIERS,
    _NO_TOOL_INTENT_MARKERS,
    _SYMBOL_LOOKUP_INTENT_MARKERS,
    _WEAK_WORKSPACE_CONTEXT_MARKERS,
    _WEB_LOOKUP_ACTION_MARKERS,
    _WORKSPACE_INTENT_MARKERS,
    _academic_web_lookup_hits,
    _contains_any,
    _contextual_current_hits,
    _matched_markers,
    _skill_discovery_hits,
    _skill_discovery_preferred_tool,
    _skill_discovery_should_prefer_search,
)
from .policy_temporal import (
    _anchor_relative_time_query as _anchor_relative_time_query,
)
from .policy_temporal import (
    _clean_location_scope as _clean_location_scope,
)
from .policy_temporal import (
    _extract_location_or_scope as _extract_location_or_scope,
)
from .policy_temporal import (
    _parse_current_utc_time as _parse_current_utc_time,
)
from .policy_temporal import (
    _relative_date_parts as _relative_date_parts,
)
from .policy_temporal import (
    _temporal_live_web_search_args,
)

_DIRECT_ANSWER_NOTE = (
    "This turn should be answered directly. Do not call tools, browse the web, inspect files, "
    "or create artifacts unless the user explicitly changes that request."
)


_WORKSPACE_TOOL_NOTE = (
    "This turn may use only local workspace inspection tools. Do not use web tools or artifact-writing tools. "
    "For symbol, function, tool, definition, usage, or location lookups, prefer search_code first with the "
    "most specific query. When search_code only identifies a file or line and the user asks for exact nearby "
    "configuration, values, or membership, call read_file on that file before answering. Do not claim that a "
    "local value cannot be confirmed while read_file is available and the relevant file is known. Use list_files "
    "first only when the user asks to browse or enumerate files."
)


_LIVE_WEB_TOOL_NOTE = "This turn may use live web/time tools when needed. Do not inspect local project files unless the user asks."


_BRANCH_ACTION_GUARD_NOTE = (
    "Branch management is executed only through structured Branch Action confirmations. "
    "If the user asks to switch, fork, open, archive, or merge branches, do not claim the branch was created, "
    "opened, archived, merged, or switched unless the runtime has already returned a successful Branch Action "
    "or branch API result. Ask for confirmation or describe the pending action instead."
)

_HTTP_URL_RE = re.compile(r"https?://[^\s<>()\"'，。！？、]+", re.IGNORECASE)
_SKILL_ID_RE = r"[A-Za-z0-9][A-Za-z0-9_.:/-]*"
_SKILL_TOOL_NAMES = frozenset(
    {
        "skills_search",
        "skill_view",
        "skills_list",
        "skill_install",
        "skills_refresh_index",
        "skill_sources",
    }
)


_ToolPolicy = Literal["direct_answer", "workspace_lookup", "live_web_research", "execution"]


@dataclass(frozen=True, slots=True)
class TurnToolExposure:
    policy: _ToolPolicy
    confidence: float
    reason_codes: tuple[str, ...]
    preferred_first_tool: str | None
    allowed_toolsets: tuple[str, ...]
    hard_denied_toolsets: tuple[str, ...]


def _classify_turn_tool_policy(text: str) -> _ToolPolicy:
    return _classify_turn_tool_exposure(text).policy


def build_tool_intent_plan(
    text: str,
    *,
    active_skill_ids: tuple[str, ...] | list[str] = (),
    pending_tool_action: Mapping[str, Any] | None = None,
) -> ToolIntentPlan:
    normalized = " ".join(text.strip().split())
    pending_web_search = _pending_live_web_search_intent(pending_tool_action)
    if _is_tool_carryover_confirmation(normalized) and pending_web_search is not None:
        query = str(pending_web_search.get("query") or "").strip() or normalized
        reason_codes = [
            "pending_tool_action_carryover",
            "live_web_signal",
            "policy_live_web_research",
        ]
        if _requires_temporal_anchor(query):
            reason_codes.append("temporal_anchor_required")
        return ToolIntentPlan(
            normalized_text=normalized,
            policy="live_web_research",
            confidence=0.9,
            reason_codes=reason_codes,
            preferred_first_tool="web_search",
            preferred_first_args={"query": query},
            allowed_toolsets=["web"],
            denied_toolsets=[toolset for toolset in _ALL_FILTERABLE_TOOLSETS if toolset != "web"],
            source="pending_tool_action",
            temporal_anchor_required="temporal_anchor_required" in reason_codes,
        )

    exposure = _classify_turn_tool_exposure(normalized)
    source = "deterministic"

    no_tool = "explicit_no_tool" in exposure.reason_codes
    explicit_skill_tool_request = set(exposure.allowed_toolsets) == {"skill"} or (
        exposure.preferred_first_tool in _SKILL_TOOL_NAMES
    )
    skill_ids = {
        str(skill_id).strip().lower() for skill_id in active_skill_ids if str(skill_id).strip()
    }
    if not no_tool and not explicit_skill_tool_request and "plan" in skill_ids:
        exposure = _exposure(
            "direct_answer",
            confidence=0.95,
            reason_codes=(*exposure.reason_codes, "skill_plan_direct_answer"),
        )
        source = "skill:plan"
    elif (
        not no_tool
        and not explicit_skill_tool_request
        and ("review" in skill_ids or "security-review" in skill_ids)
    ):
        exposure = _exposure(
            "workspace_lookup",
            confidence=max(exposure.confidence, 0.9),
            reason_codes=(*exposure.reason_codes, "skill_review_workspace"),
            preferred_first_tool=exposure.preferred_first_tool,
        )
        source = "skill:review"
    elif (
        not no_tool
        and not explicit_skill_tool_request
        and ("research" in skill_ids or "web-research" in skill_ids)
    ):
        exposure = _exposure(
            "live_web_research",
            confidence=max(exposure.confidence, 0.9),
            reason_codes=(*exposure.reason_codes, "skill_research_web"),
            preferred_first_tool=exposure.preferred_first_tool or "web_search",
        )
        source = "skill:research"
    elif (
        not no_tool
        and not explicit_skill_tool_request
        and skill_ids
        and not skill_ids <= {"eco"}
        and exposure.policy == "direct_answer"
    ):
        exposure = _exposure(
            "workspace_lookup",
            confidence=max(exposure.confidence, 0.85),
            reason_codes=(*exposure.reason_codes, "active_skill_workspace"),
            preferred_first_tool=exposure.preferred_first_tool,
            allowed_toolsets=("workspace",),
        )
        source = "skill:active"

    reason_codes = list(exposure.reason_codes)
    if exposure.policy == "live_web_research" and _requires_temporal_anchor(normalized):
        reason_codes.append("temporal_anchor_required")

    preferred_first_args = _preferred_first_args(exposure.preferred_first_tool, normalized)
    return ToolIntentPlan(
        normalized_text=normalized,
        policy=exposure.policy,
        confidence=exposure.confidence,
        reason_codes=list(dict.fromkeys(reason_codes)),
        preferred_first_tool=exposure.preferred_first_tool,
        preferred_first_args=preferred_first_args,
        allowed_toolsets=list(exposure.allowed_toolsets),
        denied_toolsets=list(exposure.hard_denied_toolsets),
        source=source,
        temporal_anchor_required="temporal_anchor_required" in reason_codes,
    )


def _turn_tool_exposure_from_intent_plan(intent_plan: ToolIntentPlan) -> TurnToolExposure:
    policy = str(intent_plan.policy or "direct_answer")
    if policy not in {"direct_answer", "workspace_lookup", "live_web_research", "execution"}:
        policy = "direct_answer"
    return TurnToolExposure(
        policy=policy,  # type: ignore[arg-type]
        confidence=float(intent_plan.confidence or 0.55),
        reason_codes=tuple(str(item) for item in intent_plan.reason_codes if str(item)),
        preferred_first_tool=intent_plan.preferred_first_tool,
        allowed_toolsets=tuple(str(item) for item in intent_plan.allowed_toolsets if str(item)),
        hard_denied_toolsets=tuple(str(item) for item in intent_plan.denied_toolsets if str(item)),
    )


def _preferred_first_args(tool_name: str | None, text: str) -> dict[str, Any]:
    if tool_name == "web_search":
        return {"query": text}
    if tool_name == "web_fetch":
        url = _first_http_url(text)
        return {"url": url} if url else {}
    if tool_name == "search_code":
        return {"query": _workspace_search_query(text)}
    if tool_name == "skills_search":
        return {"query": text}
    if tool_name == "skill_view":
        skill_name = _skill_view_name_from_text(text)
        return {"name": skill_name} if skill_name else {}
    return {}


def _skill_view_name_from_text(text: str) -> str:
    normalized = " ".join(str(text or "").strip().split())
    if not normalized:
        return ""
    patterns = (
        rf"(?i)(?<![a-z0-9_])skill_view(?![a-z0-9_])\s*"
        rf"(?:查看|打开|读取|加载|view|inspect|open|read|name|名称|for|of|:|：)?\s*"
        rf"`?(?P<name>{_SKILL_ID_RE})`?",
        rf"(?:查看|打开|读取|加载)\s+`?(?P<name>{_SKILL_ID_RE})`?\s*(?:这个)?(?:skill|技能)",
    )
    ignored = {
        "查看",
        "打开",
        "读取",
        "加载",
        "view",
        "inspect",
        "open",
        "read",
        "name",
        "for",
        "of",
    }
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if not match:
            continue
        name = str(match.group("name") or "").strip("`.,!?;:，。！？；：")
        if name and name.lower() not in ignored:
            return name
    return ""


def _tool_intent_plan_requires_temporal_anchor(intent_plan: ToolIntentPlan) -> bool:
    if str(intent_plan.policy or "") != "live_web_research":
        return False
    reason_codes = {str(item) for item in intent_plan.reason_codes if str(item)}
    if "temporal_anchor_required" in reason_codes:
        return True
    query = ""
    preferred_args = intent_plan.preferred_first_args
    if isinstance(preferred_args, Mapping):
        query = str(preferred_args.get("query") or "").strip()
    return _requires_temporal_anchor(query or str(intent_plan.normalized_text or ""))


def _classify_turn_tool_exposure(text: str) -> TurnToolExposure:
    normalized = " ".join(text.strip().split())
    if not normalized:
        return _exposure(
            "direct_answer",
            confidence=1.0,
            reason_codes=("empty_turn",),
        )

    no_tool_hits = _matched_markers(normalized, _NO_TOOL_INTENT_MARKERS)
    if no_tool_hits:
        return _exposure(
            "direct_answer",
            confidence=1.0,
            reason_codes=("explicit_no_tool",),
        )

    local_context_hits = _matched_markers(normalized, _LOCAL_WORKSPACE_QUALIFIERS)
    explicit_workspace_hits = _matched_markers(normalized, _EXPLICIT_WORKSPACE_CONTEXT_MARKERS)
    workspace_hits = _matched_markers(normalized, _WORKSPACE_INTENT_MARKERS)
    symbol_hits = _matched_markers(normalized, _SYMBOL_LOOKUP_INTENT_MARKERS)
    file_browse_hits = _matched_markers(normalized, _FILE_BROWSE_INTENT_MARKERS)
    live_hits = _matched_markers(normalized, _LIVE_WEB_INTENT_MARKERS)
    fresh_external_hits = _matched_markers(normalized, _FRESH_EXTERNAL_INTENT_MARKERS)
    web_lookup_hits = _matched_markers(normalized, _WEB_LOOKUP_ACTION_MARKERS)
    if not web_lookup_hits:
        live_hits, fresh_external_hits = _filter_bare_current_hits(live_hits, fresh_external_hits)
    contextual_current_hits = set(_contextual_current_hits(normalized))
    if contextual_current_hits:
        live_hits = tuple(hit for hit in live_hits if hit not in contextual_current_hits)
        fresh_external_hits = tuple(
            hit for hit in fresh_external_hits if hit not in contextual_current_hits
        )
    academic_lookup_hits = _academic_web_lookup_hits(normalized)
    code_reference_hit = bool(_CODE_OR_FILE_REFERENCE_RE.search(normalized))
    if academic_lookup_hits:
        live_hits = tuple(dict.fromkeys((*live_hits, *academic_lookup_hits)))
        web_lookup_hits = tuple(dict.fromkeys((*web_lookup_hits, *academic_lookup_hits)))
    skill_discovery_hits = _skill_discovery_hits(normalized)
    if _contains_any(normalized, ("引用来源", "引用数据来源", "cite source", "cite sources")):
        symbol_hits = tuple(hit for hit in symbol_hits if hit not in {"引用", "reference"})
    execution_hits = _matched_markers(normalized, _EXECUTION_INTENT_MARKERS)
    creative_hits = _matched_markers(normalized, _CREATIVE_DIRECT_MARKERS)
    strong_explicit_workspace_hits = tuple(
        hit for hit in explicit_workspace_hits if hit not in _WEAK_WORKSPACE_CONTEXT_MARKERS
    )
    strong_workspace_hits = tuple(
        dict.fromkeys(
            [
                *local_context_hits,
                *strong_explicit_workspace_hits,
                *symbol_hits,
                *file_browse_hits,
                *(("code_reference",) if code_reference_hit else ()),
            ]
        )
    )

    workspace_score = (
        len(local_context_hits) * 4
        + (4 if code_reference_hit else 0)
        + len(symbol_hits) * 3
        + len(file_browse_hits) * 3
        + len(explicit_workspace_hits) * 2
        + len(workspace_hits)
    )
    live_web_score = len(web_lookup_hits) * 3 + len(fresh_external_hits) * 2 + len(live_hits)
    execution_score = len(execution_hits) * 3
    direct_score = len(creative_hits) * 2

    if local_context_hits:
        current_only_hits = {"当前", "current"} & set(fresh_external_hits)
        live_web_score = max(0, live_web_score - len(current_only_hits) * 3)

    has_workspace_signal = workspace_score > 0
    has_strong_workspace_signal = bool(strong_workspace_hits)
    has_live_web_signal = live_web_score > 0

    reason_codes: list[str] = []
    if creative_hits:
        reason_codes.append("creative_direct_signal")
    if strong_workspace_hits:
        reason_codes.append("local_workspace_context")
    if has_strong_workspace_signal or (workspace_hits and not has_live_web_signal):
        reason_codes.append("workspace_lookup_signal")
    if fresh_external_hits and has_live_web_signal:
        reason_codes.append("fresh_external_signal")
    if (web_lookup_hits or live_hits) and has_live_web_signal:
        reason_codes.append("live_web_signal")
    if execution_hits:
        reason_codes.append("execution_signal")
    if skill_discovery_hits:
        reason_codes.append("skill_discovery_signal")

    preferred_skill_tool = _skill_discovery_preferred_tool(normalized)
    if skill_discovery_hits and (
        not execution_score
        or preferred_skill_tool
        or _skill_discovery_should_prefer_search(normalized)
    ):
        reason_codes.append("policy_workspace_lookup")
        return _exposure(
            "workspace_lookup",
            confidence=max(
                0.78,
                _confidence(len(skill_discovery_hits) * 3, max(workspace_score, live_web_score)),
            ),
            reason_codes=tuple(reason_codes),
            preferred_first_tool=preferred_skill_tool or "skills_search",
            allowed_toolsets=("skill",),
        )

    if execution_score and has_strong_workspace_signal and not has_live_web_signal:
        reason_codes.append("policy_execution")
        return _exposure(
            "execution",
            confidence=_confidence(execution_score + workspace_score, direct_score),
            reason_codes=tuple(reason_codes),
            preferred_first_tool=_preferred_first_tool(
                normalized,
                policy="execution",
                symbol_hits=symbol_hits,
                file_browse_hits=file_browse_hits,
                web_lookup_hits=web_lookup_hits,
                fresh_external_hits=fresh_external_hits,
            ),
        )

    if has_strong_workspace_signal and has_live_web_signal:
        reason_codes.append("mixed_live_web_workspace")
        return _exposure(
            "execution",
            confidence=_confidence(
                max(workspace_score, live_web_score), min(workspace_score, live_web_score)
            ),
            reason_codes=tuple(reason_codes),
            preferred_first_tool=_preferred_first_tool(
                normalized,
                policy="execution",
                symbol_hits=symbol_hits,
                file_browse_hits=file_browse_hits,
                web_lookup_hits=web_lookup_hits,
                fresh_external_hits=fresh_external_hits,
            ),
            allowed_toolsets=("web", "workspace"),
            hard_denied_toolsets=("artifact", "memory", "skill"),
        )

    if execution_score and execution_score >= max(workspace_score, live_web_score, direct_score):
        reason_codes.append("policy_execution")
        return _exposure(
            "execution",
            confidence=_confidence(
                execution_score, max(workspace_score, live_web_score, direct_score)
            ),
            reason_codes=tuple(reason_codes),
        )

    if has_live_web_signal and live_web_score >= max(workspace_score, direct_score):
        reason_codes.append("policy_live_web_research")
        return _exposure(
            "live_web_research",
            confidence=_confidence(live_web_score, max(workspace_score, direct_score)),
            reason_codes=tuple(reason_codes),
            preferred_first_tool=_preferred_first_tool(
                normalized,
                policy="live_web_research",
                symbol_hits=symbol_hits,
                file_browse_hits=file_browse_hits,
                web_lookup_hits=web_lookup_hits,
                fresh_external_hits=fresh_external_hits,
            ),
        )

    if has_workspace_signal:
        reason_codes.append("policy_workspace_lookup")
        return _exposure(
            "workspace_lookup",
            confidence=_confidence(workspace_score, max(live_web_score, direct_score)),
            reason_codes=tuple(reason_codes),
            preferred_first_tool=_preferred_first_tool(
                normalized,
                policy="workspace_lookup",
                symbol_hits=symbol_hits,
                file_browse_hits=file_browse_hits,
                web_lookup_hits=web_lookup_hits,
                fresh_external_hits=fresh_external_hits,
            ),
        )

    if direct_score:
        reason_codes.append("policy_direct_answer")
        return _exposure(
            "direct_answer",
            confidence=_confidence(
                direct_score, max(workspace_score, live_web_score, execution_score)
            ),
            reason_codes=tuple(reason_codes),
        )

    return _exposure(
        "direct_answer",
        confidence=0.55,
        reason_codes=("default_direct_answer",),
    )


def _filter_bare_current_hits(
    live_hits: tuple[str, ...],
    fresh_external_hits: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    live_non_current = tuple(hit for hit in live_hits if hit not in _BARE_CURRENT_MARKERS)
    fresh_non_current = tuple(
        hit for hit in fresh_external_hits if hit not in _BARE_CURRENT_MARKERS
    )
    if live_non_current or fresh_non_current:
        return live_hits, fresh_external_hits
    return live_non_current, fresh_non_current


def _exposure(
    policy: _ToolPolicy,
    *,
    confidence: float,
    reason_codes: tuple[str, ...],
    preferred_first_tool: str | None = None,
    allowed_toolsets: tuple[str, ...] | None = None,
    hard_denied_toolsets: tuple[str, ...] | None = None,
) -> TurnToolExposure:
    if allowed_toolsets is None:
        allowed_toolsets = _allowed_toolsets_for_policy(policy)
    if hard_denied_toolsets is None and policy == "direct_answer":
        hard_denied_toolsets = _ALL_FILTERABLE_TOOLSETS
    elif hard_denied_toolsets is None and allowed_toolsets:
        hard_denied_toolsets = tuple(
            toolset for toolset in _ALL_FILTERABLE_TOOLSETS if toolset not in allowed_toolsets
        )
    elif hard_denied_toolsets is None:
        hard_denied_toolsets = ()
    return TurnToolExposure(
        policy=policy,
        confidence=round(max(0.0, min(confidence, 1.0)), 2),
        reason_codes=tuple(dict.fromkeys(reason_codes)),
        preferred_first_tool=preferred_first_tool,
        allowed_toolsets=allowed_toolsets,
        hard_denied_toolsets=hard_denied_toolsets,
    )


def _allowed_toolsets_for_policy(policy: _ToolPolicy) -> tuple[str, ...]:
    if policy == "workspace_lookup":
        return ("workspace",)
    if policy == "live_web_research":
        return ("web",)
    return ()


def _confidence(top_score: int, runner_up_score: int) -> float:
    if top_score <= 0:
        return 0.55
    return 0.6 + min(0.3, top_score * 0.04) + min(0.1, max(0, top_score - runner_up_score) * 0.03)


def _preferred_first_tool(
    text: str,
    *,
    policy: _ToolPolicy,
    symbol_hits: tuple[str, ...],
    file_browse_hits: tuple[str, ...],
    web_lookup_hits: tuple[str, ...],
    fresh_external_hits: tuple[str, ...],
) -> str | None:
    if policy in {"live_web_research", "execution"} and _should_prefer_web_fetch(text):
        return "web_fetch"
    if policy == "workspace_lookup":
        if file_browse_hits and not symbol_hits:
            return "list_files"
        if (
            symbol_hits
            or _CODE_OR_FILE_REFERENCE_RE.search(text)
            or _contains_any(text, _CODE_SEARCH_TOOL_INTENT_MARKERS)
        ):
            return "search_code"
    if policy == "live_web_research":
        if web_lookup_hits or _contains_any(text, _LIVE_WEB_SEARCH_FIRST_MARKERS):
            return "web_search"
    if policy == "execution":
        wants_workspace_first = bool(symbol_hits) and not file_browse_hits
        wants_web_first = bool(web_lookup_hits or fresh_external_hits)
        if wants_workspace_first and not wants_web_first:
            return "search_code"
        if wants_web_first and not wants_workspace_first:
            return "web_search"
    return None


def _should_prefer_web_fetch(text: str) -> bool:
    if not _first_http_url(text):
        return False
    return _contains_any(
        text,
        (
            "fetch",
            "open",
            "read",
            "打开",
            "读取",
            "抓取",
            "获取",
            "看一下",
            "查看",
            "网页",
            "页面",
            "标题",
            "summary",
            "summarize",
        ),
    )


def _first_http_url(text: str) -> str:
    match = _HTTP_URL_RE.search(str(text or ""))
    if not match:
        return ""
    return match.group(0).rstrip(".,!?;:，。！？；：")


def _tools_for_policy(
    policy: _ToolPolicy,
    tools: list[Any],
    latest_user: str = "",
    *,
    role: AgentRole | str | None = None,
    exposure: TurnToolExposure | None = None,
) -> list[Any]:
    effective_policy = exposure.policy if exposure is not None else policy
    policy_engine = CapabilityPolicyEngine()
    roles = _roles_for_policy(effective_policy, role=role, exposure=exposure)
    candidates = [
        tool
        for tool in tools
        if any(
            policy_engine.tool_allowed(tool, role=effective_role, tool_policy=effective_policy)[0]
            for effective_role in roles
        )
    ]
    if exposure is not None:
        candidates = _filter_tools_by_exposure(candidates, exposure)
    if effective_policy == "workspace_lookup":
        normalized = " ".join(latest_user.strip().split())
        if _contains_any(normalized, _CODE_SEARCH_TOOL_INTENT_MARKERS) and not _contains_any(
            normalized, _FILE_BROWSE_INTENT_MARKERS
        ):
            focused = [
                tool for tool in candidates if "code_search" in _tool_runtime(tool).intent_tags
            ]
            if focused:
                return focused
    return candidates


def _roles_for_policy(
    policy: _ToolPolicy,
    *,
    role: AgentRole | str | None,
    exposure: TurnToolExposure | None,
) -> tuple[AgentRole | str, ...]:
    if role is not None:
        return (role,)
    if exposure is not None and set(exposure.allowed_toolsets) == {"skill"}:
        return (AgentRole.SKILL_SCOUT, AgentRole.PLANNER)
    if (
        exposure is not None
        and policy == "execution"
        and set(exposure.allowed_toolsets) == {"web", "workspace"}
    ):
        return (AgentRole.PLANNER, AgentRole.EXECUTOR)
    return (_default_role_for_policy(policy),)


def _filter_tools_by_exposure(tools: list[Any], exposure: TurnToolExposure) -> list[Any]:
    allowed_toolsets = set(exposure.allowed_toolsets)
    hard_denied_toolsets = set(exposure.hard_denied_toolsets)
    filtered: list[Any] = []
    for tool in tools:
        runtime = _tool_runtime(tool)
        if runtime.toolset in hard_denied_toolsets:
            continue
        if allowed_toolsets and runtime.toolset not in allowed_toolsets:
            continue
        if exposure.policy == "execution" and allowed_toolsets:
            if runtime.side_effect or runtime.requires_workspace_write:
                continue
        filtered.append(tool)
    return filtered


def _tool_runtime(tool: Any) -> ToolRuntimeMeta:
    return ToolRuntimeMeta.from_tool(tool)


def _default_role_for_policy(policy: _ToolPolicy) -> AgentRole:
    if policy == "live_web_research":
        return AgentRole.PLANNER
    return AgentRole.EXECUTOR


def _workspace_lookup_should_start_with_search(
    text: str, messages: list[Any], tools: list[Any], exposure: TurnToolExposure | None = None
) -> bool:
    normalized = " ".join(text.strip().split())
    if not normalized:
        return False
    if any(isinstance(message, ToolMessage) for message in messages):
        return False
    if not any(str(getattr(tool, "name", "")) == "search_code" for tool in tools):
        return False
    if exposure is not None and exposure.preferred_first_tool is not None:
        return exposure.preferred_first_tool == "search_code"
    return _contains_any(normalized, _CODE_SEARCH_TOOL_INTENT_MARKERS) and not _contains_any(
        normalized,
        _FILE_BROWSE_INTENT_MARKERS,
    )


def _live_web_research_should_start_with_search(
    text: str, messages: list[Any], tools: list[Any], exposure: TurnToolExposure | None = None
) -> bool:
    normalized = " ".join(text.strip().split())
    if not normalized:
        return False
    if _has_non_temporal_anchor_tool_result(messages):
        return False
    if not any(str(getattr(tool, "name", "")) == "web_search" for tool in tools):
        return False
    if exposure is not None and exposure.preferred_first_tool is not None:
        return exposure.preferred_first_tool == "web_search"
    return _contains_any(normalized, _LIVE_WEB_SEARCH_FIRST_MARKERS)


def _has_non_temporal_anchor_tool_result(messages: list[Any]) -> bool:
    latest_human_index = -1
    for index, message in enumerate(messages):
        if getattr(message, "type", None) == "human":
            latest_human_index = index

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
            name = call_names_by_id.get(str(message.tool_call_id or "").strip())
            if name != "current_utc_time":
                return True
    return False


def _workspace_search_query(text: str) -> str:
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?", text)
    seen: list[str] = []
    for token in tokens:
        lowered = token.lower()
        if lowered in {"repo", "repository", "codebase", "source", "file", "function", "class"}:
            continue
        if token not in seen:
            seen.append(token)
    if seen:
        return " ".join(seen[:6])
    return text.strip()


def _tool_policy_note(policy: _ToolPolicy) -> str:
    if policy == "direct_answer":
        return _DIRECT_ANSWER_NOTE
    if policy == "workspace_lookup":
        return _WORKSPACE_TOOL_NOTE
    if policy == "live_web_research":
        return _LIVE_WEB_TOOL_NOTE
    return _BRANCH_ACTION_GUARD_NOTE


__all__ = [
    "_BRANCH_ACTION_GUARD_NOTE",
    "_DIRECT_ANSWER_NOTE",
    "_LIVE_WEB_TOOL_NOTE",
    "_WORKSPACE_TOOL_NOTE",
    "TurnToolExposure",
    "build_tool_intent_plan",
    "_classify_turn_tool_exposure",
    "_classify_turn_tool_policy",
    "_live_web_research_should_start_with_search",
    "_temporal_live_web_search_args",
    "_tool_intent_plan_requires_temporal_anchor",
    "_tool_policy_note",
    "_tools_for_policy",
    "_workspace_lookup_should_start_with_search",
    "_workspace_search_query",
]
