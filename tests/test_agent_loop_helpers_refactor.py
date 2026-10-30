from __future__ import annotations

from pathlib import Path

from focus_agent.capabilities.tool_router import ToolIntentPlan
from focus_agent.engine.graph import agent_loop_helpers
from focus_agent.engine.graph import agent_loop_helpers_skill_planning as skill_planning
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


def test_skill_plan_skips_unmatched_active_skill(tmp_path: Path, monkeypatch) -> None:
    skill = _active_skill(tmp_path)
    registry = _SingleSkillRegistry(skill)
    base_plan = ToolIntentPlan(policy="execution")

    monkeypatch.setattr(
        skill_planning,
        "_active_skill_match_score",
        lambda *_args, **_kwargs: (0.0, []),
    )

    plan = skill_planning.build_active_skill_execution_plan(
        skill_registry=registry,
        active_skill_ids=[skill.skill_id],
        text="quality",
        workspace_root=tmp_path,
        base_intent_plan=base_plan,
    )

    assert plan is None


def test_recommended_tool_merging_respects_policy_filter(
    tmp_path: Path,
    monkeypatch,
) -> None:
    skill = _active_skill(tmp_path)
    registry = _SingleSkillRegistry(skill)
    available_tool = type("Tool", (), {"name": "read_file"})()
    recommended_tool = type("Tool", (), {"name": "run_workspace_command"})()

    monkeypatch.setattr(
        skill_planning,
        "_recommended_tool_allowed_for_policy",
        lambda *_args, **_kwargs: False,
    )

    merged = skill_planning._merge_active_skill_recommended_tools(
        [available_tool],
        [available_tool, recommended_tool],
        skill_registry=registry,
        active_skill_ids=[skill.skill_id],
        tool_policy="execution",
    )

    assert merged == [available_tool]
