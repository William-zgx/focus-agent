from .support import (
    AIMessage,
    BranchActionBranchService,
    BranchActionGraph,
    ConcurrentTurnError,
    CoordinationBackend,
    HumanMessage,
    InMemoryBackgroundJobDeduperBackend,
    InMemoryRateLimitBackend,
    MultiThreadBranchActionGraph,
    Path,
    Settings,
    SettingsOverlay,
    SimpleNamespace,
    _repo_with_child_branch,
    pytest,
    time,
)


def test_send_message_creates_pending_branch_action_without_forking(
    chat_service_factory, tmp_path: Path
):
    repo = _repo_with_child_branch(tmp_path)
    graph = BranchActionGraph(
        {
            "messages": [
                HumanMessage(content="你觉得华英农业下周会是什么样的走势呀？"),
                AIMessage(content="这需要切换分支后再分析。"),
            ]
        }
    )
    branch_service = BranchActionBranchService()
    runtime = SimpleNamespace(
        settings=Settings(),
        graph=graph,
        repo=repo,
        branch_service=branch_service,
    )
    chat = chat_service_factory(runtime)

    payload = chat.send_message(
        thread_id="child-1",
        user_id="owner-1",
        message="是的，帮我切换一个同级分支吧。",
    )

    assert branch_service.fork_calls == []
    assert payload["branch_actions"][0]["kind"] == "fork_sibling_branch"
    assert payload["branch_actions"][0]["status"] == "pending"
    assert payload["branch_actions"][0]["target_parent_thread_id"] == "root-1"
    assert (
        payload["branch_actions"][0]["handoff_message"] == "你觉得华英农业下周会是什么样的走势呀？"
    )
    assert "华英农业" in payload["branch_actions"][0]["suggested_branch_name"]
    assert "已创建" not in payload["assistant_message"]
    assert graph.updates[-1][1] == "bootstrap_turn"


def test_send_message_defaults_generic_new_branch_to_child_branch(
    chat_service_factory, tmp_path: Path
):
    repo = _repo_with_child_branch(tmp_path)
    graph = BranchActionGraph(
        {
            "messages": [
                HumanMessage(content="我们正在讨论包车东线时间段分配。"),
            ]
        }
    )
    runtime = SimpleNamespace(
        settings=Settings(),
        graph=graph,
        repo=repo,
        branch_service=BranchActionBranchService(),
    )
    chat = chat_service_factory(runtime)

    payload = chat.send_message(
        thread_id="child-1",
        user_id="owner-1",
        message="新建分支，探索一下今天包车东线的时间段分配。",
    )

    assert payload["branch_actions"][0]["kind"] == "fork_child_branch"
    assert payload["branch_actions"][0]["target_parent_thread_id"] == "child-1"
    assert payload["branch_actions"][0]["handoff_message"] == "探索一下今天包车东线的时间段分配"


def test_branch_action_execution_keeps_auto_name_pending_for_first_turn_refresh(
    chat_service_factory, tmp_path: Path
):
    repo = _repo_with_child_branch(tmp_path)
    graph = BranchActionGraph(
        {
            "messages": [HumanMessage(content="你觉得华英农业下周会是什么样的走势呀？")],
        }
    )
    branch_service = BranchActionBranchService()
    runtime = SimpleNamespace(
        settings=Settings(),
        graph=graph,
        repo=repo,
        branch_service=branch_service,
    )
    chat = chat_service_factory(runtime)

    chat.send_message(thread_id="child-1", user_id="owner-1", message="帮我切换一个同级分支吧。")
    action_id = graph.values["branch_actions"][0]["action_id"]

    chat.execute_branch_action(thread_id="child-1", action_id=action_id, user_id="owner-1")

    assert branch_service.fork_calls[-1]["branch_name"] is None
    assert "华英农业" in branch_service.fork_calls[-1]["name_source"]


