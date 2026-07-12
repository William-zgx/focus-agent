from focus_agent.engine.graph import policy, policy_markers, policy_skill_markers


def test_policy_markers_reexports_skill_marker_symbols():
    symbol_names = (
        "_SKILL_DISCOVERY_SUBJECT_MARKERS",
        "_SKILL_DISCOVERY_PHRASE_MARKERS",
        "_SKILL_DISCOVERY_ACTION_MARKERS",
        "_SKILL_EXECUTION_ACTION_MARKERS",
        "_SKILL_TASK_EXECUTION_MARKERS",
        "_SKILL_INSTALL_ACTION_MARKERS",
        "_SKILL_DISCOVERY_SEARCH_ACTION_MARKERS",
        "_SKILL_DISCOVERY_TOOL_MARKERS",
        "_CODE_FILE_REFERENCE_RE",
        "_CODE_OR_FILE_REFERENCE_RE",
        "_marker_matches",
        "_matched_markers",
        "_skill_discovery_hits",
        "_skill_install_hits",
        "_skill_discovery_preferred_tool",
        "_skill_discovery_should_prefer_search",
        "_active_skill_execution_hits",
        "_active_skill_task_execution_hits",
    )

    for symbol_name in symbol_names:
        assert getattr(policy_markers, symbol_name) is getattr(policy_skill_markers, symbol_name)


def test_skill_marker_matching_keeps_english_boundaries_and_whitespace():
    assert policy_markers._marker_matches("please use skill now", "skill") is True
    assert policy_markers._marker_matches("please use   skill now", "use skill") is True
    assert policy_markers._marker_matches("skillfully written", "skill") is False
    assert policy_markers._marker_matches("skill_searching", "skill") is False


def test_skill_marker_detection_ignores_code_references_but_handles_explicit_tools():
    code_reference = "分析 src/focus_agent/engine/graph/policy.py 的 skill 逻辑"

    assert policy_markers._skill_discovery_hits(code_reference) == ()
    assert policy_markers._skill_install_hits(code_reference) == ()
    assert policy_markers._skill_discovery_hits("skills_search for release readiness skills") == (
        "skills_search",
        "skills",
    )
    assert (
        policy_markers._skill_discovery_preferred_tool(
            "Use skills_search, then skill_view for release-readiness."
        )
        == "skills_search"
    )


def test_skill_marker_execution_does_not_override_explicit_discovery_tool():
    execution_text = "请使用 stocks skill 查询当前股票行情"

    assert policy_markers._active_skill_execution_hits(execution_text) == (
        "使用",
        "skill",
        "查询",
    )
    assert policy_markers._active_skill_task_execution_hits(execution_text) == ("查询",)
    assert policy_markers._active_skill_execution_hits("使用 skills_search 查询 skill") == ()
    assert policy_markers._active_skill_task_execution_hits("使用 skills_search 查询 skill") == ()


def test_policy_uses_extracted_skill_markers_for_tool_intent_behavior():
    discovery_plan = policy.build_tool_intent_plan(
        "帮我查一下项目里有没有 release readiness 相关 skill"
    )
    install_plan = policy.build_tool_intent_plan("stock-analyzer，想办法安装这个skill。")

    assert discovery_plan.preferred_first_tool == "skills_search"
    assert discovery_plan.allowed_toolsets == ["skill"]
    assert "skill_discovery_signal" in discovery_plan.reason_codes
    assert install_plan.preferred_first_tool == "skills_search"
    assert install_plan.preferred_first_args == {"query": "stock-analyzer", "scope": "all"}
    assert "skill_install_intent" in install_plan.reason_codes
