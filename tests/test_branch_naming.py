from langchain.messages import AIMessage, HumanMessage

from focus_agent.services.branches import BranchService
from focus_agent.core.branching import BranchRole


def test_initial_branch_name_defaults_to_new_branch_without_model_invoke():
    service = object.__new__(BranchService)
    service.proposal_model = None

    branch_name = service._resolve_initial_branch_name(
        preferred_name=None,
        parent_values={
            "messages": [HumanMessage(content="Please investigate why tool calls keep retrying on the import flow.")],
            "rolling_summary": "",
        },
        name_source="Focus on the import retry bug",
        branch_role=BranchRole.EXPLORE_ALTERNATIVES,
    )

    assert branch_name == "New Branch"


def test_branch_name_preserves_explicit_preferred_name_after_sanitizing():
    service = object.__new__(BranchService)
    service.proposal_model = None

    branch_name = service._resolve_initial_branch_name(
        preferred_name='  "Retry Loop Hotfix"  ',
        parent_values={},
        name_source=None,
        branch_role=BranchRole.DEEP_DIVE,
    )

    assert branch_name == "Retry Loop Hotfix"


def test_ai_branch_name_is_generated_from_child_branch_conversation():
    service = object.__new__(BranchService)

    class FakeModel:
        def __init__(self):
            self.seen_messages = None

        def invoke(self, messages):
            self.seen_messages = messages
            return "快速排序方案"

    fake_model = FakeModel()
    service.proposal_model = fake_model

    branch_name = service._resolve_branch_name(
        preferred_name=None,
        thread_values={
            "messages": [
                HumanMessage(content="帮我写一个 C 语言版本的快速排序。"),
                AIMessage(content="我先给你一个基础实现，再解释关键步骤。"),
            ],
            "rolling_summary": "用户在这个新分支里继续追问 C 语言快速排序实现。",
        },
        branch_role=BranchRole.DEEP_DIVE,
    )

    assert branch_name == "快速排序方案"
    assert fake_model.seen_messages is not None
    assert "Use Chinese to match the conversation language." in fake_model.seen_messages[0].content
    assert "最近对话" in fake_model.seen_messages[1].content
    assert "快速排序" in fake_model.seen_messages[1].content


def test_fallback_branch_name_uses_chinese_role_name_for_chinese_session():
    assert BranchService._fallback_branch_name("", BranchRole.VERIFY, language="zh") == "验证"
