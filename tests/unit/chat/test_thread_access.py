from focus_agent.services.chat.threads import ChatThreadAccessMixin

from .support import (
    BackfillImportGraph,
    BranchRecord,
    BranchRole,
    BranchStatus,
    ChatServicePorts,
    FailingBackfillImportGraph,
    FakeGraph,
    HumanMessage,
    Path,
    PostCommitFailingBackfillImportGraph,
    Settings,
    SimpleNamespace,
    SQLiteBranchRepository,
    SystemMessage,
    ThreadStateUnavailableError,
    pytest,
)


def test_chat_service_accepts_narrow_ports(chat_service_factory, tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")
    ports = ChatServicePorts(settings=Settings(), graph=FakeGraph(), repo=repo)
    chat = chat_service_factory(ports)

    payload = chat.get_thread_state(thread_id="root-1", user_id="owner-1")

    assert payload["thread_id"] == "root-1"
    assert chat.ports is ports


def test_get_thread_state_does_not_mask_snapshot_read_failure(chat_service_factory, tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    class BrokenGraph:
        def get_state(self, _config):
            raise RuntimeError("graph unavailable")

    chat = chat_service_factory(
        ChatServicePorts(settings=Settings(), graph=BrokenGraph(), repo=repo)
    )

    with pytest.raises(ThreadStateUnavailableError):
        chat.get_thread_state(thread_id="root-1", user_id="owner-1")


def test_get_thread_state_falls_back_to_repo_when_branch_meta_is_incomplete(
    chat_service_factory, tmp_path: Path
):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")
    repo.ensure_thread_owner(thread_id="child-1", root_thread_id="root-1", owner_user_id="owner-1")
    repo.create(
        BranchRecord(
            branch_id="b-1",
            root_thread_id="root-1",
            parent_thread_id="root-1",
            child_thread_id="child-1",
            return_thread_id="root-1",
            owner_user_id="owner-1",
            branch_name="Recovered Branch",
            branch_role=BranchRole.DEEP_DIVE,
            branch_depth=1,
            branch_status=BranchStatus.ACTIVE,
            is_archived=True,
            archived_at="2026-04-12 10:00:00",
        )
    )

    class BrokenBranchGraph:
        def get_state(self, _config):
            return SimpleNamespace(
                values={"branch_meta": {"is_archived": True, "archived_at": "2026-04-12 10:00:00"}}
            )

    runtime = SimpleNamespace(
        settings=Settings(),
        graph=BrokenBranchGraph(),
        repo=repo,
    )
    chat = chat_service_factory(runtime)

    payload = chat.get_thread_state(thread_id="child-1", user_id="owner-1")

    assert payload["thread_id"] == "child-1"
    assert payload["branch_meta"]["branch_id"] == "b-1"
    assert payload["branch_meta"]["branch_name"] == "Recovered Branch"
    assert "conclusion_policy" not in payload["branch_meta"]


def test_get_thread_state_falls_back_to_repo_when_branch_meta_is_missing(
    chat_service_factory, tmp_path: Path
):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")
    repo.ensure_thread_owner(thread_id="child-2", root_thread_id="root-1", owner_user_id="owner-1")
    repo.create(
        BranchRecord(
            branch_id="b-2",
            root_thread_id="root-1",
            parent_thread_id="root-1",
            child_thread_id="child-2",
            return_thread_id="root-1",
            owner_user_id="owner-1",
            branch_name="Fresh Branch",
            branch_role=BranchRole.EXPLORE_ALTERNATIVES,
            branch_depth=1,
            branch_status=BranchStatus.ACTIVE,
        )
    )

    class MissingBranchMetaGraph:
        def get_state(self, _config):
            return SimpleNamespace(values={})

    runtime = SimpleNamespace(
        settings=Settings(),
        graph=MissingBranchMetaGraph(),
        repo=repo,
    )
    chat = chat_service_factory(runtime)

    payload = chat.get_thread_state(thread_id="child-2", user_id="owner-1")

    assert payload["thread_id"] == "child-2"
    assert payload["root_thread_id"] == "root-1"
    assert payload["branch_meta"]["branch_id"] == "b-2"
    assert payload["branch_meta"]["parent_thread_id"] == "root-1"
    assert "conclusion_policy" not in payload["branch_meta"]


def test_imported_conclusion_message_preserves_chat_guards():
    assert ChatThreadAccessMixin._imported_conclusion_message({"summary": " "}) == ""
    assert (
        ChatThreadAccessMixin._imported_conclusion_message(
            {"branch_id": "branch-1", "summary": " Conclusion "}
        )
        == "Imported conclusion from branch 'branch-1':\nConclusion"
    )
    assert (
        ChatThreadAccessMixin._imported_conclusion_message({"summary": "Conclusion"})
        == "Imported conclusion from branch 'unknown branch':\nConclusion"
    )


def test_append_imported_summary_preserves_chat_guards():
    imported = {"branch_id": "branch-1", "summary": " Conclusion "}
    assert (
        ChatThreadAccessMixin._append_imported_summary(" Existing ", {"summary": " "}) == "Existing"
    )

    previous = "Existing\nImported from branch-1: Conclusion"
    assert ChatThreadAccessMixin._append_imported_summary(previous, imported) == previous

    truncated = ChatThreadAccessMixin._append_imported_summary("x" * 4000, imported)
    assert len(truncated) == 4000
    assert truncated.endswith("Imported from branch-1: Conclusion")


def test_get_thread_state_backfills_visible_imported_conclusion(
    chat_service_factory, tmp_path: Path
):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")
    graph = BackfillImportGraph()
    runtime = SimpleNamespace(
        settings=Settings(),
        graph=graph,
        repo=repo,
    )
    chat = chat_service_factory(runtime)

    payload = chat.get_thread_state(
        thread_id="root-1",
        user_id="owner-1",
        request_id="req-snapshot",
    )

    system_messages = [message for message in payload["messages"] if message["type"] == "system"]
    assert system_messages
    assert payload["trace"]["metadata"]["request_id"] == "req-snapshot"
    assert (
        "Imported conclusion from branch 'explore-alternatives':" in system_messages[-1]["content"]
    )
    assert "Recovered conclusion from child branch." in system_messages[-1]["content"]
    assert payload["rolling_summary"].endswith(
        "Imported from explore-alternatives: Recovered conclusion from child branch."
    )
    assert graph.updates
    assert graph.updates[0][1] == "bootstrap_turn"


def test_unauthorized_thread_state_does_not_backfill_or_write_graph(
    chat_service_factory, tmp_path: Path
):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")
    graph = BackfillImportGraph()
    before = dict(graph.values)
    chat = chat_service_factory(SimpleNamespace(settings=Settings(), graph=graph, repo=repo))

    with pytest.raises(PermissionError):
        chat.get_thread_state(thread_id="root-1", user_id="intruder-1")

    assert graph.updates == []
    assert graph.values == before


def test_backfill_failure_returns_persisted_state(chat_service_factory, tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")
    graph = FailingBackfillImportGraph()
    chat = chat_service_factory(SimpleNamespace(settings=Settings(), graph=graph, repo=repo))

    payload = chat.get_thread_state(thread_id="root-1", user_id="owner-1")

    assert payload["rolling_summary"] == "Existing summary."
    assert not [message for message in payload["messages"] if message["type"] == "system"]
    assert len(graph.updates) == 1


def test_backfill_post_commit_failure_returns_new_persisted_state(
    chat_service_factory, tmp_path: Path
):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")
    graph = PostCommitFailingBackfillImportGraph()
    chat = chat_service_factory(SimpleNamespace(settings=Settings(), graph=graph, repo=repo))

    payload = chat.get_thread_state(thread_id="root-1", user_id="owner-1")

    assert "Imported from explore-alternatives" in payload["rolling_summary"]
    assert any(message["type"] == "system" for message in payload["messages"])
    assert len(graph.updates) == 1


def test_get_thread_state_dedupes_dict_imported_conclusion_notice(
    chat_service_factory, tmp_path: Path
):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")
    graph = BackfillImportGraph()
    graph.values["messages"] = [
        {
            "type": "system",
            "content": (
                "Imported conclusion from branch 'explore-alternatives':\n"
                "Recovered conclusion from child branch.\n\n"
                "Key findings:\n"
                "- Finding A\n\n"
                "Evidence refs: doc-1"
            ),
        }
    ]
    runtime = SimpleNamespace(
        settings=Settings(),
        graph=graph,
        repo=repo,
    )
    chat = chat_service_factory(runtime)

    payload = chat.get_thread_state(
        thread_id="root-1",
        user_id="owner-1",
        request_id="req-snapshot",
    )

    system_messages = [message for message in payload["messages"] if message["type"] == "system"]
    assert len(system_messages) == 1
    assert "Recovered conclusion from child branch." in system_messages[0]["content"]
    assert graph.updates
    assert "messages" not in graph.updates[0][0]


def test_get_thread_state_returns_longer_recent_history_window(
    chat_service_factory, tmp_path: Path
):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")
    messages = [HumanMessage(content=f"message-{index}") for index in range(60)]

    class LongHistoryGraph:
        def get_state(self, _config):
            return SimpleNamespace(values={"messages": messages}, interrupts=[])

    runtime = SimpleNamespace(
        settings=Settings(),
        graph=LongHistoryGraph(),
        repo=repo,
    )
    chat = chat_service_factory(runtime)

    payload = chat.get_thread_state(thread_id="root-1", user_id="owner-1")

    assert len(payload["messages"]) == 60
    assert payload["messages"][0]["content"] == "message-0"
    assert payload["messages"][-1]["content"] == "message-59"


def test_get_thread_state_caps_history_window_for_large_threads(
    chat_service_factory, tmp_path: Path
):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")
    messages = [SystemMessage(content=f"message-{index}") for index in range(250)]

    class LargeHistoryGraph:
        def get_state(self, _config):
            return SimpleNamespace(values={"messages": messages}, interrupts=[])

    runtime = SimpleNamespace(
        settings=Settings(),
        graph=LargeHistoryGraph(),
        repo=repo,
    )
    chat = chat_service_factory(runtime)

    payload = chat.get_thread_state(thread_id="root-1", user_id="owner-1")

    assert len(payload["messages"]) == chat._THREAD_STATE_MESSAGE_LIMIT
    assert payload["messages"][0]["content"] == "message-50"
    assert payload["messages"][-1]["content"] == "message-249"


def test_get_thread_state_keeps_state_fork_brief_alongside_repo_branch_meta(
    chat_service_factory, tmp_path: Path
):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")
    repo.ensure_thread_owner(thread_id="child-3", root_thread_id="root-1", owner_user_id="owner-1")
    repo.create(
        BranchRecord(
            branch_id="b-3",
            root_thread_id="root-1",
            parent_thread_id="root-1",
            child_thread_id="child-3",
            return_thread_id="root-1",
            owner_user_id="owner-1",
            branch_name="Repo Name",
            branch_role=BranchRole.DEEP_DIVE,
            branch_depth=1,
            branch_status=BranchStatus.ACTIVE,
        )
    )
    fork_brief = {
        "goal": "Compare cost under $2k/mo",
        "parent_summary": "Rejected MySQL.",
        "parent_recent_turns": [{"role": "user", "content": "Shortlist Yugabyte"}],
        "forked_at": "2026-10-31T00:00:00+00:00",
        "parent_message_count": 4,
    }

    class StateGraph:
        def get_state(self, _config):
            return SimpleNamespace(
                values={
                    "branch_meta": {
                        "branch_id": "b-3",
                        "root_thread_id": "root-1",
                        "parent_thread_id": "root-1",
                        "return_thread_id": "root-1",
                        "branch_name": "Stale State Name",
                        "branch_role": "deep_dive",
                        "branch_depth": 1,
                        "fork_brief": fork_brief,
                    }
                }
            )

    chat = chat_service_factory(SimpleNamespace(settings=Settings(), graph=StateGraph(), repo=repo))

    payload = chat.get_thread_state(thread_id="child-3", user_id="owner-1")

    assert payload["branch_meta"]["branch_name"] == "Repo Name"
    assert payload["branch_meta"]["fork_brief"] == fork_brief
