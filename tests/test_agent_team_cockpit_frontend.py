from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT_TEAM_ROOT = ROOT / "apps" / "web" / "src" / "features" / "agent-team"
AGENT_TEAM_STYLES = (
    ROOT / "apps" / "web" / "src" / "shared" / "styles" / "modules" / "agent-team.css"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


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


def _assert_contains_all(text: str, expected: list[str]) -> None:
    for item in expected:
        assert item in text, f"missing expected frontend contract text: {item}"


def _compact(text: str) -> str:
    return " ".join(text.split())


def test_create_page_exposes_cockpit_collaboration_modes():
    create_text = _read(AGENT_TEAM_ROOT / "agent-team-workbench-create.tsx")
    options_text = _read(AGENT_TEAM_ROOT / "agent-team-create-options.ts")
    create_contract_text = create_text + "\n" + options_text
    styles_text = _read_agent_team_styles()

    for text in ["快一点", "稳一点", "细一点", "COLLABORATION_MODES", "selectedCollaboration"]:
        assert text in create_contract_text
    assert 'granularity: "coarse"' in create_contract_text
    assert 'granularity: "balanced"' in create_contract_text
    assert 'granularity: "detailed"' in create_contract_text
    assert 'focus: "implementation"' in create_contract_text
    assert 'focus: "verification"' in create_contract_text
    assert 'focus: "auto"' in create_contract_text
    assert "max_tasks: selectedCollaboration.maxTasks" in create_text
    assert "fa-agent-team-collab-grid" in styles_text
    assert "fa-agent-team-collab-card" in styles_text


def test_workbench_uses_agent_team_cockpit_and_merge_decision_hook():
    workbench_text = _read(AGENT_TEAM_ROOT / "agent-team-workbench.tsx")
    hook_text = _read(AGENT_TEAM_ROOT / "use-agent-team.ts")
    types_text = _read(AGENT_TEAM_ROOT / "types.ts")

    assert "AgentTeamCockpit" in workbench_text
    assert "useAgentTeamMergeDecision" in workbench_text
    assert "recordAgentTeamMergeDecision" in hook_text
    assert "AgentTeamMergeDecisionRequest" in types_text
    assert "AgentTeamMergeDecisionResponse" in types_text
    assert "apply?: boolean" in types_text
    assert "next_action?: AgentTeamMergeDecisionAction" in types_text
    assert "approved?: boolean" in types_text
    assert "action?: AgentTeamMergeDecisionAction" in types_text
    assert 'next_action: "merge"' in workbench_text
    assert "accepted_tasks: tasks.map" in workbench_text
    assert "branchDecisionThreadIdFromSessionData" in workbench_text
    assert 'startsWith("agent-team-standalone-") ? "" : rootThreadId' in workbench_text
    assert "PreMergeCheckPanel" not in workbench_text
    assert "TaskLanesPanel" not in workbench_text


def test_view_model_derives_cockpit_state():
    view_model_text = _read(AGENT_TEAM_ROOT / "agent-team-workbench-view-model.ts")
    derived_state_text = _read(AGENT_TEAM_ROOT / "agent-team-workbench-derived-state.ts")
    decision_state_text = _read(AGENT_TEAM_ROOT / "agent-team-workbench-decision-state.ts")
    focus_state_text = _read(AGENT_TEAM_ROOT / "agent-team-workbench-focus-state.ts")
    view_model_contract_text = view_model_text + "\n" + derived_state_text
    selector_contract_text = view_model_text + "\n" + decision_state_text + "\n" + focus_state_text

    _assert_contains_all(
        view_model_text,
        [
            "missionHeaderState",
            "phaseMapItems",
            "recommendedTaskId",
            "focusReason",
            "decisionDockState",
            "finalPreviewState",
        ],
    )
    _assert_contains_all(
        selector_contract_text,
        [
            "isPlanReview",
            "recommendedTaskStateForSelection",
            "isPlanReviewState",
            'state.kind === "failed" || state.kind === "needs_attention"',
            'state.kind === "running" || state.kind === "queued"',
            'state.kind === "ready"',
            'state.kind === "completed"',
        ],
    )
    _assert_contains_all(
        view_model_contract_text,
        [
            "placeholder",
            "Not deliverable",
            "deliverable",
            "Final Preview",
            "request_changes",
        ],
    )
    for legacy_compat_field in [
        "isPlanReview",
        "phaseGroups",
        "recommendedTaskReason",
        "finalResultState",
    ]:
        assert legacy_compat_field in view_model_text


def test_cockpit_component_contains_required_surfaces():
    cockpit_text = _read(AGENT_TEAM_ROOT / "agent-team-cockpit.tsx")
    cockpit_helper_text = _read(AGENT_TEAM_ROOT / "agent-team-cockpit-helpers.ts")
    workbench_text = _read(AGENT_TEAM_ROOT / "agent-team-workbench.tsx")
    cockpit_contract_text = cockpit_text + "\n" + cockpit_helper_text
    combined_text = cockpit_contract_text + "\n" + workbench_text

    _assert_contains_all(
        cockpit_contract_text,
        [
            "MissionHeader",
            "MissionSteps",
            "TaskList",
            "TaskDetail",
            "FinalResultCard",
            "BlockedTaskGuide",
            "blockedReasonInfo",
            "Automatic execution is off",
            "自动执行没有开启",
            "Show next step",
            "重试这个任务",
            "useRetryAgentTeamTask",
        ],
    )
    _assert_contains_all(
        cockpit_text,
        [
            "fa-agent-team-simple-hero",
            "fa-agent-team-simple-steps",
            "fa-agent-team-simple-main",
            "fa-agent-team-simple-task-list",
            "fa-agent-team-blocked-guide",
            "fa-agent-team-simple-task is-",
            "is-blocked-action",
            "fa-agent-team-fix-box",
            "fa-agent-team-simple-result",
        ],
    )
    _assert_contains_all(
        combined_text,
        [
            "Inspector",
            "fa-agent-team-inspector-overlay",
            "fa-agent-team-inspector-drawer",
        ],
    )
    assert (
        "const primaryDisabled = Boolean(viewModel.primaryAction.disabledReason) || "
        "Boolean(viewModel.primaryAction.busy);"
    ) in _compact(cockpit_text)
    assert (
        "const primaryClick = blockedTask ? () => actions.onSelectTask(blockedTask.task_id) "
        ": actions.onPrimaryAction;"
    ) in _compact(cockpit_text)
    assert "onClick={primaryClick}" in cockpit_text


def test_cockpit_css_keeps_lightweight_hierarchy_without_binding_visual_treatment():
    styles_text = _read_agent_team_styles()

    _assert_contains_all(
        styles_text,
        [
            ".fa-agent-team-simple-hero",
            "grid-template-columns: minmax(0, 1fr) minmax(240px, 320px)",
            ".fa-agent-team-simple-main",
            "overflow-x: visible",
            ".fa-agent-team-simple-task",
            ".fa-agent-team-blocked-guide",
            ".fa-agent-team-simple-task.is-blocked-action",
            ".fa-agent-team-simple-detail.is-blocked-detail",
            ".fa-agent-team-fix-box",
            ".fa-agent-team-inspector-overlay",
            "position: fixed;",
            ".fa-agent-team-inspector-drawer",
            "transform: translateX(100%)",
        ],
    )
    mobile_start = styles_text.rfind("@media (max-width: 760px)")
    assert mobile_start >= 0, "missing mobile simple media query"
    assert ".fa-agent-team-blocked-guide" in styles_text[mobile_start:]
