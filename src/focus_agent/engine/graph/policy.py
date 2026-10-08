from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from langchain.messages import ToolMessage as ToolMessage

from ...capabilities.tool_router import ToolIntentPlan
from .policy_intent import (
    is_tool_carryover_confirmation as _is_tool_carryover_confirmation,
)
from .policy_intent import (
    pending_live_web_search_intent as _pending_live_web_search_intent,
)
from .policy_intent import (
    requires_temporal_anchor as _requires_temporal_anchor,
)
from .policy_intent_parsing import (
    _HTTP_URL_RE as _HTTP_URL_RE,
)
from .policy_intent_parsing import (
    _SKILL_ID_RE as _SKILL_ID_RE,
)
from .policy_intent_parsing import (
    _explicit_web_tool_contract_reason_codes,
    _filter_bare_current_hits,
    _preferred_first_args,
    _preferred_first_tool,
    _remote_url_local_mutation_request,
    _should_prefer_web_fetch,
    _ToolPolicy,
    _workspace_search_query,
    requires_external_evidence,
)
from .policy_intent_parsing import (
    _first_http_url as _first_http_url,
)
from .policy_intent_parsing import (
    _skill_install_name_from_text as _skill_install_name_from_text,
)
from .policy_intent_parsing import (
    _skill_view_name_from_text as _skill_view_name_from_text,
)
from .policy_markers import (
    _ALL_FILTERABLE_TOOLSETS,
    _BARE_CURRENT_MARKERS,
    _CODE_OR_FILE_REFERENCE_RE,
    _CODE_SEARCH_TOOL_INTENT_MARKERS,  # noqa: F401
    _CREATIVE_DIRECT_MARKERS,
    _EXECUTION_INTENT_MARKERS,
    _EXPLICIT_WORKSPACE_CONTEXT_MARKERS,
    _FILE_BROWSE_INTENT_MARKERS,
    _FRESH_EXTERNAL_INTENT_MARKERS,
    _LIVE_WEB_INTENT_MARKERS,
    _LIVE_WEB_SEARCH_FIRST_MARKERS,  # noqa: F401
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
    _skill_install_hits,
)
from .policy_notes import (
    _BRANCH_ACTION_GUARD_NOTE,
    _DIRECT_ANSWER_NOTE,
    _LIVE_WEB_TOOL_NOTE,
    _WORKSPACE_TOOL_NOTE,
    _tool_policy_note,
)
from .policy_skill_markers import _explicit_skill_management_request
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
    explicit_window_days,
)
from .policy_tools import (
    _live_web_research_should_start_with_search,
    _tools_for_policy,
    _workspace_lookup_should_start_with_search,
)

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
    if explicit_window_days(normalized):
        fresh_external_hits = (*fresh_external_hits, "explicit_time_window")
    web_lookup_hits = _matched_markers(normalized, _WEB_LOOKUP_ACTION_MARKERS)
    if not web_lookup_hits:
        live_hits, fresh_external_hits = _filter_bare_current_hits(
            live_hits,
            fresh_external_hits,
            bare_current_markers=_BARE_CURRENT_MARKERS,
        )
    contextual_current_hits = set(_contextual_current_hits(normalized))
    if contextual_current_hits:
        live_hits = tuple(hit for hit in live_hits if hit not in contextual_current_hits)
        fresh_external_hits = tuple(
            hit for hit in fresh_external_hits if hit not in contextual_current_hits
        )
    academic_lookup_hits = _academic_web_lookup_hits(normalized)
    # URL paths can contain underscore-delimited slugs such as ``api_v2`` or
    # ``source_code``. They are remote resource identifiers, not local code
    # references, so exclude URL spans before applying the workspace heuristic.
    code_reference_text = _HTTP_URL_RE.sub(" ", normalized)
    code_reference_hit = bool(_CODE_OR_FILE_REFERENCE_RE.search(code_reference_text))
    if academic_lookup_hits:
        live_hits = tuple(dict.fromkeys((*live_hits, *academic_lookup_hits)))
        web_lookup_hits = tuple(dict.fromkeys((*web_lookup_hits, *academic_lookup_hits)))
    skill_discovery_hits = _skill_discovery_hits(normalized)
    skill_install_hits = _skill_install_hits(normalized)
    if _contains_any(normalized, ("引用来源", "引用数据来源", "cite source", "cite sources")):
        symbol_hits = tuple(hit for hit in symbol_hits if hit not in {"引用", "reference"})
    execution_hits = _matched_markers(normalized, _EXECUTION_INTENT_MARKERS)
    explicit_temporal_web_contract = (
        "current_utc_time" in normalized and "web_search" in normalized and bool(web_lookup_hits)
    )
    remote_url_read_request = _should_prefer_web_fetch(normalized)
    remote_url_local_mutation_request = _remote_url_local_mutation_request(normalized)
    if remote_url_local_mutation_request:
        execution_hits = tuple(dict.fromkeys((*execution_hits, "remote_url_local_mutation")))
    elif remote_url_read_request and not local_context_hits and not file_browse_hits:
        # A remote page-reading request wins over generic execution words when
        # no local target or mutation was requested.
        execution_hits = ()
    if explicit_temporal_web_contract:
        execution_hits = tuple(
            hit for hit in execution_hits if hit not in {"修改", "modify", "文件", "file"}
        )
        explicit_workspace_hits = tuple(
            hit for hit in explicit_workspace_hits if hit not in {"文件", "file"}
        )
        workspace_hits = tuple(hit for hit in workspace_hits if hit not in {"文件", "file"})
    creative_hits = _matched_markers(normalized, _CREATIVE_DIRECT_MARKERS)
    strong_explicit_workspace_hits = tuple(
        hit for hit in explicit_workspace_hits if hit not in _WEAK_WORKSPACE_CONTEXT_MARKERS
    )
    if (
        remote_url_read_request
        and not remote_url_local_mutation_request
        and not local_context_hits
        and not file_browse_hits
    ):
        # Provenance terms describe how to cite a remote page here; they should
        # not turn a URL-reading request into a local code lookup. Keep other
        # explicit workspace terms (for example "source file" or "function")
        # so that a URL plus a local inspection request remains distinguishable.
        provenance_markers = {"引用", "reference", "source"}
        symbol_hits = tuple(hit for hit in symbol_hits if hit not in provenance_markers)
        workspace_hits = tuple(hit for hit in workspace_hits if hit not in provenance_markers)
        explicit_workspace_hits = tuple(
            hit for hit in explicit_workspace_hits if hit not in provenance_markers
        )
        strong_explicit_workspace_hits = tuple(
            hit for hit in strong_explicit_workspace_hits if hit not in provenance_markers
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

    # Generic capability words are weak discovery hints, not a reason to deny
    # web access for an external research task. Explicit local skill requests win.
    explicit_skill_request = _explicit_skill_management_request(normalized)
    if (fresh_external_hits or remote_url_read_request) and not explicit_skill_request:
        skill_discovery_hits = ()
    external_evidence_required = requires_external_evidence(normalized)
    if external_evidence_required and not explicit_skill_request:
        skill_discovery_hits = ()
        if not has_strong_workspace_signal and not remote_url_local_mutation_request:
            return _exposure(
                "live_web_research",
                confidence=0.95,
                reason_codes=("explicit_external_evidence", "policy_live_web_research"),
                preferred_first_tool="web_fetch" if remote_url_read_request else "web_search",
            )

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
    if skill_install_hits:
        reason_codes.append("skill_install_intent")

    preferred_skill_tool = _skill_discovery_preferred_tool(normalized)
    if skill_install_hits:
        explicit_skill_install = "skill_install" in skill_install_hits
        reason_codes.append("policy_execution")
        return _exposure(
            "execution",
            confidence=max(0.86, _confidence(len(skill_install_hits) * 4, workspace_score)),
            reason_codes=tuple(reason_codes),
            preferred_first_tool="skill_install" if explicit_skill_install else "skills_search",
            allowed_toolsets=("skill",),
        )
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

    if explicit_temporal_web_contract:
        reason_codes = [
            code
            for code in reason_codes
            if code
            not in {
                "execution_signal",
                "local_workspace_context",
                "mixed_live_web_workspace",
                "workspace_lookup_signal",
            }
        ]
        reason_codes.append("explicit_temporal_web_contract")
        reason_codes.append("policy_live_web_research")
        return _exposure(
            "live_web_research",
            confidence=max(0.95, _confidence(live_web_score, workspace_score)),
            reason_codes=tuple(reason_codes),
            preferred_first_tool="web_search",
        )

    if remote_url_local_mutation_request:
        reason_codes.append("remote_url_local_mutation")
        reason_codes.append("policy_execution")
        return _exposure(
            "execution",
            confidence=_confidence(execution_score, max(workspace_score, live_web_score)),
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

    explicit_web_tool_reason_codes = _explicit_web_tool_contract_reason_codes(
        normalized,
        has_live_web_signal=has_live_web_signal,
        has_local_workspace_context=bool(local_context_hits),
        has_explicit_workspace_context=bool(strong_explicit_workspace_hits),
        has_file_browse=bool(file_browse_hits),
        reason_codes=reason_codes,
    )
    if explicit_web_tool_reason_codes is not None:
        return _exposure(
            "live_web_research",
            confidence=max(0.95, _confidence(live_web_score, execution_score)),
            reason_codes=explicit_web_tool_reason_codes,
            preferred_first_tool=_preferred_first_tool(
                normalized,
                policy="live_web_research",
                symbol_hits=symbol_hits,
                file_browse_hits=file_browse_hits,
                web_lookup_hits=web_lookup_hits,
                fresh_external_hits=fresh_external_hits,
            ),
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
