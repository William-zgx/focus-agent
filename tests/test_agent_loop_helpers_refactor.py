from __future__ import annotations

from pathlib import Path

from focus_agent.capabilities.tool_router import ToolIntentPlan
from focus_agent.engine.graph import agent_loop_helpers
from focus_agent.skills.models import SkillDefinition


class _SingleSkillRegistry:
    def __init__(self, skill: SkillDefinition) -> None:
        self._skill = skill

    def resolve(self, skill_id: str) -> SkillDefinition | None:
        if skill_id == self._skill.skill_id:
            return self._skill
        return None

    def is_skill_enabled(self, skill_id: str) -> bool:
        return skill_id == self._skill.skill_id


def _active_skill(tmp_path: Path) -> SkillDefinition:
    skill_path = tmp_path / ".focus_agent" / "skills" / "quality" / "SKILL.md"
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text("# Quality", encoding="utf-8")
    return SkillDefinition(
        skill_id="quality",
        description="Run quality checks.",
        path=skill_path,
        body="",
        raw_text="",
        aliases=("quality",),
        primary_tools=("run_workspace_command",),
        prompt_mode="execute",
    )


def test_agent_loop_helpers_facade_stays_within_line_budget() -> None:
    helper_path = Path(agent_loop_helpers.__file__)

    assert len(helper_path.read_text(encoding="utf-8").splitlines()) <= 740


def test_agent_loop_helpers_reexports_skill_planning_interfaces() -> None:
    legacy_private_symbols = (
        "_ACTIVE_EXECUTE_CONTINUATION_MARKERS",
        "_FINANCE_ENTITY_HINTS",
        "_FINANCE_PERFORMANCE_MARKERS",
        "_LIVE_WEB_DOMAIN_MARKERS",
        "_SKILL_SUPPORTING_TOOL_DEFAULTS",
        "_STOCK_CODE_RE",
        "_active_execute_continuation_allowed",
        "_active_skill_match_score",
        "_active_skill_recommended_tool_names",
        "_explicit_live_web_domains",
        "_is_explicit_skill_lookup_policy",
        "_looks_like_active_execute_continuation",
        "_merge_active_skill_recommended_tools",
        "_normalized_skill_tool_names",
        "_query_matches_live_web_domain",
        "_recommended_tool_allowed_for_policy",
        "_skill_live_web_domains",
        "_skill_match_terms",
        "_skill_primary_tools",
        "_skill_runtime_cwd",
        "_skill_supporting_tools",
        "_skill_supports_live_web_domains",
    )

    assert callable(agent_loop_helpers._merge_active_skill_recommended_tools)
    assert callable(agent_loop_helpers.build_active_skill_execution_plan)
    assert callable(agent_loop_helpers.apply_skill_execution_plan)
    assert callable(agent_loop_helpers.skill_execution_policy_note)
    assert agent_loop_helpers._SKILL_SUPPORTING_TOOL_DEFAULTS
    assert all(hasattr(agent_loop_helpers, name) for name in legacy_private_symbols)


def test_skill_plan_uses_legacy_helper_patch_seam(tmp_path: Path, monkeypatch) -> None:
    skill = _active_skill(tmp_path)
    registry = _SingleSkillRegistry(skill)
    base_plan = ToolIntentPlan(policy="execution")

    monkeypatch.setattr(
        agent_loop_helpers,
        "_active_skill_match_score",
        lambda *_args, **_kwargs: (0.0, []),
    )

    plan = agent_loop_helpers.build_active_skill_execution_plan(
        skill_registry=registry,
        active_skill_ids=[skill.skill_id],
        text="quality",
        workspace_root=tmp_path,
        base_intent_plan=base_plan,
    )

    assert plan is None


def test_recommended_tool_merging_uses_legacy_helper_patch_seam(
    tmp_path: Path,
    monkeypatch,
) -> None:
    skill = _active_skill(tmp_path)
    registry = _SingleSkillRegistry(skill)
    available_tool = type("Tool", (), {"name": "read_file"})()
    recommended_tool = type("Tool", (), {"name": "run_workspace_command"})()

    monkeypatch.setattr(
        agent_loop_helpers,
        "_recommended_tool_allowed_for_policy",
        lambda *_args, **_kwargs: False,
    )

    merged = agent_loop_helpers._merge_active_skill_recommended_tools(
        [available_tool],
        [available_tool, recommended_tool],
        skill_registry=registry,
        active_skill_ids=[skill.skill_id],
        tool_policy="execution",
    )

    assert merged == [available_tool]
