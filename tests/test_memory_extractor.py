from __future__ import annotations

from langchain.messages import AIMessage, HumanMessage

from focus_agent.core.request_context import RequestContext
from focus_agent.core.types import FindingItem
from focus_agent.memory.extractor import MemoryExtractor
from focus_agent.memory.models import MemoryKind


def _context(**overrides: str) -> RequestContext:
    defaults = {
        "user_id": "user-1",
        "root_thread_id": "thread-1",
    }
    defaults.update(overrides)
    return RequestContext(**defaults)


def _kinds(result) -> list[MemoryKind]:
    return [record.kind for record in result.records]


def test_extracts_stable_user_profile_but_not_current_task_statement():
    extractor = MemoryExtractor()

    profile_result = extractor.extract_from_turn(
        context=_context(),
        state={"messages": [HumanMessage(content="我是 Go 后端工程师，不熟 React。")]},
    )
    task_result = extractor.extract_from_turn(
        context=_context(),
        state={"messages": [HumanMessage(content="我在做 memory extractor/write policy 的边界收紧。")]},
    )

    assert _kinds(profile_result) == [MemoryKind.USER_PROFILE]
    assert MemoryKind.USER_PROFILE not in _kinds(task_result)


def test_extracts_only_standalone_user_preferences():
    extractor = MemoryExtractor()

    preference_result = extractor.extract_from_turn(
        context=_context(),
        state={"messages": [HumanMessage(content="回答里不要使用 emoji。")]},
    )
    task_result = extractor.extract_from_turn(
        context=_context(),
        state={"messages": [HumanMessage(content="帮我用中文总结这个 PR。")]},
    )

    assert _kinds(preference_result) == [MemoryKind.USER_PREFERENCE]
    assert MemoryKind.USER_PREFERENCE not in _kinds(task_result)


def test_does_not_promote_pinned_facts_into_user_memory():
    extractor = MemoryExtractor()

    result = extractor.extract_from_turn(
        context=_context(),
        state={
            "messages": [HumanMessage(content="继续。")],
            "pinned_facts": [{"fact": "先只改 extractor，不要动 graph_builder", "source": "user"}],
        },
    )

    assert result.records == []


def test_project_fact_requires_durable_project_rule():
    extractor = MemoryExtractor()

    durable_result = extractor.extract_from_turn(
        context=_context(project_id="proj-1"),
        state={"active_goal": "默认输出语言是中文。"},
    )
    task_result = extractor.extract_from_turn(
        context=_context(project_id="proj-1"),
        state={"active_goal": "修复 owner 字段丢失"},
    )

    assert MemoryKind.PROJECT_FACT in _kinds(durable_result)
    assert MemoryKind.PROJECT_FACT not in _kinds(task_result)


def test_turn_summary_filters_ack_noise_but_keeps_substantive_episode():
    extractor = MemoryExtractor()

    noise_result = extractor.extract_from_turn(
        context=_context(),
        state={"messages": [HumanMessage(content="继续。"), AIMessage(content="好的。")]},
    )
    substantive_result = extractor.extract_from_turn(
        context=_context(),
        state={
            "messages": [
                HumanMessage(content="修复 owner 首次加载丢失"),
                AIMessage(content="已定位到缓存初始化竞态，并补了回归测试。"),
            ]
        },
    )

    assert noise_result.records == []
    assert _kinds(substantive_result) == [MemoryKind.TURN_SUMMARY]
    assert substantive_result.records[0].content == (
        "User: 修复 owner 首次加载丢失 Assistant: 已定位到缓存初始化竞态，并补了回归测试。"
    )


def test_branch_findings_only_come_from_branch_local_findings():
    extractor = MemoryExtractor()

    inferred_from_ai = extractor.extract_from_turn(
        context=_context(branch_id="branch-1"),
        state={"messages": [AIMessage(content="发现 owner 字段首次加载会丢失。")]},
    )
    explicit_branch_finding = extractor.extract_from_turn(
        context=_context(branch_id="branch-1"),
        state={
            "messages": [AIMessage(content="发现 owner 字段首次加载会丢失。")],
            "branch_local_findings": [
                FindingItem(finding="owner 字段首次加载会丢失", evidence_refs=["note-1"], confidence=0.9)
            ],
        },
    )

    assert MemoryKind.BRANCH_FINDING not in _kinds(inferred_from_ai)
    assert _kinds(explicit_branch_finding) == [MemoryKind.BRANCH_FINDING, MemoryKind.TURN_SUMMARY]
    assert explicit_branch_finding.records[0].content == "owner 字段首次加载会丢失"
    assert explicit_branch_finding.records[0].evidence_refs == ["note-1"]
