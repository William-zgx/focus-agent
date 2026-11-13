from .support import (
    AIMessage,
    BranchActionGraph,
    BranchActionKind,
    BranchActionNavigation,
    BranchMeta,
    BranchRole,
    BranchStatus,
    ChatServicePorts,
    HumanMessage,
    RequestContext,
    Settings,
    SimpleNamespace,
    branch_action_intent,
    branch_handoff_message_from_text,
    build_branch_action_proposal,
    infer_suggested_branch_name,
    is_branch_action_dismissal,
    is_branch_action_request,
    mark_branch_action_executed,
    pytest,
)


def test_branch_thread_state_hides_copied_branch_creation_turn(
    chat_service_factory,
):
    action = build_branch_action_proposal(
        kind=BranchActionKind.FORK_CHILD_BRANCH,
        root_thread_id="root-1",
        source_thread_id="parent-1",
        target_parent_thread_id="parent-1",
        suggested_branch_name="备用方案",
        reason="User requested a branch switch from chat.",
    )
    executed = mark_branch_action_executed(
        action,
        navigation=BranchActionNavigation(root_thread_id="root-1", thread_id="child-new"),
    )
    graph = BranchActionGraph(
        {
            "branch_meta": {
                "branch_id": "branch-new",
                "root_thread_id": "root-1",
                "parent_thread_id": "parent-1",
                "return_thread_id": "parent-1",
                "branch_name": "备用方案",
                "branch_role": "deep_dive",
                "branch_depth": 2,
                "branch_status": "active",
                "branch_fork_message_count": 3,
            },
            "messages": [
                HumanMessage(content="原始上下文。"),
                HumanMessage(content="新建分支，探索一下备用方案。"),
                AIMessage(content="我已准备好分支切换确认项：创建子分支「备用方案」。"),
                HumanMessage(content="备用方案要先看雨天安排。"),
                AIMessage(content="雨天安排可以先预留室内活动。"),
            ],
            "branch_actions": [executed.model_dump(mode="json")],
        }
    )
    chat = chat_service_factory(
        ChatServicePorts(settings=Settings(), graph=graph, repo=SimpleNamespace())
    )

    payload = chat._response_payload(
        thread_id="child-new",
        user_id="owner-1",
        context=RequestContext(
            user_id="owner-1",
            root_thread_id="root-1",
            branch_id="branch-new",
            parent_thread_id="parent-1",
        ),
        branch_meta=BranchMeta(
            branch_id="branch-new",
            root_thread_id="root-1",
            parent_thread_id="parent-1",
            return_thread_id="parent-1",
            branch_name="备用方案",
            branch_role=BranchRole.DEEP_DIVE,
            branch_depth=2,
            branch_status=BranchStatus.ACTIVE,
        ),
        interrupts=[],
    )

    assert [message["content"] for message in payload["messages"]] == [
        "原始上下文。",
        "备用方案要先看雨天安排。",
        "雨天安排可以先预留室内活动。",
    ]
    assert payload["assistant_message"] == "雨天安排可以先预留室内活动。"
    assert payload["branch_actions"] == []


def test_branch_thread_state_hides_copied_recommendation_handoff_after_auto_run(
    chat_service_factory,
):
    handoff = "new topic tokyo disneyland family budget for october 2026"
    graph = BranchActionGraph(
        {
            "branch_meta": {
                "branch_id": "branch-new",
                "root_thread_id": "root-1",
                "parent_thread_id": "parent-1",
                "return_thread_id": "parent-1",
                "branch_name": "Tokyo Disneyland",
                "branch_role": "explore_alternatives",
                "branch_depth": 2,
                "branch_status": "active",
                "branch_fork_message_count": 3,
            },
            "messages": [
                HumanMessage(content="Jeju October trip context."),
                HumanMessage(content=handoff),
                AIMessage(
                    content=(
                        "I prepared a branch switch confirmation: create a new "
                        "sibling branch “Tokyo Disneyland”. Confirm it in the card, "
                        "or reply “go ahead”."
                    )
                ),
                HumanMessage(content=handoff),
                AIMessage(content="Tokyo Disneyland needs a separate October budget."),
            ],
            "branch_actions": [
                build_branch_action_proposal(
                    kind=BranchActionKind.FORK_SIBLING_BRANCH,
                    root_thread_id="root-1",
                    source_thread_id="parent-1",
                    target_parent_thread_id="root-1",
                    suggested_branch_name="Tokyo Disneyland",
                    reason="topic shift",
                    handoff_message=handoff,
                ).model_dump(mode="json")
            ],
        }
    )
    chat = chat_service_factory(
        ChatServicePorts(settings=Settings(), graph=graph, repo=SimpleNamespace())
    )

    payload = chat._response_payload(
        thread_id="child-new",
        user_id="owner-1",
        context=RequestContext(
            user_id="owner-1",
            root_thread_id="root-1",
            branch_id="branch-new",
            parent_thread_id="parent-1",
        ),
        branch_meta=BranchMeta(
            branch_id="branch-new",
            root_thread_id="root-1",
            parent_thread_id="parent-1",
            return_thread_id="parent-1",
            branch_name="Tokyo Disneyland",
            branch_role=BranchRole.EXPLORE_ALTERNATIVES,
            branch_depth=2,
            branch_status=BranchStatus.ACTIVE,
        ),
        interrupts=[],
    )

    assert [message["content"] for message in payload["messages"]] == [
        "Jeju October trip context.",
        handoff,
        "Tokyo Disneyland needs a separate October budget.",
    ]
    assert payload["branch_actions"] == []


