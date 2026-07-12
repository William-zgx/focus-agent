from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ...capabilities.tool_registry import ToolRuntimeMeta
from ...capabilities.tool_router import SkillExecutionPlan, ToolIntentPlan
from ...skills import SkillRegistry
from ...skills.models import SkillDefinition

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
    max_primary_tool_skills = 2
    for index, (_, skill, reasons) in enumerate(matches):
        selected_skill_ids.append(skill.skill_id)
        skill_primary = _skill_primary_tools(skill)
        skill_supporting = _skill_supporting_tools(skill, primary_tools=skill_primary)
        if index < max_primary_tool_skills:
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
        tool_name for tool_name in recommended if tool_name not in _SKILL_SUPPORTING_TOOL_DEFAULTS
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
