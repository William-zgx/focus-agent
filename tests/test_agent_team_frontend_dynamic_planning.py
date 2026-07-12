from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT_TEAM_ROOT = ROOT / "apps" / "web" / "src" / "features" / "agent-team"
AGENT_TEAM_STYLES = (
    ROOT / "apps" / "web" / "src" / "shared" / "styles" / "modules" / "agent-team.css"
)
COCKPIT_SOURCE_FILES = (
    "agent-team-cockpit.tsx",
    "agent-team-cockpit-mission.tsx",
    "agent-team-cockpit-panels.tsx",
    "agent-team-cockpit-types.ts",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_cockpit_sources() -> str:
    return "\n".join(_read(AGENT_TEAM_ROOT / name) for name in COCKPIT_SOURCE_FILES)


def _read_agent_team_styles() -> str:
    module_dir = AGENT_TEAM_STYLES.parent
    seen: set[Path] = set()

    def read_with_imports(path: Path) -> list[str]:
        if path in seen:
            return []
        seen.add(path)
        text = _read(path)
        chunks = [text]
        for line in text.splitlines():
            if line.startswith("@import ") and '"' in line:
                chunks.extend(read_with_imports(module_dir / line.split('"', 2)[1]))
        return chunks

    return "\n".join(read_with_imports(AGENT_TEAM_STYLES))


def _read_task_surface_text() -> str:
    return "\n".join(
        _read(AGENT_TEAM_ROOT / name)
        for name in [
            "agent-team-workbench-task-lanes.tsx",
            "agent-team-workbench-task-board.tsx",
            "agent-team-workbench-task-detail.tsx",
            "agent-team-workbench-task-returned-sections.tsx",
            "agent-team-workbench-task-view-helpers.tsx",
        ]
    )


def test_create_page_no_longer_shows_fixed_role_template():
    create_text = _read(AGENT_TEAM_ROOT / "agent-team-workbench-create.tsx")

    assert "DEFAULT_TASK_ROLES" not in create_text
    assert "计划模板" not in create_text
    assert "默认角色只是参考" not in create_text
    assert "Default roles are guidance" not in create_text
    assert "生成协作方案" in create_text
    assert "planAgentTeamSession" in create_text
    assert "dispatchAgentTeamSession" in create_text
    assert "生成方案中" in create_text
    assert "Step 1" not in create_text
    assert "Step 2" not in create_text
    assert "Step 3" not in create_text
    assert "第一步" not in create_text
    assert "第二步" not in create_text
    assert "第三步" not in create_text
    assert "不绑定来源，直接创建独立 Mission" in create_text
    assert "root_thread_id?: string | null" in _read(AGENT_TEAM_ROOT / "types.ts")


def test_workbench_exposes_dynamic_planning_controls_and_metadata():
    workbench_text = (
        "\n".join(
            [
                _read(AGENT_TEAM_ROOT / "agent-team-workbench.tsx"),
                _read(AGENT_TEAM_ROOT / "agent-team-workbench-view-model.ts"),
            ]
        )
        + "\n"
        + _read_cockpit_sources()
    )
    cockpit_entry_text = _read(AGENT_TEAM_ROOT / "agent-team-cockpit.tsx")
    styles_text = _read_agent_team_styles()

    assert "export function AgentTeamCockpit" in cockpit_entry_text
    assert 'from "./agent-team-cockpit-mission"' in cockpit_entry_text
    assert 'from "./agent-team-cockpit-panels"' in cockpit_entry_text
    assert 'from "./agent-team-cockpit-types"' in cockpit_entry_text
    for text in ["生成方案", "重新拆解", "运行 Mission", "生成最终结果"]:
        assert text in workbench_text or text in _read(
            AGENT_TEAM_ROOT / "agent-team-workbench-utils.ts"
        )

    assert "fa-agent-team-guided-layout" in workbench_text
    assert "fa-agent-team-cockpit-mission-header" in workbench_text
    assert "fa-agent-team-cockpit-grid" in workbench_text
    assert "fa-agent-team-cockpit-button is-primary" in workbench_text
    assert "Decision Dock" in workbench_text
    assert "Plan Review" in workbench_text
    assert "AdvancedDetailsPanel" in workbench_text
    assert "StatusPill status={session.status}" not in workbench_text
    assert "待审查" not in workbench_text
    assert "模型规划不可用，已使用保守协作方案" in workbench_text
    assert "fa-agent-team-planning-meta" not in workbench_text
    assert "fa-agent-team-refine-strip" not in workbench_text
    assert "replace_existing: true" in workbench_text
    assert 'granularity: "detailed"' in workbench_text
    assert 'granularity: "coarse"' in workbench_text
    assert 'focus: "implementation"' in workbench_text
    assert 'focus: "verification"' in workbench_text
    assert "fa-agent-team-cockpit-grid" in styles_text
    assert "fa-agent-team-cockpit-button" in styles_text
    assert "fa-agent-team-inspector-overlay" in styles_text
    assert "fa-agent-team-plan-banner" in styles_text


def test_task_surface_prefers_dynamic_plan_fields_over_roles():
    task_text = _read_task_surface_text()
    types_text = _read(AGENT_TEAM_ROOT / "types.ts")

    assert "taskTitle(task)" in task_text
    assert "taskSubtitle(task, isChineseUi)" in task_text
    assert "task.planning_rationale" in task_text
    assert "task.task_type" in task_text
    assert "fa-agent-team-task-timeline" in task_text
    assert "高级详情" in task_text
    assert "等待前置任务" in task_text
    assert "需要处理" in task_text
    assert "执行失败" in task_text
    assert "任务回传" in task_text
    assert "回传摘要" in task_text
    assert "结果摘要" in task_text
    assert "关键依据" in task_text
    assert "依据 ${taskEvidence.length} 条 · 风险 ${taskRiskCount} 条" in task_text
    assert "TaskGuidedSections" in task_text
    assert "{isSelected ? (" not in task_text
    assert "产物内容" in task_text
    assert "outputsForTask" in task_text
    assert "artifactsForTask" in task_text
    assert "outputExecutionItems" in task_text
    assert "outputs:" in _read(AGENT_TEAM_ROOT / "agent-team-workbench-utils.ts")
    assert "运行此任务：不可用" in task_text
    assert "原始运行状态" in task_text
    assert "原始 output payload" in task_text
    assert "原始 artifact payload" in task_text
    assert "阻塞" not in task_text
    assert "roleLabel" not in task_text
    assert "roleHint" not in task_text
    assert "DEFAULT_TASK_ROLES" not in task_text

    for field in [
        "planning_source",
        "planner_model_id",
        "plan_generated_at",
        "planning_error",
        "title",
        "planning_rationale",
        "task_type",
        "plan_source",
    ]:
        assert field in types_text
    assert "payload?: Record<string, unknown> | null" in types_text


def test_default_result_panel_summarizes_raw_execution_text():
    workbench_text = (
        "\n".join(
            [
                _read(AGENT_TEAM_ROOT / "agent-team-workbench.tsx"),
                _read(AGENT_TEAM_ROOT / "agent-team-workbench-view-model.ts"),
            ]
        )
        + "\n"
        + _read_cockpit_sources()
    )
    cockpit_entry_text = _read(AGENT_TEAM_ROOT / "agent-team-cockpit.tsx")
    result_text = _read(AGENT_TEAM_ROOT / "agent-team-workbench-merge-handoff.tsx")
    styles_text = _read_agent_team_styles()

    assert "export function AgentTeamCockpit" in cockpit_entry_text
    assert 'from "./agent-team-cockpit-panels"' in cockpit_entry_text
    assert "finalResultState" in workbench_text
    assert "Final Preview" in workbench_text
    assert "executionModeForWorkbench" in workbench_text
    assert "模拟执行" in workbench_text
    assert "真实模型执行" in workbench_text
    assert "后台执行" in workbench_text
    assert "finalResultSummary" in result_text
    assert "finalAnswerText" in result_text
    assert "final_answer" in result_text
    assert "final_answer_status" in result_text
    assert "final_answer_warnings" in result_text
    assert "source_output_ids" in result_text
    assert "isRawRunText" in result_text
    assert "任务产出已回传" in result_text
    assert "原始依据" in result_text
    assert "Raw outputs" in result_text
    assert "limitUserFacingItems" in result_text
    assert "模拟执行提示" in result_text
    assert "当前下一步" not in result_text
    assert "-webkit-line-clamp: 2" in styles_text