def test_branch_thread_state_hides_copied_terminal_handoff_after_auto_run(
    chat_service_factory,
):
    handoff = "大阪环球影城十月亲子预算怎么安排？"
    graph = BranchActionGraph(
        {
            "branch_meta": {
                "branch_id": "branch-new",
                "root_thread_id": "root-1",
                "parent_thread_id": "parent-1",
                "return_thread_id": "parent-1",
                "branch_name": "USJ budget",
                "branch_role": "explore_alternatives",
                "branch_depth": 2,
                "branch_status": "active",
                "branch_fork_message_count": 2,
            },
            "messages": [
                HumanMessage(content="Jeju October trip context."),
                HumanMessage(content=handoff),
                HumanMessage(content=handoff),
                AIMessage(content="USJ October budget belongs in this branch."),
            ],
            "branch_actions": [
                build_branch_action_proposal(
                    kind=BranchActionKind.FORK_SIBLING_BRANCH,
                    root_thread_id="root-1",
                    source_thread_id="parent-1",
                    target_parent_thread_id="root-1",
                    suggested_branch_name="USJ budget",
                    reason="topic shift",
                    handoff_message=handoff,
                ).model_dump(mode="json")
            ],
        }
    )
    chat = chat_service_factory(
        ChatServicePorts(settings=Settings(), graph=graph, repo=SimpleNamespace())
    )

    payload = chat._response_payload(
        thread_id="child-new",
        user_id="owner-1",
        context=RequestContext(
            user_id="owner-1",
            root_thread_id="root-1",
            branch_id="branch-new",
            parent_thread_id="parent-1",
        ),
        branch_meta=BranchMeta(
            branch_id="branch-new",
            root_thread_id="root-1",
            parent_thread_id="parent-1",
            return_thread_id="parent-1",
            branch_name="USJ budget",
            branch_role=BranchRole.EXPLORE_ALTERNATIVES,
            branch_depth=2,
            branch_status=BranchStatus.ACTIVE,
        ),
        interrupts=[],
    )

    assert [message["content"] for message in payload["messages"]] == [
        "Jeju October trip context.",
        handoff,
        "USJ October budget belongs in this branch.",
    ]
    assert payload["branch_actions"] == []


def test_branch_thread_state_hides_local_duplicate_handoff_before_answer(
    chat_service_factory,
):
    handoff = "大阪环球影城十月亲子预算，20字以内"
    graph = BranchActionGraph(
        {
            "branch_meta": {
                "branch_id": "branch-new",
                "root_thread_id": "root-1",
                "parent_thread_id": "parent-1",
                "return_thread_id": "parent-1",
                "branch_name": "USJ budget",
                "branch_role": "explore_alternatives",
                "branch_depth": 2,
                "branch_status": "active",
                "branch_fork_message_count": 1,
            },
            "messages": [
                HumanMessage(content="Jeju October trip context."),
                HumanMessage(content=handoff),
                HumanMessage(content=handoff),
                AIMessage(content="USJ October budget belongs in this branch."),
            ],
            "branch_actions": [],
        }
    )
    chat = chat_service_factory(
        ChatServicePorts(settings=Settings(), graph=graph, repo=SimpleNamespace())
    )

    payload = chat._response_payload(
        thread_id="child-new",
        user_id="owner-1",
        context=RequestContext(
            user_id="owner-1",
            root_thread_id="root-1",
            branch_id="branch-new",
            parent_thread_id="parent-1",
        ),
        branch_meta=BranchMeta(
            branch_id="branch-new",
            root_thread_id="root-1",
            parent_thread_id="parent-1",
            return_thread_id="parent-1",
            branch_name="USJ budget",
            branch_role=BranchRole.EXPLORE_ALTERNATIVES,
            branch_depth=2,
            branch_status=BranchStatus.ACTIVE,
        ),
        interrupts=[],
    )

    assert [message["content"] for message in payload["messages"]] == [
        "Jeju October trip context.",
        handoff,
        "USJ October budget belongs in this branch.",
    ]


