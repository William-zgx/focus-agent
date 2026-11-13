from .support import (
    BranchActionBranchService,
    BranchRecommendationGraph,
    ConcurrentTurnError,
    HumanMessage,
    MultiThreadBranchActionGraph,
    Path,
    Settings,
    SimpleNamespace,
    SQLiteBranchRepository,
    StaleBranchRecommendationGraph,
    _branch_recommendation_service,
    _repo_with_child_branch,
    pytest,
)


def test_send_message_pre_turn_recommendation_answers_first_then_attaches_child_card(
    chat_service_factory,
    tmp_path: Path,
):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")
    settings = Settings(
        agent_branch_recommendation_enabled=True,
        agent_branch_recommendation_mode="suggest",
    )
    graph = BranchRecommendationGraph(
        {"messages": [HumanMessage(content="我们在规划包车东线时间段分配。")]}
    )
    runtime = SimpleNamespace(
        settings=settings,
        graph=graph,
        repo=repo,
        branch_decision_service=_branch_recommendation_service(settings, graph),
    )
    chat = chat_service_factory(runtime)

    payload = chat.send_message(
        thread_id="root-1",
        user_id="owner-1",
        message="单独深入细化一下下午东线每个时间段的安排。",
    )

    assert graph.invoke_calls == 1
    assert payload["assistant_message"] == "normal answer"
    assert [message.content for message in graph.values["messages"]][-2:] == [
        "单独深入细化一下下午东线每个时间段的安排。",
        "normal answer",
    ]
    assert payload["branch_actions"][0]["kind"] == "fork_child_branch"
    assert payload["branch_actions"][0]["status"] == "pending"
    assert payload["branch_actions"][0]["delivery"] == "after_answer"
    assert payload["branch_actions"][0]["target_parent_thread_id"] == "root-1"
    assert payload["branch_actions"][0]["source"] == "branch_decision"
    assert payload["branch_actions"][0]["handoff_message"] == "深入细化一下下午东线每个时间段的安排"
    assert payload["branch_decision_summary"]["latest_decision"]["status"] == "promoted"
    assert (
        payload["branch_decision_summary"]["latest_decision"]["metadata"][
            "recommendation_user_visible"
        ]
        is True
    )
    assert (
        payload["branch_decision_summary"]["latest_decision"]["recommendation_target"]
        == "fork_child_branch"
    )
    assert payload["branch_decision_summary"]["latest_decision"]["metadata"]["delivery"] == (
        "after_answer"
    )


def test_send_message_pre_turn_recommendation_survives_stale_checkpoint_read(
    chat_service_factory,
    tmp_path: Path,
):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")
    settings = Settings(
        agent_branch_recommendation_enabled=True,
        agent_branch_recommendation_mode="suggest",
    )
    graph = StaleBranchRecommendationGraph(
        {"messages": [HumanMessage(content="我们在规划包车东线时间段分配。")]}
    )
    runtime = SimpleNamespace(
        settings=settings,
        graph=graph,
        repo=repo,
        branch_decision_service=_branch_recommendation_service(settings, graph),
    )
    chat = chat_service_factory(runtime)

    payload = chat.send_message(
        thread_id="root-1",
        user_id="owner-1",
        message="New branch for the east-route afternoon schedule details.",
    )

    assert graph.invoke_calls == 0
    assert payload["branch_actions"][0]["source"] == "branch_decision"
    assert payload["branch_actions"][0]["status"] == "pending"
    assert payload["branch_actions"][0]["delivery"] == "proposal"
    assert (
        graph.values["branch_actions"][0]["action_id"] == payload["branch_actions"][0]["action_id"]
    )
    assert "branch switch confirmation" in payload["assistant_message"]
    assert "branch_actions" in graph.updates[-1][0]
    assert "messages" in graph.updates[-1][0]


