import asyncio
from pathlib import Path
from types import SimpleNamespace
import threading

import pytest
from langchain.messages import AIMessage, HumanMessage

from focus_agent.services.chat import ChatService, ConcurrentTurnError
from focus_agent.config import Settings
from focus_agent.repositories.sqlite_branch_repository import SQLiteBranchRepository
from focus_agent.core.branching import BranchRecord, BranchRole, BranchStatus
from focus_agent.skills.registry import SkillRegistry


class FakeGraph:
    def get_state(self, _config):
        return SimpleNamespace(values={})


class RecordingGraph:
    def __init__(self):
        self.values: dict[str, object] = {}
        self.last_payload = None
        self.last_context = None

    def invoke(self, payload, *, config, context, version):
        self.last_payload = payload
        self.last_context = context
        self.values = {
            "messages": [AIMessage(content="planned")],
            "active_skill_ids": list(payload.get("active_skill_ids", [])),
            "selected_model": payload.get("selected_model", ""),
            "selected_thinking_mode": payload.get("selected_thinking_mode", ""),
        }
        return {}

    def get_state(self, _config):
        return SimpleNamespace(values=self.values, interrupts=[])


class BackfillImportGraph:
    def __init__(self):
        self.values = {
            "messages": [AIMessage(content="existing assistant reply")],
            "merge_queue": [
                {
                    "branch_id": "branch-1",
                    "branch_name": "explore-alternatives",
                    "summary": "Recovered conclusion from child branch.",
                    "key_findings": ["Finding A"],
                    "evidence_refs": ["doc-1"],
                }
            ],
            "rolling_summary": "Existing summary.",
        }
        self.updates: list[tuple[dict[str, object], str | None]] = []

    def get_state(self, _config):
        return SimpleNamespace(values=self.values, interrupts=[])

    def update_state(self, _config, values, as_node=None):
        self.updates.append((values, as_node))
        if "messages" in values:
            self.values["messages"] = list(self.values.get("messages", [])) + list(values["messages"])
        if "rolling_summary" in values:
            self.values["rolling_summary"] = values["rolling_summary"]