def test_branch_thread_state_does_not_drop_messages_when_fork_count_is_stale(
    chat_service_factory,
):
    graph = BranchActionGraph(
        {
            "branch_meta": {
                "branch_id": "branch-new",
                "root_thread_id": "root-1",
                "parent_thread_id": "parent-1",
                "return_thread_id": "parent-1",
                "branch_name": "备用方案",
                "branch_role": "deep_dive",
                "branch_depth": 2,
                "branch_status": "active",
                "branch_fork_message_count": 99,
            },
            "messages": [
                HumanMessage(content="备用方案要先看雨天安排。"),
                AIMessage(content="雨天安排可以先预留室内活动。"),
            ],
        }
    )
    chat = chat_service_factory(
        ChatServicePorts(settings=Settings(), graph=graph, repo=SimpleNamespace())
    )

    payload = chat._response_payload(
        thread_id="child-new",
        user_id="owner-1",
        context=RequestContext(
            user_id="owner-1",
            root_thread_id="root-1",
            branch_id="branch-new",
            parent_thread_id="parent-1",
        ),
        branch_meta=BranchMeta(
            branch_id="branch-new",
            root_thread_id="root-1",
            parent_thread_id="parent-1",
            return_thread_id="parent-1",
            branch_name="备用方案",
            branch_role=BranchRole.DEEP_DIVE,
            branch_depth=2,
            branch_status=BranchStatus.ACTIVE,
        ),
        interrupts=[],
    )

    assert [message["content"] for message in payload["messages"]] == [
        "备用方案要先看雨天安排。",
        "雨天安排可以先预留室内活动。",
    ]
    assert payload["assistant_message"] == "雨天安排可以先预留室内活动。"


def test_branch_action_intent_requires_branch_context():
    assert is_branch_action_request("帮我切换一个同级分支吧。")
    assert is_branch_action_request("Create a sibling branch for this idea.")
    assert not is_branch_action_request("帮我切换一下模型。")
    assert not is_branch_action_request("切换到深度思考模式。")


def test_branch_action_dismissal_does_not_match_no_inside_words():
    pending = build_branch_action_proposal(
        kind=BranchActionKind.FORK_CHILD_BRANCH,
        root_thread_id="root-1",
        source_thread_id="thread-1",
        target_parent_thread_id="thread-1",
        suggested_branch_name="Candidate",
        reason="User requested a branch switch from chat.",
    )
    message = "QA_STEP_4_NORMAL_REPLY: 请直接回答。不要创建分支。"

    assert not is_branch_action_dismissal(message)
    assert not is_branch_action_request(message)
    assert (
        branch_action_intent(
            values={"branch_actions": [pending.model_dump(mode="json")]},
            message=message,
        )
        is None
    )
    assert is_branch_action_dismissal("no")
    assert is_branch_action_dismissal("No, thanks")


def test_branch_handoff_strips_title_clause_from_current_thread_continuation():
    message = "请创建一个子分支，标题叫 Negated Pending QA，用于单独探索浏览器测试。"

    assert infer_suggested_branch_name(message, []) == "Negated Pending QA"
    assert branch_handoff_message_from_text(message) == "探索浏览器测试"


def test_branch_handoff_strips_english_title_clause_from_current_thread_continuation():
    message = (
        "Create a child branch titled Browser Branch QA to separately explore "
        "browser testing. Do not answer yet; show a confirmable branch action."
    )

    assert infer_suggested_branch_name(message, []) == "Browser Branch QA"
    assert branch_handoff_message_from_text(message) == "separately explore browser testing"


@pytest.mark.parametrize(
    ("message", "expected_name", "expected_handoff"),
    [
        (
            "Create a child branch titled Research and QA to compare options.",
            "Research and QA",
            "compare options",
        ),
        (
            "Create a child branch titled API to REST migration to evaluate plan.",
            "API to REST migration",
            "evaluate plan",
        ),
        (
            "Create a child branch called Plan for Mobile QA to review risk.",
            "Plan for Mobile QA",
            "review risk",
        ),
    ],
)
def test_branch_handoff_preserves_english_title_connectors(
    message: str,
    expected_name: str,
    expected_handoff: str,
):
    assert infer_suggested_branch_name(message, []) == expected_name
    assert branch_handoff_message_from_text(message) == expected_handoff