def test_send_message_pre_turn_recommendation_uses_thread_turn_lock(
    chat_service_factory, tmp_path: Path
):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")
    settings = Settings(
        agent_branch_recommendation_enabled=True,
        agent_branch_recommendation_mode="suggest",
    )
    graph = BranchRecommendationGraph(
        {"messages": [HumanMessage(content="我们在规划包车东线时间段分配。")]}
    )
    runtime = SimpleNamespace(
        settings=settings,
        graph=graph,
        repo=repo,
        branch_decision_service=_branch_recommendation_service(settings, graph),
    )
    chat = chat_service_factory(runtime)

    chat._acquire_thread_turn(thread_id="root-1")
    try:
        with pytest.raises(ConcurrentTurnError, match="still processing the previous turn"):
            chat.send_message(
                thread_id="root-1",
                user_id="owner-1",
                message="单独深入细化一下下午东线每个时间段的安排。",
            )
    finally:
        chat._release_thread_turn(thread_id="root-1")

    assert graph.invoke_calls == 0
    assert "branch_actions" not in graph.values


def test_send_message_pre_turn_recommendation_creates_sibling_card_from_child(
    chat_service_factory,
    tmp_path: Path,
):
    repo = _repo_with_child_branch(tmp_path)
    settings = Settings(
        agent_branch_recommendation_enabled=True,
        agent_branch_recommendation_mode="suggest",
    )
    graph = BranchRecommendationGraph(
        {
            "messages": [HumanMessage(content="当前分支在研究方案 A。")],
            "branch_meta": {
                "branch_id": "branch-1",
                "root_thread_id": "root-1",
                "parent_thread_id": "root-1",
                "return_thread_id": "root-1",
                "branch_name": "方案 A",
                "branch_role": "deep_dive",
                "branch_depth": 1,
                "branch_status": "active",
            },
        }
    )
    runtime = SimpleNamespace(
        settings=settings,
        graph=graph,
        repo=repo,
        branch_decision_service=_branch_recommendation_service(settings, graph),
    )
    chat = chat_service_factory(runtime)

    payload = chat.send_message(
        thread_id="child-1",
        user_id="owner-1",
        message="换个方向并行探索东线备用方案。",
    )

    assert graph.invoke_calls == 1
    assert payload["assistant_message"] == "normal answer"
    assert payload["branch_actions"][0]["delivery"] == "after_answer"
    assert payload["branch_actions"][0]["kind"] == "fork_sibling_branch"
    assert payload["branch_actions"][0]["target_parent_thread_id"] == "root-1"
    assert (
        payload["branch_decision_summary"]["latest_decision"]["recommendation_target"]
        == "fork_sibling_branch"
    )


def test_pre_turn_recommendation_execution_carries_question_to_sibling_branch(
    chat_service_factory,
    tmp_path: Path,
):
    repo = _repo_with_child_branch(tmp_path)
    settings = Settings(
        agent_branch_recommendation_enabled=True,
        agent_branch_recommendation_mode="suggest",
    )
    graph = MultiThreadBranchActionGraph(
        {
            "root-1": {
                "messages": [HumanMessage(content="根线程里的基础上下文。")],
            },
            "child-1": {
                "messages": [HumanMessage(content="当前分支在研究方案 A。")],
                "branch_meta": {
                    "branch_id": "branch-1",
                    "root_thread_id": "root-1",
                    "parent_thread_id": "root-1",
                    "return_thread_id": "root-1",
                    "branch_name": "方案 A",
                    "branch_role": "deep_dive",
                    "branch_depth": 1,
                    "branch_status": "active",
                },
            },
        }
    )
    branch_service = BranchActionBranchService()
    runtime = SimpleNamespace(
        settings=settings,
        graph=graph,
        repo=repo,
        branch_service=branch_service,
        branch_decision_service=_branch_recommendation_service(settings, graph),
    )
    chat = chat_service_factory(runtime)

    message = "换个方向并行探索东线备用方案。"
    chat.send_message(thread_id="child-1", user_id="owner-1", message=message)
    action_id = graph.values_by_thread["child-1"]["branch_actions"][0]["action_id"]

    chat.execute_branch_action(thread_id="child-1", action_id=action_id, user_id="owner-1")

    assert branch_service.fork_calls[-1]["parent_thread_id"] == "root-1"
    child_messages = graph.values_by_thread["child-new"]["messages"]
    assert any(
        isinstance(item, HumanMessage) and item.content == "并行探索东线备用方案"
        for item in child_messages
    )