def test_stream_message_raises_permission_error_before_streaming(tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")
    runtime = SimpleNamespace(
        settings=Settings(),
        graph=FakeGraph(),
        repo=repo,
    )
    chat = ChatService(runtime)

    with pytest.raises(PermissionError):
        chat.stream_message(thread_id="root-1", user_id="other-user", message="hello")


def test_send_message_rejects_merged_branch(tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")
    repo.create(
        BranchRecord(
            branch_id="b-merged",
            root_thread_id="root-1",
            parent_thread_id="root-1",
            child_thread_id="child-merged",
            return_thread_id="root-1",
            owner_user_id="owner-1",
            branch_name="Merged Branch",
            branch_role=BranchRole.DEEP_DIVE,
            branch_depth=1,
            branch_status=BranchStatus.MERGED,
        )
    )
    runtime = SimpleNamespace(
        settings=Settings(),
        graph=FakeGraph(),
        repo=repo,
    )
    chat = ChatService(runtime)

    with pytest.raises(PermissionError, match="Merged branches are read-only."):
        chat.send_message(thread_id="child-merged", user_id="owner-1", message="hello")


def test_stream_message_rejects_merged_branch_before_streaming(tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")
    repo.create(
        BranchRecord(
            branch_id="b-merged",
            root_thread_id="root-1",
            parent_thread_id="root-1",
            child_thread_id="child-merged",
            return_thread_id="root-1",
            owner_user_id="owner-1",
            branch_name="Merged Branch",
            branch_role=BranchRole.DEEP_DIVE,
            branch_depth=1,
            branch_status=BranchStatus.MERGED,
        )
    )
    runtime = SimpleNamespace(
        settings=Settings(),
        graph=FakeGraph(),
        repo=repo,
    )
    chat = ChatService(runtime)

    with pytest.raises(PermissionError, match="Merged branches are read-only."):
        chat.stream_message(thread_id="child-merged", user_id="owner-1", message="hello")


def test_sse_frame_serializes_message_objects():
    frame = ChatService._sse_frame(
        event="agent.update",
        data={"messages": [HumanMessage(content="hello")]},
    )

    assert 'event: agent.update' in frame
    assert '"content": "hello"' in frame


def test_stream_message_emits_heartbeat_during_long_running_turn(tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    class SlowStreamingGraph:
        def __init__(self):
            self.values = {
                "messages": [AIMessage(content="Final answer after heartbeat.")],
                "selected_model": "openai:gpt-4.1-mini",
                "selected_thinking_mode": "disabled",
            }

        async def astream(self, payload, *, config, context, stream_mode, version):
            del payload, config, context, stream_mode, version
            await asyncio.sleep(0.03)
            if False:
                yield {}

        def get_state(self, _config):
            return SimpleNamespace(values=self.values, interrupts=[])

    runtime = SimpleNamespace(
        settings=Settings(sse_heartbeat_seconds=0.01),
        graph=SlowStreamingGraph(),
        repo=repo,
        branch_service=SimpleNamespace(
            refresh_conversation_title_after_first_turn=lambda **kwargs: None,
            refresh_branch_name_after_first_turn=lambda **kwargs: None,
        ),
    )
    chat = ChatService(runtime)

    async def collect_frames():
        return [frame async for frame in chat.stream_message(thread_id="root-1", user_id="owner-1", message="hello")]

    frames = asyncio.run(collect_frames())

    assert any("event: status" in frame and '"stage": "heartbeat"' in frame for frame in frames)
    assert any("event: turn.completed" in frame for frame in frames)


def test_stream_message_does_not_complete_with_previous_assistant_reply(tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    class NoopStreamingGraph:
        def __init__(self):
            self.values = {
                "messages": [AIMessage(content="Previous answer that belongs to an older turn.")],
                "selected_model": "openai:gpt-4.1-mini",
                "selected_thinking_mode": "disabled",
            }

        async def astream(self, payload, *, config, context, stream_mode, version):
            del payload, config, context, stream_mode, version
            if False:
                yield {}

        def get_state(self, _config):
            return SimpleNamespace(values=self.values, interrupts=[])

    runtime = SimpleNamespace(
        settings=Settings(),
        graph=NoopStreamingGraph(),
        repo=repo,
    )
    chat = ChatService(runtime)

    async def collect_frames():
        return [frame async for frame in chat.stream_message(thread_id="root-1", user_id="owner-1", message="new turn")]

    frames = asyncio.run(collect_frames())

    assert not any(
        "event: visible_text.completed" in frame
        and "Previous answer that belongs to an older turn." in frame
        for frame in frames
    )
    assert any("event: turn.completed" in frame for frame in frames)


def test_send_message_rejects_concurrent_turn_on_same_thread(tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    class BlockingInvokeGraph:
        def __init__(self):
            self.values = {
                "messages": [AIMessage(content="done")],
                "selected_model": "openai:gpt-4.1-mini",
                "selected_thinking_mode": "disabled",
            }
            self.entered = threading.Event()
            self.release = threading.Event()

        def invoke(self, payload, *, config, context, version):
            del payload, config, context, version
            self.entered.set()
            assert self.release.wait(timeout=2.0)
            return {}

        def get_state(self, _config):
            return SimpleNamespace(values=self.values, interrupts=[])

    graph = BlockingInvokeGraph()
    runtime = SimpleNamespace(
        settings=Settings(),
        graph=graph,
        repo=repo,
    )
    chat = ChatService(runtime)
    completed = threading.Event()

    def run_first_turn():
        try:
            chat.send_message(thread_id="root-1", user_id="owner-1", message="first")
        finally:
            completed.set()

    worker = threading.Thread(target=run_first_turn, daemon=True)
    worker.start()
    assert graph.entered.wait(timeout=2.0)

    with pytest.raises(ConcurrentTurnError, match="still processing the previous turn"):
        chat.send_message(thread_id="root-1", user_id="owner-1", message="second")

    graph.release.set()
    assert completed.wait(timeout=2.0)
    worker.join(timeout=2.0)


def test_stream_message_reports_busy_thread_failure(tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    class BlockingStreamingGraph:
        def __init__(self):
            self.values = {
                "messages": [AIMessage(content="Final answer after wait.")],
                "selected_model": "openai:gpt-4.1-mini",
                "selected_thinking_mode": "disabled",
            }
            self.entered: asyncio.Event | None = None
            self.release: asyncio.Event | None = None

        async def astream(self, payload, *, config, context, stream_mode, version):
            del payload, config, context, stream_mode, version
            assert self.entered is not None
            assert self.release is not None
            self.entered.set()
            await self.release.wait()
            if False:
                yield {}

        def get_state(self, _config):
            return SimpleNamespace(values=self.values, interrupts=[])

    graph = BlockingStreamingGraph()
    runtime = SimpleNamespace(
        settings=Settings(sse_heartbeat_seconds=0.01),
        graph=graph,
        repo=repo,
        branch_service=SimpleNamespace(
            refresh_conversation_title_after_first_turn=lambda **kwargs: None,
            refresh_branch_name_after_first_turn=lambda **kwargs: None,
        ),
    )
    chat = ChatService(runtime)

    async def collect_frames(stream):
        return [frame async for frame in stream]

    async def run_test():
        graph.entered = asyncio.Event()
        graph.release = asyncio.Event()

        first_task = asyncio.create_task(
            collect_frames(chat.stream_message(thread_id="root-1", user_id="owner-1", message="first"))
        )
        await asyncio.wait_for(graph.entered.wait(), timeout=1.0)

        second_frames = [
            frame
            async for frame in chat.stream_message(thread_id="root-1", user_id="owner-1", message="second")
        ]

        assert any("event: turn.failed" in frame for frame in second_frames)
        assert any("previous turn" in frame for frame in second_frames)

        graph.release.set()
        first_frames = await asyncio.wait_for(first_task, timeout=1.0)
        assert any("event: turn.completed" in frame for frame in first_frames)

    asyncio.run(run_test())


def test_get_thread_state_falls_back_to_repo_when_branch_meta_is_incomplete(tmp_path: Path):
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
            return SimpleNamespace(values={"branch_meta": {"is_archived": True, "archived_at": "2026-04-12 10:00:00"}})

    runtime = SimpleNamespace(
        settings=Settings(),
        graph=BrokenBranchGraph(),
        repo=repo,
    )
    chat = ChatService(runtime)

    payload = chat.get_thread_state(thread_id="child-1", user_id="owner-1")

    assert payload["thread_id"] == "child-1"
    assert payload["branch_meta"]["branch_id"] == "b-1"
    assert payload["branch_meta"]["branch_name"] == "Recovered Branch"
    assert "conclusion_policy" not in payload["branch_meta"]


def test_get_thread_state_falls_back_to_repo_when_branch_meta_is_missing(tmp_path: Path):
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
    chat = ChatService(runtime)

    payload = chat.get_thread_state(thread_id="child-2", user_id="owner-1")

    assert payload["thread_id"] == "child-2"
    assert payload["root_thread_id"] == "root-1"
    assert payload["branch_meta"]["branch_id"] == "b-2"
    assert payload["branch_meta"]["parent_thread_id"] == "root-1"
    assert "conclusion_policy" not in payload["branch_meta"]


def test_send_message_activates_skills_from_prefix(tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    skill_dir = tmp_path / "skills"
    plan_dir = skill_dir / "plan"
    plan_dir.mkdir(parents=True, exist_ok=True)
    (plan_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                "name: plan",
                "description: Planning mode",
                "triggers: plan:",
                "prompt_mode: explore",
                "---",
                "",
                "# Plan",
                "",
                "Plan first.",
            ]
        ),
        encoding="utf-8",
    )

    graph = RecordingGraph()
    runtime = SimpleNamespace(
        settings=Settings(),
        graph=graph,
        repo=repo,
        skill_registry=SkillRegistry([skill_dir]),
    )
    chat = ChatService(runtime)

    payload = chat.send_message(
        thread_id="root-1",
        user_id="owner-1",
        message="plan: map the rollout",
        model="moonshot:kimi-k2.5",
        thinking_mode="disabled",
    )

    assert graph.last_context.skill_hints == ("plan",)
    assert graph.last_payload["task_brief"] == "map the rollout"
    assert graph.last_payload["active_skill_ids"] == ["plan"]
    assert graph.last_payload["selected_model"] == "moonshot:kimi-k2.5"
    assert graph.last_payload["selected_thinking_mode"] == "disabled"
    assert payload["active_skill_ids"] == ["plan"]
    assert payload["selected_model"] == "moonshot:kimi-k2.5"
    assert payload["selected_thinking_mode"] == "disabled"


def test_get_thread_state_backfills_visible_imported_conclusion(tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")
    graph = BackfillImportGraph()
    runtime = SimpleNamespace(
        settings=Settings(),
        graph=graph,
        repo=repo,
    )
    chat = ChatService(runtime)

    payload = chat.get_thread_state(thread_id="root-1", user_id="owner-1")

    system_messages = [message for message in payload["messages"] if message["type"] == "system"]
    assert system_messages
    assert "Imported conclusion from branch 'explore-alternatives':" in system_messages[-1]["content"]
    assert "Recovered conclusion from child branch." in system_messages[-1]["content"]
    assert payload["rolling_summary"].endswith(
        "Imported from explore-alternatives: Recovered conclusion from child branch."
    )
    assert graph.updates
    assert graph.updates[0][1] == "bootstrap_turn"