def test_branch_action_execution_uses_explicit_branch_title(chat_service_factory, tmp_path: Path):
    repo = _repo_with_child_branch(tmp_path)
    graph = BranchActionGraph({"messages": [HumanMessage(content="根线程里的基础上下文。")]})
    branch_service = BranchActionBranchService()
    runtime = SimpleNamespace(
        settings=Settings(),
        graph=graph,
        repo=repo,
        branch_service=branch_service,
    )
    chat = chat_service_factory(runtime)

    chat.send_message(
        thread_id="root-1",
        user_id="owner-1",
        message="请创建一个子分支，标题叫 Confirm Branch QA，用于研究分支确认跳转。",
    )
    action = graph.values["branch_actions"][0]

    assert action["suggested_branch_name"] == "Confirm Branch QA"
    assert action["suggested_branch_name_source"] == "explicit"

    chat.execute_branch_action(
        thread_id="root-1",
        action_id=action["action_id"],
        user_id="owner-1",
    )

    assert branch_service.fork_calls[-1]["branch_name"] == "Confirm Branch QA"
    assert branch_service.fork_calls[-1]["name_source"] == "Confirm Branch QA"


def test_branch_action_execution_carries_source_question_to_sibling_branch(
    chat_service_factory, tmp_path: Path
):
    repo = _repo_with_child_branch(tmp_path)
    graph = MultiThreadBranchActionGraph(
        {
            "root-1": {
                "messages": [HumanMessage(content="根线程里的基础上下文。")],
            },
            "child-1": {
                "messages": [
                    HumanMessage(content="你觉得华英农业下周会是什么样的走势呀？"),
                    AIMessage(content="这需要切换分支后再分析。"),
                ],
            },
        }
    )
    branch_service = BranchActionBranchService()
    runtime = SimpleNamespace(
        settings=Settings(),
        graph=graph,
        repo=repo,
        branch_service=branch_service,
    )
    chat = chat_service_factory(runtime)

    chat.send_message(thread_id="child-1", user_id="owner-1", message="帮我切换一个同级分支吧。")
    action_id = graph.values_by_thread["child-1"]["branch_actions"][0]["action_id"]

    chat.execute_branch_action(thread_id="child-1", action_id=action_id, user_id="owner-1")

    assert branch_service.fork_calls[-1]["parent_thread_id"] == "root-1"
    child_messages = graph.values_by_thread["child-new"]["messages"]
    assert any(
        isinstance(message, HumanMessage)
        and message.content == "你觉得华英农业下周会是什么样的走势呀？"
        for message in child_messages
    )


def test_branch_action_execution_carries_inline_question_to_child_branch(
    chat_service_factory, tmp_path: Path
):
    repo = _repo_with_child_branch(tmp_path)
    graph = MultiThreadBranchActionGraph(
        {
            "root-1": {
                "messages": [HumanMessage(content="主线正在规划济州岛旅行。")],
            },
        }
    )
    branch_service = BranchActionBranchService()
    runtime = SimpleNamespace(
        settings=Settings(),
        graph=graph,
        repo=repo,
        branch_service=branch_service,
    )
    chat = chat_service_factory(runtime)

    chat.send_message(
        thread_id="root-1",
        user_id="owner-1",
        message="新建子分支，帮我探索一下东门市场的具体情况。",
    )
    action_id = graph.values_by_thread["root-1"]["branch_actions"][0]["action_id"]

    chat.execute_branch_action(thread_id="root-1", action_id=action_id, user_id="owner-1")

    assert branch_service.fork_calls[-1]["parent_thread_id"] == "root-1"
    child_messages = graph.values_by_thread["child-new"]["messages"]
    assert any(
        isinstance(message, HumanMessage) and message.content == "探索一下东门市场的具体情况"
        for message in child_messages
    )