def test_pre_turn_execute_mode_audit_action_rejects_user_actions(
    chat_service_factory, tmp_path: Path
):
    repo = _repo_with_child_branch(tmp_path)
    settings = Settings(
        agent_branch_recommendation_enabled=True,
        agent_branch_recommendation_mode="execute",
    )
    graph = MultiThreadBranchActionGraph(
        {
            "root-1": {"messages": [HumanMessage(content="根线程里的基础上下文。")]},
            "child-1": {
                "messages": [HumanMessage(content="当前分支在研究方案 A。")],
                "branch_meta": {
                    "branch_id": "branch-1",
                    "root_thread_id": "root-1",
                    "parent_thread_id": "root-1",
                    "return_thread_id": "root-1",
                    "branch_name": "方案 A",
                    "branch_role": "deep_dive",
                    "branch_depth": 1,
                    "branch_status": "active",
                },
            },
        }
    )
    branch_service = BranchActionBranchService()
    runtime = SimpleNamespace(
        settings=settings,
        graph=graph,
        repo=repo,
        branch_service=branch_service,
        branch_decision_service=_branch_recommendation_service(settings, graph),
    )
    chat = chat_service_factory(runtime)

    chat.send_message(
        thread_id="child-1",
        user_id="owner-1",
        message="换个方向并行探索东线备用方案。",
    )
    action = graph.values_by_thread["child-1"]["branch_actions"][0]

    assert action["recommendation_user_visible"] is False
    with pytest.raises(ValueError, match="audit-only"):
        chat.execute_branch_action(
            thread_id="child-1",
            action_id=action["action_id"],
            user_id="owner-1",
        )
    with pytest.raises(ValueError, match="audit-only"):
        chat.dismiss_branch_action(
            thread_id="child-1",
            action_id=action["action_id"],
            user_id="owner-1",
        )
    assert branch_service.fork_calls == []


def test_send_message_pre_turn_continue_recommendation_invokes_normally(
    chat_service_factory, tmp_path: Path
):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")
    settings = Settings(
        agent_branch_recommendation_enabled=True,
        agent_branch_recommendation_mode="suggest",
    )
    graph = BranchRecommendationGraph(
        {"messages": [HumanMessage(content="我们正在讨论主线问题。")]}
    )
    runtime = SimpleNamespace(
        settings=settings,
        graph=graph,
        repo=repo,
        branch_decision_service=_branch_recommendation_service(settings, graph),
    )
    chat = chat_service_factory(runtime)

    payload = chat.send_message(
        thread_id="root-1",
        user_id="owner-1",
        message="不用分支，继续回答这个问题。",
    )

    assert graph.invoke_calls == 1
    assert payload["branch_actions"] == []
    assert payload["assistant_message"] == "normal answer"


def test_send_message_pre_turn_shadow_recommendation_audits_without_card(
    chat_service_factory, tmp_path: Path
):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")
    settings = Settings(
        agent_branch_recommendation_enabled=True,
        agent_branch_recommendation_mode="shadow",
    )
    graph = BranchRecommendationGraph(
        {"messages": [HumanMessage(content="我们正在讨论主线问题。")]}
    )
    runtime = SimpleNamespace(
        settings=settings,
        graph=graph,
        repo=repo,
        branch_decision_service=_branch_recommendation_service(settings, graph),
    )
    chat = chat_service_factory(runtime)

    payload = chat.send_message(
        thread_id="root-1",
        user_id="owner-1",
        message="换个主题，先看另一个问题：酒店取消政策怎么处理？",
    )

    latest = payload["branch_decision_summary"]["latest_decision"]
    assert graph.invoke_calls == 1
    assert payload["branch_actions"] == []
    assert payload["assistant_message"] == "normal answer"
    assert latest["status"] == "shadowed"
    assert latest["recommendation_target"] == "fork_child_branch"
    assert latest["metadata"]["reason"] == "shadow_mode"
    assert latest["metadata"]["recommendation_user_visible"] is False