def test_branch_action_execution_marks_copied_child_action_executed(
    chat_service_factory, tmp_path: Path
):
    repo = _repo_with_child_branch(tmp_path)
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

    class CopyingBranchActionBranchService(BranchActionBranchService):
        def fork_branch(self, **kwargs):
            record = super().fork_branch(**kwargs)
            source_values = graph.values_by_thread["child-1"]
            graph.values_by_thread[record.child_thread_id] = {
                "messages": list(source_values.get("messages", [])),
                "branch_actions": [
                    dict(item) for item in list(source_values.get("branch_actions", []))
                ],
            }
            return record

    runtime = SimpleNamespace(
        settings=Settings(),
        graph=graph,
        repo=repo,
        branch_service=CopyingBranchActionBranchService(),
    )
    chat = chat_service_factory(runtime)

    chat.send_message(thread_id="child-1", user_id="owner-1", message="帮我切换一个同级分支吧。")
    action_id = graph.values_by_thread["child-1"]["branch_actions"][0]["action_id"]
    chat.execute_branch_action(thread_id="child-1", action_id=action_id, user_id="owner-1")

    child_actions = graph.values_by_thread["child-new"]["branch_actions"]
    assert child_actions[0]["action_id"] == action_id
    assert child_actions[0]["status"] == "executed"
    assert child_actions[0]["navigation"]["thread_id"] == "child-new"


def test_branch_action_execute_uses_thread_turn_lock(chat_service_factory, tmp_path: Path):
    repo = _repo_with_child_branch(tmp_path)
    graph = BranchActionGraph(
        {
            "messages": [HumanMessage(content="你觉得华英农业下周会是什么样的走势呀？")],
        }
    )
    runtime = SimpleNamespace(
        settings=Settings(),
        graph=graph,
        repo=repo,
        branch_service=BranchActionBranchService(),
    )
    chat = chat_service_factory(runtime)
    chat.send_message(thread_id="child-1", user_id="owner-1", message="帮我切换一个同级分支吧。")
    action_id = graph.values["branch_actions"][0]["action_id"]

    chat._acquire_thread_turn(thread_id="child-1")
    try:
        with pytest.raises(ConcurrentTurnError, match="still processing the previous turn"):
            chat.execute_branch_action(thread_id="child-1", action_id=action_id, user_id="owner-1")
    finally:
        chat._release_thread_turn(thread_id="child-1")


def test_branch_action_execute_heartbeats_thread_turn_lock(chat_service_factory, tmp_path: Path):
    repo = _repo_with_child_branch(tmp_path)
    graph = BranchActionGraph(
        {
            "messages": [HumanMessage(content="你觉得华英农业下周会是什么样的走势呀？")],
        }
    )

    class RecordingThreadLocks:
        def __init__(self):
            self.acquired: list[tuple[str, str, float]] = []
            self.heartbeats: list[tuple[str, str, float]] = []
            self.released: list[tuple[str, str]] = []

        def acquire_thread_turn(self, *, thread_id: str, owner: str, ttl_seconds: float) -> bool:
            self.acquired.append((thread_id, owner, ttl_seconds))
            return True

        def heartbeat_thread_turn(self, *, thread_id: str, owner: str, ttl_seconds: float) -> bool:
            self.heartbeats.append((thread_id, owner, ttl_seconds))
            return True

        def release_thread_turn(self, *, thread_id: str, owner: str) -> None:
            self.released.append((thread_id, owner))

    class SlowBranchActionBranchService(BranchActionBranchService):
        def fork_branch(self, **kwargs):
            time.sleep(0.03)
            return super().fork_branch(**kwargs)

    locks = RecordingThreadLocks()
    runtime = SimpleNamespace(
        settings=SettingsOverlay(
            Settings(runtime_thread_lock_ttl_seconds=9.0),
            runtime_thread_lock_heartbeat_seconds=0.01,
        ),
        graph=graph,
        repo=repo,
        branch_service=SlowBranchActionBranchService(),
        coordination_backend=CoordinationBackend(
            thread_turns=locks,
            job_deduper=InMemoryBackgroundJobDeduperBackend(),
            rate_limiter=InMemoryRateLimitBackend(),
        ),
    )
    chat = chat_service_factory(runtime)
    chat.send_message(thread_id="child-1", user_id="owner-1", message="帮我切换一个同级分支吧。")
    action_id = graph.values["branch_actions"][0]["action_id"]
    locks.acquired.clear()
    locks.heartbeats.clear()
    locks.released.clear()

    chat.execute_branch_action(thread_id="child-1", action_id=action_id, user_id="owner-1")

    assert locks.acquired
    assert locks.heartbeats
    assert locks.heartbeats[0][2] == 9.0
    assert locks.released == [("child-1", locks.acquired[0][1])]
