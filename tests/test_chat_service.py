import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import threading
import time

import pytest
from langchain.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.base import BaseCheckpointSaver

from focus_agent.services.chat import ChatService, ChatServicePorts, ConcurrentTurnError
from focus_agent.services.branch_actions import is_branch_action_request
from focus_agent.services.coordination import (
    CoordinationBackend,
    InMemoryBackgroundJobDeduperBackend,
    InMemoryThreadTurnLockBackend,
    InMemoryRateLimitBackend,
)
from focus_agent.services.thread_turn_lease import ThreadTurnLeaseManager
from focus_agent.config import ConfiguredModel, ModelCatalogConfig, Settings
from focus_agent.repositories.sqlite_branch_repository import SQLiteBranchRepository
from focus_agent.core.branching import BranchMeta, BranchRecord, BranchRole, BranchStatus
from focus_agent.skills.registry import SkillRegistry


class SettingsOverlay:
    def __init__(self, base: Settings, **overrides):
        self._base = base
        for key, value in overrides.items():
            setattr(self, key, value)

    def __getattr__(self, name):
        return getattr(self._base, name)


class FakeGraph:
    def get_state(self, _config):
        return SimpleNamespace(values={})


class StaleBranchMetaGraph:
    def get_state(self, _config):
        return SimpleNamespace(
            values={
                "branch_meta": {
                    "branch_id": "b-merged",
                    "root_thread_id": "root-1",
                    "parent_thread_id": "root-1",
                    "return_thread_id": "root-1",
                    "branch_name": "Merged Branch",
                    "branch_role": "deep_dive",
                    "branch_depth": 1,
                    "branch_status": "active",
                }
            },
            interrupts=[],
        )


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

    def update_state(self, _config, values, as_node=None):
        del _config, as_node
        self.values = {**self.values, **dict(values)}


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


class BranchActionGraph:
    def __init__(self, values: dict[str, object] | None = None):
        self.values = values or {}
        self.updates: list[tuple[dict[str, object], str | None]] = []

    def get_state(self, _config):
        return SimpleNamespace(values=self.values, interrupts=[])

    def update_state(self, _config, values, as_node=None):
        self.updates.append((values, as_node))
        if "messages" in values:
            self.values["messages"] = list(self.values.get("messages", [])) + list(values["messages"])
        for key, value in values.items():
            if key != "messages":
                self.values[key] = value


class BranchActionBranchService:
    def __init__(self):
        self.fork_calls: list[dict[str, object]] = []

    def fork_branch(self, **kwargs):
        self.fork_calls.append(kwargs)
        return BranchRecord(
            branch_id="branch-new",
            root_thread_id="root-1",
            parent_thread_id=str(kwargs["parent_thread_id"]),
            child_thread_id="child-new",
            return_thread_id=str(kwargs["parent_thread_id"]),
            owner_user_id=str(kwargs["user_id"]),
            branch_name=str(kwargs.get("branch_name") or "New Branch"),
            branch_role=kwargs.get("branch_role") or BranchRole.EXPLORE_ALTERNATIVES,
            branch_depth=1,
            branch_status=BranchStatus.ACTIVE,
        )


class FailingBranchActionBranchService:
    def fork_branch(self, **_kwargs):
        raise ValueError("fork failed for test")


def _decode_sse_frames(frames: list[str]) -> list[tuple[str, dict[str, object]]]:
    decoded: list[tuple[str, dict[str, object]]] = []
    for frame in frames:
        event = ""
        data_lines: list[str] = []
        for line in frame.splitlines():
            if line.startswith("event: "):
                event = line.removeprefix("event: ")
            elif line.startswith("data: "):
                data_lines.append(line.removeprefix("data: "))
        if event:
            decoded.append((event, json.loads("\n".join(data_lines))))
    return decoded


def _repo_with_child_branch(tmp_path: Path) -> SQLiteBranchRepository:
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")
    repo.ensure_thread_owner(thread_id="child-1", root_thread_id="root-1", owner_user_id="owner-1")
    repo.create(
        BranchRecord(
            branch_id="branch-1",
            root_thread_id="root-1",
            parent_thread_id="root-1",
            child_thread_id="child-1",
            return_thread_id="root-1",
            owner_user_id="owner-1",
            branch_name="Nanwang Energy Deep Dive",
            branch_role=BranchRole.DEEP_DIVE,
            branch_depth=1,
            branch_status=BranchStatus.ACTIVE,
        )
    )
    return repo


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


def test_chat_service_accepts_narrow_ports(tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")
    ports = ChatServicePorts(settings=Settings(), graph=FakeGraph(), repo=repo)
    chat = ChatService(ports)

    payload = chat.get_thread_state(thread_id="root-1", user_id="owner-1")

    assert payload["thread_id"] == "root-1"
    assert chat.ports is ports


def test_send_message_creates_pending_branch_action_without_forking(tmp_path: Path):
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
    chat = ChatService(runtime)

    payload = chat.send_message(
        thread_id="child-1",
        user_id="owner-1",
        message="是的，帮我切换一个同级分支吧。",
    )

    assert branch_service.fork_calls == []
    assert payload["branch_actions"][0]["kind"] == "fork_sibling_branch"
    assert payload["branch_actions"][0]["status"] == "pending"
    assert payload["branch_actions"][0]["target_parent_thread_id"] == "root-1"
    assert "华英农业" in payload["branch_actions"][0]["suggested_branch_name"]
    assert "已创建" not in payload["assistant_message"]
    assert graph.updates[-1][1] == "bootstrap_turn"


def test_branch_action_intent_requires_branch_context():
    assert is_branch_action_request("帮我切换一个同级分支吧。")
    assert is_branch_action_request("Create a sibling branch for this idea.")
    assert not is_branch_action_request("帮我切换一下模型。")
    assert not is_branch_action_request("切换到深度思考模式。")


def test_stream_message_executes_pending_branch_action_and_emits_navigation(tmp_path: Path):
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
    chat = ChatService(runtime)
    chat.send_message(thread_id="child-1", user_id="owner-1", message="帮我切换一个同级分支吧。")

    async def collect_frames():
        return [frame async for frame in chat.stream_message(thread_id="child-1", user_id="owner-1", message="直接切过去。")]

    frames = asyncio.run(collect_frames())

    assert branch_service.fork_calls[0]["parent_thread_id"] == "root-1"
    assert branch_service.fork_calls[0]["branch_name"]
    assert any("event: branch.action.executed" in frame and '"thread_id": "child-new"' in frame for frame in frames)
    assert any("event: turn.completed" in frame for frame in frames)
    assert graph.values["branch_actions"][0]["status"] == "executed"


def test_stream_message_emits_failed_branch_action_when_execution_fails(tmp_path: Path):
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
        branch_service=FailingBranchActionBranchService(),
    )
    chat = ChatService(runtime)
    chat.send_message(thread_id="child-1", user_id="owner-1", message="帮我切换一个同级分支吧。")

    async def collect_frames():
        return [frame async for frame in chat.stream_message(thread_id="child-1", user_id="owner-1", message="直接切过去。")]

    frames = asyncio.run(collect_frames())

    assert any("event: branch.action.failed" in frame and "fork failed for test" in frame for frame in frames)
    assert any("event: turn.failed" in frame for frame in frames)
    assert graph.values["branch_actions"][0]["status"] == "failed"
    assert graph.values["branch_actions"][0]["error"] == "fork failed for test"


def test_branch_action_execute_uses_thread_turn_lock(tmp_path: Path):
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
    chat = ChatService(runtime)
    chat.send_message(thread_id="child-1", user_id="owner-1", message="帮我切换一个同级分支吧。")
    action_id = graph.values["branch_actions"][0]["action_id"]

    chat._acquire_thread_turn(thread_id="child-1")
    try:
        with pytest.raises(ConcurrentTurnError, match="still processing the previous turn"):
            chat.execute_branch_action(thread_id="child-1", action_id=action_id, user_id="owner-1")
    finally:
        chat._release_thread_turn(thread_id="child-1")


def test_thread_turn_lock_heartbeat_interval_uses_ttl_third_cap():
    runtime = SimpleNamespace(
        settings=SettingsOverlay(
            Settings(runtime_thread_lock_ttl_seconds=9.0),
            runtime_thread_lock_heartbeat_seconds=10.0,
        ),
        graph=FakeGraph(),
        repo=SimpleNamespace(),
    )
    chat = ChatService(runtime)

    assert chat._thread_turn_lock_heartbeat_seconds() == 3.0

    runtime.settings = SettingsOverlay(
        Settings(runtime_thread_lock_ttl_seconds=9.0),
        runtime_thread_lock_heartbeat_seconds=2.0,
    )
    chat = ChatService(runtime)

    assert chat._thread_turn_lock_heartbeat_seconds() == 2.0


def test_branch_action_execute_heartbeats_thread_turn_lock(tmp_path: Path):
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
    chat = ChatService(runtime)
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


def test_send_message_rejects_merged_branch_when_graph_meta_is_stale(tmp_path: Path):
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
        graph=StaleBranchMetaGraph(),
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


def test_compact_thread_context_rejects_merged_branch(tmp_path: Path):
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
        chat.compact_thread_context(thread_id="child-merged", user_id="owner-1")


def test_preview_thread_context_increases_with_draft_message(tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    class ContextPreviewGraph:
        def get_state(self, _config):
            return SimpleNamespace(
                values={
                    "messages": [HumanMessage(content="Known context"), AIMessage(content="Known answer")],
                    "context_budget": {"prompt_token_limit": 10000, "chars_per_token": 4},
                },
                interrupts=[],
            )

    runtime = SimpleNamespace(
        settings=Settings(),
        graph=ContextPreviewGraph(),
        repo=repo,
    )
    chat = ChatService(runtime)

    baseline = chat.preview_thread_context(thread_id="root-1", user_id="owner-1")["context_usage"]
    with_draft = chat.preview_thread_context(
        thread_id="root-1",
        user_id="owner-1",
        draft_message="draft context " * 80,
    )["context_usage"]

    assert with_draft["used_tokens"] > baseline["used_tokens"]
    assert with_draft["token_limit"] == 10000


def test_compact_thread_context_updates_summary_without_deleting_messages(tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    class CompactGraph:
        def __init__(self):
            self.values = {
                "messages": [
                    HumanMessage(content="Original user goal"),
                    AIMessage(content="Original assistant answer"),
                ],
                "rolling_summary": "Previous rolling summary.",
                "user_constraints": [{"constraint": "Keep token usage separate from context usage."}],
                "context_budget": {"prompt_token_limit": 10000, "chars_per_token": 4},
            }
            self.updates = []

        def get_state(self, _config):
            return SimpleNamespace(values=self.values, interrupts=[])

        def update_state(self, _config, values, as_node=None):
            self.updates.append((values, as_node))
            self.values = {**self.values, **dict(values)}

    graph = CompactGraph()
    runtime = SimpleNamespace(
        settings=Settings(),
        graph=graph,
        repo=repo,
    )
    chat = ChatService(runtime)

    payload = chat.compact_thread_context(thread_id="root-1", user_id="owner-1", trigger="manual")

    assert len(graph.values["messages"]) == 2
    assert graph.updates[-1][1] == "context_compaction"
    assert graph.values["context_compaction"]["trigger"] == "manual"
    assert graph.values["context_compaction"]["non_destructive"] is True
    assert "Context compaction snapshot:" in graph.values["rolling_summary"]
    assert payload["context_usage"]["last_compacted_at"] == graph.values["context_compaction"]["last_compacted_at"]


def test_compact_thread_context_heartbeats_thread_turn_lock(tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

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

    class SlowCompactGraph:
        def __init__(self):
            self.values = {
                "messages": [
                    HumanMessage(content="Original user goal"),
                    AIMessage(content="Original assistant answer"),
                ],
                "context_budget": {"prompt_token_limit": 10000, "chars_per_token": 4},
            }

        def get_state(self, _config):
            return SimpleNamespace(values=self.values, interrupts=[])

        def update_state(self, _config, values, as_node=None):
            del _config, as_node
            time.sleep(0.03)
            self.values = {**self.values, **dict(values)}

    locks = RecordingThreadLocks()
    runtime = SimpleNamespace(
        settings=SettingsOverlay(
            Settings(runtime_thread_lock_ttl_seconds=9.0),
            runtime_thread_lock_heartbeat_seconds=0.01,
        ),
        graph=SlowCompactGraph(),
        repo=repo,
        coordination_backend=CoordinationBackend(
            thread_turns=locks,
            job_deduper=InMemoryBackgroundJobDeduperBackend(),
            rate_limiter=InMemoryRateLimitBackend(),
        ),
    )
    chat = ChatService(runtime)

    chat.compact_thread_context(thread_id="root-1", user_id="owner-1", trigger="manual")

    assert locks.acquired
    assert locks.heartbeats
    assert locks.heartbeats[0][2] == 9.0
    assert locks.released == [("root-1", locks.acquired[0][1])]


def test_post_turn_context_compaction_uses_durable_background_job_when_enabled(tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    class RecordingJobDeduper(InMemoryBackgroundJobDeduperBackend):
        def __init__(self):
            super().__init__()
            self.enqueued = []

        def enqueue_job(self, spec):
            self.enqueued.append(spec)
            return True

    class RecordingBackgroundWork:
        def __init__(self):
            self.submitted: list[str] = []

        def submit(self, *, key, func, delay_seconds=0.0, **kwargs):
            del func, delay_seconds, kwargs
            self.submitted.append(key)
            return True

    job_deduper = RecordingJobDeduper()
    background_work = RecordingBackgroundWork()
    runtime = SimpleNamespace(
        settings=Settings(background_job_execution="durable"),
        graph=FakeGraph(),
        repo=repo,
        background_work=background_work,
        coordination_backend=CoordinationBackend(
            thread_turns=InMemoryThreadTurnLockBackend(),
            job_deduper=job_deduper,
            rate_limiter=InMemoryRateLimitBackend(),
        ),
    )
    chat = ChatService(runtime)

    chat._schedule_post_turn_context_compaction(thread_id="root-1", user_id="owner-1", kind="chat.turn")

    assert background_work.submitted == []
    assert len(job_deduper.enqueued) == 1
    spec = job_deduper.enqueued[0]
    assert spec.kind == "context_compaction"
    assert spec.key == "chat:context_compaction:root-1"
    assert spec.payload == {
        "thread_id": "root-1",
        "user_id": "owner-1",
        "trigger": "auto_post_turn",
        "force": False,
    }
    assert spec.max_attempts == 3
    assert spec.dedupe_policy == "replace"


def test_branch_title_refresh_uses_durable_background_jobs_when_enabled(tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    class RecordingJobDeduper(InMemoryBackgroundJobDeduperBackend):
        def __init__(self):
            super().__init__()
            self.enqueued = []

        def enqueue_job(self, spec):
            self.enqueued.append(spec)
            return True

    class RecordingBackgroundWork:
        def __init__(self):
            self.submitted: list[str] = []

        def submit(self, *, key, func, delay_seconds=0.0, **kwargs):
            del func, delay_seconds, kwargs
            self.submitted.append(key)
            return True

    class RecordingBranchService:
        def __init__(self):
            self.calls: list[tuple[str, dict[str, str]]] = []

        def refresh_conversation_title_after_first_turn(self, **kwargs):
            self.calls.append(("conversation_title", kwargs))

        def refresh_branch_metadata_after_first_turn(self, **kwargs):
            self.calls.append(("branch_title", kwargs))

    job_deduper = RecordingJobDeduper()
    background_work = RecordingBackgroundWork()
    branch_service = RecordingBranchService()
    runtime = SimpleNamespace(
        settings=Settings(background_job_execution="durable"),
        graph=FakeGraph(),
        repo=repo,
        branch_service=branch_service,
        background_work=background_work,
        coordination_backend=CoordinationBackend(
            thread_turns=InMemoryThreadTurnLockBackend(),
            job_deduper=job_deduper,
            rate_limiter=InMemoryRateLimitBackend(),
        ),
    )
    chat = ChatService(runtime)

    chat._schedule_branch_name_refresh_after_first_turn(
        thread_id="root-1",
        user_id="owner-1",
        branch_meta=None,
        kind="chat.turn",
    )
    chat._schedule_branch_name_refresh_after_first_turn(
        thread_id="child-1",
        user_id="owner-1",
        branch_meta=BranchMeta(
            branch_id="branch-1",
            root_thread_id="root-1",
            parent_thread_id="root-1",
            return_thread_id="root-1",
            branch_name="Deep Dive",
            branch_role=BranchRole.DEEP_DIVE,
            branch_depth=1,
        ),
        kind="chat.turn",
    )

    assert branch_service.calls == []
    assert background_work.submitted == []
    assert [(spec.kind, spec.key, spec.payload) for spec in job_deduper.enqueued] == [
        (
            "conversation_title",
            "chat:conversation_title:root-1",
            {"root_thread_id": "root-1", "user_id": "owner-1"},
        ),
        (
            "branch_title",
            "chat:branch_title:child-1",
            {"child_thread_id": "child-1", "user_id": "owner-1"},
        ),
    ]
    assert all(spec.max_attempts == 3 for spec in job_deduper.enqueued)
    assert all(spec.dedupe_policy == "replace" for spec in job_deduper.enqueued)


def test_branch_metadata_refresh_is_scheduled_after_sync_turn_lease_release(tmp_path: Path):
    repo = _repo_with_child_branch(tmp_path)
    locks = InMemoryThreadTurnLockBackend()

    class ImmediateBackgroundWork:
        def __init__(self):
            self.submitted: list[str] = []

        def submit(self, *, key, func, delay_seconds=0.0, **kwargs):
            del delay_seconds
            self.submitted.append(key)
            func(**kwargs)
            return True

    class LeaseCheckingBranchService:
        def __init__(self):
            self.calls: list[dict[str, str]] = []

        def refresh_branch_metadata_after_first_turn(self, **kwargs):
            with ThreadTurnLeaseManager(
                backend=locks,
                thread_id=kwargs["child_thread_id"],
                ttl_seconds=30.0,
                heartbeat_interval_seconds=30.0,
            ):
                self.calls.append(dict(kwargs))

    background_work = ImmediateBackgroundWork()
    branch_service = LeaseCheckingBranchService()
    runtime = SimpleNamespace(
        settings=Settings(),
        graph=RecordingGraph(),
        repo=repo,
        branch_service=branch_service,
        background_work=background_work,
        coordination_backend=CoordinationBackend(
            thread_turns=locks,
            job_deduper=InMemoryBackgroundJobDeduperBackend(),
            rate_limiter=InMemoryRateLimitBackend(),
        ),
    )
    chat = ChatService(runtime)

    chat.send_message(thread_id="child-1", user_id="owner-1", message="first branch turn")

    assert background_work.submitted[-1] == "chat:branch_title:child-1"
    assert branch_service.calls == [{"child_thread_id": "child-1", "user_id": "owner-1"}]


def test_branch_metadata_refresh_is_scheduled_after_stream_turn_lease_release(tmp_path: Path):
    repo = _repo_with_child_branch(tmp_path)
    locks = InMemoryThreadTurnLockBackend()

    class ImmediateBackgroundWork:
        def __init__(self):
            self.submitted: list[str] = []

        def submit(self, *, key, func, delay_seconds=0.0, **kwargs):
            del delay_seconds
            self.submitted.append(key)
            func(**kwargs)
            return True

    class LeaseCheckingBranchService:
        def __init__(self):
            self.calls: list[dict[str, str]] = []

        def refresh_branch_metadata_after_first_turn(self, **kwargs):
            with ThreadTurnLeaseManager(
                backend=locks,
                thread_id=kwargs["child_thread_id"],
                ttl_seconds=30.0,
                heartbeat_interval_seconds=30.0,
            ):
                self.calls.append(dict(kwargs))

    class BranchStreamingGraph:
        def __init__(self):
            self.values = {
                "messages": [AIMessage(content="Branch answer.")],
                "selected_model": "openai:gpt-4.1-mini",
                "selected_thinking_mode": "disabled",
            }

        async def astream(self, payload, *, config, context, stream_mode, version):
            del payload, config, context, stream_mode, version
            if False:
                yield {}

        def get_state(self, _config):
            return SimpleNamespace(values=self.values, interrupts=[])

    background_work = ImmediateBackgroundWork()
    branch_service = LeaseCheckingBranchService()
    runtime = SimpleNamespace(
        settings=Settings(),
        graph=BranchStreamingGraph(),
        repo=repo,
        branch_service=branch_service,
        background_work=background_work,
        coordination_backend=CoordinationBackend(
            thread_turns=locks,
            job_deduper=InMemoryBackgroundJobDeduperBackend(),
            rate_limiter=InMemoryRateLimitBackend(),
        ),
    )
    chat = ChatService(runtime)

    async def collect_frames():
        return [frame async for frame in chat.stream_message(thread_id="child-1", user_id="owner-1", message="hello")]

    frames = asyncio.run(collect_frames())

    assert any("event: turn.completed" in frame for frame in frames)
    assert background_work.submitted[-1] == "chat:branch_title:child-1"
    assert branch_service.calls == [{"child_thread_id": "child-1", "user_id": "owner-1"}]


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
        settings=Settings(sse_heartbeat_seconds=0.01, runtime_thread_lock_ttl_seconds=17.0),
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


def test_stream_message_heartbeats_and_releases_coordination_lock(tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

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

    locks = RecordingThreadLocks()
    runtime = SimpleNamespace(
        settings=SettingsOverlay(
            Settings(sse_heartbeat_seconds=60.0, runtime_thread_lock_ttl_seconds=17.0),
            runtime_thread_lock_heartbeat_seconds=0.01,
        ),
        graph=SlowStreamingGraph(),
        repo=repo,
        branch_service=SimpleNamespace(
            refresh_conversation_title_after_first_turn=lambda **kwargs: None,
            refresh_branch_name_after_first_turn=lambda **kwargs: None,
        ),
        coordination_backend=CoordinationBackend(
            thread_turns=locks,
            job_deduper=InMemoryBackgroundJobDeduperBackend(),
            rate_limiter=InMemoryRateLimitBackend(),
        ),
    )
    chat = ChatService(runtime)

    async def collect_frames():
        return [frame async for frame in chat.stream_message(thread_id="root-1", user_id="owner-1", message="hello")]

    frames = asyncio.run(collect_frames())

    assert not any("event: status" in frame and '"stage": "heartbeat"' in frame for frame in frames)
    assert locks.acquired
    assert locks.heartbeats
    assert locks.acquired[0][2] == 17.0
    assert locks.heartbeats[0][2] == 17.0
    assert locks.released == [("root-1", locks.acquired[0][1])]


def test_stream_message_emits_failed_when_thread_turn_heartbeat_is_lost(tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    class LosingThreadLocks:
        def __init__(self):
            self.acquired: list[tuple[str, str, float]] = []
            self.heartbeats: list[tuple[str, str, float]] = []
            self.released: list[tuple[str, str]] = []

        def acquire_thread_turn(self, *, thread_id: str, owner: str, ttl_seconds: float) -> bool:
            self.acquired.append((thread_id, owner, ttl_seconds))
            return True

        def heartbeat_thread_turn(self, *, thread_id: str, owner: str, ttl_seconds: float) -> bool:
            self.heartbeats.append((thread_id, owner, ttl_seconds))
            return False

        def release_thread_turn(self, *, thread_id: str, owner: str) -> None:
            self.released.append((thread_id, owner))

    class BlockingStreamingGraph:
        def __init__(self):
            self.values = {
                "messages": [],
                "selected_model": "openai:gpt-4.1-mini",
                "selected_thinking_mode": "disabled",
            }

        async def astream(self, payload, *, config, context, stream_mode, version):
            del payload, config, context, stream_mode, version
            await asyncio.sleep(10.0)
            if False:
                yield {}

        def get_state(self, _config):
            return SimpleNamespace(values=self.values, interrupts=[])

    locks = LosingThreadLocks()
    runtime = SimpleNamespace(
        settings=SettingsOverlay(
            Settings(sse_heartbeat_seconds=60.0, runtime_thread_lock_ttl_seconds=9.0),
            runtime_thread_lock_heartbeat_seconds=0.01,
        ),
        graph=BlockingStreamingGraph(),
        repo=repo,
        branch_service=SimpleNamespace(
            refresh_conversation_title_after_first_turn=lambda **kwargs: None,
            refresh_branch_name_after_first_turn=lambda **kwargs: None,
        ),
        coordination_backend=CoordinationBackend(
            thread_turns=locks,
            job_deduper=InMemoryBackgroundJobDeduperBackend(),
            rate_limiter=InMemoryRateLimitBackend(),
        ),
    )
    chat = ChatService(runtime)

    async def collect_frames():
        return [frame async for frame in chat.stream_message(thread_id="root-1", user_id="owner-1", message="hello")]

    async def run_test():
        return await asyncio.wait_for(collect_frames(), timeout=1.0)

    frames = asyncio.run(run_test())

    assert locks.heartbeats
    assert any("event: turn.failed" in frame and "heartbeat was lost" in frame for frame in frames)
    assert not any("event: turn.completed" in frame for frame in frames)
    assert locks.released == [("root-1", locks.acquired[0][1])]


def test_stream_message_releases_coordination_lock_when_client_disconnects(tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    class RecordingThreadLocks:
        def __init__(self):
            self.acquired: list[tuple[str, str, float]] = []
            self.released: list[tuple[str, str]] = []

        def acquire_thread_turn(self, *, thread_id: str, owner: str, ttl_seconds: float) -> bool:
            self.acquired.append((thread_id, owner, ttl_seconds))
            return True

        def heartbeat_thread_turn(self, *, thread_id: str, owner: str, ttl_seconds: float) -> bool:
            return True

        def release_thread_turn(self, *, thread_id: str, owner: str) -> None:
            self.released.append((thread_id, owner))

    class BlockingStreamingGraph:
        def __init__(self):
            self.values = {
                "messages": [],
                "selected_model": "openai:gpt-4.1-mini",
                "selected_thinking_mode": "disabled",
            }

        async def astream(self, payload, *, config, context, stream_mode, version):
            del payload, config, context, stream_mode, version
            await asyncio.sleep(10.0)
            if False:
                yield {}

        def get_state(self, _config):
            return SimpleNamespace(values=self.values, interrupts=[])

    locks = RecordingThreadLocks()
    runtime = SimpleNamespace(
        settings=Settings(sse_heartbeat_seconds=0.01),
        graph=BlockingStreamingGraph(),
        repo=repo,
        branch_service=SimpleNamespace(
            refresh_conversation_title_after_first_turn=lambda **kwargs: None,
            refresh_branch_name_after_first_turn=lambda **kwargs: None,
        ),
        coordination_backend=CoordinationBackend(
            thread_turns=locks,
            job_deduper=InMemoryBackgroundJobDeduperBackend(),
            rate_limiter=InMemoryRateLimitBackend(),
        ),
    )
    chat = ChatService(runtime)

    async def run_test():
        stream = chat.stream_message(thread_id="root-1", user_id="owner-1", message="hello")
        first_frame = await anext(stream)
        assert "event: turn.status" in first_frame
        await stream.aclose()

    asyncio.run(run_test())

    assert locks.acquired
    assert locks.released == [("root-1", locks.acquired[0][1])]


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


def test_stream_message_falls_back_to_sync_stream_when_checkpointer_lacks_async_support(tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    class SyncOnlyCheckpointer:
        aget_tuple = BaseCheckpointSaver.aget_tuple

    class SyncOnlyStreamingGraph:
        def __init__(self):
            self.values = {
                "messages": [AIMessage(content="Hi from sync stream.")],
                "selected_model": "openai:gpt-4.1-mini",
                "selected_thinking_mode": "disabled",
            }

        def stream(self, payload, *, config, context, stream_mode, version):
            del payload, config, context, stream_mode, version
            yield {
                "type": "messages",
                "ns": (),
                "data": (AIMessageChunk(content="Hi"), {"langgraph_node": "agent_loop"}),
            }

        def get_state(self, _config):
            return SimpleNamespace(values=self.values, interrupts=[])

    runtime = SimpleNamespace(
        settings=Settings(),
        graph=SyncOnlyStreamingGraph(),
        repo=repo,
        checkpointer=SyncOnlyCheckpointer(),
        branch_service=SimpleNamespace(
            refresh_conversation_title_after_first_turn=lambda **kwargs: None,
            refresh_branch_name_after_first_turn=lambda **kwargs: None,
        ),
    )
    chat = ChatService(runtime)

    async def collect_frames():
        return [frame async for frame in chat.stream_message(thread_id="root-1", user_id="owner-1", message="hello")]

    frames = asyncio.run(collect_frames())

    assert any("event: visible_text.delta" in frame and '"delta": "Hi"' in frame for frame in frames)
    assert any("event: turn.completed" in frame for frame in frames)


def test_stream_message_keeps_backend_sse_event_names_and_json_safe_payloads(tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    class RichStreamingGraph:
        def __init__(self):
            self.values = {
                "messages": [],
                "selected_model": "openai:gpt-4.1-mini",
                "selected_thinking_mode": "disabled",
            }

        async def astream(self, payload, *, config, context, stream_mode, version):
            del config, context, stream_mode, version
            human = payload["messages"][-1]
            self.values = {
                "messages": [
                    human,
                    AIMessage(content="final answer"),
                ],
                "selected_model": "openai:gpt-4.1-mini",
                "selected_thinking_mode": "disabled",
            }
            yield {
                "type": "messages",
                "ns": ("agent_loop",),
                "data": (
                    AIMessageChunk(content="hello"),
                    {"langgraph_node": "agent_loop", "run_id": "run-1", "secret": "drop-me"},
                ),
            }
            yield {
                "type": "messages",
                "ns": ("agent_loop",),
                "data": (
                    SimpleNamespace(
                        content=[{"type": "reasoning_delta", "text": "thinking"}],
                        type="ai",
                    ),
                    {"langgraph_node": "agent_loop", "run_id": "run-1"},
                ),
            }
            yield {
                "type": "messages",
                "ns": ("agent_loop",),
                "data": (
                    AIMessageChunk(
                        content=[
                            {
                                "type": "tool_call_chunk",
                                "id": "call-1",
                                "name": "search_web",
                                "args": '{"q":"agent"}',
                            }
                        ]
                    ),
                    {"langgraph_node": "agent_loop", "run_id": "run-1"},
                ),
            }
            yield {
                "type": "custom",
                "ns": ("agent_loop",),
                "metadata": {"langgraph_node": "agent_loop", "run_id": "run-1", "secret": "drop-me"},
                "data": {
                    "event": "tool",
                    "stage": "start",
                    "tool_call_id": "call-1",
                    "tool_name": "search_web",
                },
            }
            yield {
                "type": "updates",
                "ns": ("agent_loop",),
                "metadata": {"langgraph_node": "agent_loop", "run_id": "run-1"},
                "data": {
                    "agent_loop": {
                        "messages": [
                            AIMessage(
                                content="",
                                tool_calls=[
                                    {
                                        "id": "call-1",
                                        "name": "search_web",
                                        "args": {"q": "agent"},
                                    }
                                ],
                            ),
                            ToolMessage(
                                content='{"ok":true}',
                                tool_call_id="call-1",
                                name="search_web",
                            ),
                        ]
                    }
                },
            }
            yield {
                "type": "tasks",
                "ns": ("agent_loop",),
                "metadata": {"langgraph_node": "agent_loop", "run_id": "run-1"},
                "data": {"event": "on_task_started", "id": "task-1", "name": "agent_loop"},
            }

        def get_state(self, _config):
            return SimpleNamespace(values=self.values, interrupts=[])

    runtime = SimpleNamespace(
        settings=Settings(),
        graph=RichStreamingGraph(),
        repo=repo,
        branch_service=SimpleNamespace(
            refresh_conversation_title_after_first_turn=lambda **kwargs: None,
            refresh_branch_name_after_first_turn=lambda **kwargs: None,
        ),
    )
    chat = ChatService(runtime)

    async def collect_frames():
        return [frame async for frame in chat.stream_message(thread_id="root-1", user_id="owner-1", message="hello")]

    events = _decode_sse_frames(asyncio.run(collect_frames()))
    names = [event for event, _payload in events]

    assert "visible_text.delta" in names
    assert "message.delta" in names
    assert "reasoning.delta" in names
    assert "tool_call.delta" in names
    assert "tool.call.delta" in names
    assert "tool.start" in names
    assert "tool.requested" in names
    assert "tool.result" in names
    assert "agent.update" in names
    assert "task.started" in names
    assert "visible_text.completed" in names
    assert "message.completed" in names
    assert "reasoning.completed" in names
    assert "turn.completed" in names

    by_name = {event: payload for event, payload in events}
    assert by_name["visible_text.delta"]["metadata"] == {
        "langgraph_node": "agent_loop",
        "run_id": "run-1",
    }
    assert by_name["tool_call.delta"]["id"] == "call-1"
    assert by_name["tool_call.delta"]["name"] == "search_web"
    assert by_name["tool.start"]["tool_call_id"] == "call-1"
    assert by_name["tool.start"]["id"] == "call-1"
    assert by_name["tool.start"]["tool_name"] == "search_web"
    assert by_name["tool.start"]["name"] == "search_web"
    assert by_name["tool.start"]["metadata"] == {
        "langgraph_node": "agent_loop",
        "run_id": "run-1",
    }
    assert by_name["tool.requested"]["tool_call_id"] == "call-1"
    assert by_name["tool.requested"]["id"] == "call-1"
    assert by_name["tool.requested"]["tool_name"] == "search_web"
    assert by_name["tool.requested"]["name"] == "search_web"
    assert by_name["tool.result"]["tool_call_id"] == "call-1"
    assert by_name["tool.result"]["id"] == "call-1"
    assert by_name["tool.result"]["tool_name"] == "search_web"
    assert by_name["tool.result"]["name"] == "search_web"
    assert by_name["agent.update"]["metadata"] == {
        "langgraph_node": "agent_loop",
        "run_id": "run-1",
    }
    assert by_name["task.started"]["metadata"] == {
        "langgraph_node": "agent_loop",
        "run_id": "run-1",
    }


def test_stream_message_keeps_turn_failed_event_name_and_json_safe_payload(tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    class FailingStreamingGraph:
        def __init__(self):
            self.values = {
                "messages": [],
                "selected_model": "openai:gpt-4.1-mini",
                "selected_thinking_mode": "disabled",
            }

        async def astream(self, payload, *, config, context, stream_mode, version):
            del payload, config, context, stream_mode, version
            raise RuntimeError("stream failed for test")
            if False:
                yield {}

        def get_state(self, _config):
            return SimpleNamespace(values=self.values, interrupts=[])

    runtime = SimpleNamespace(
        settings=Settings(),
        graph=FailingStreamingGraph(),
        repo=repo,
    )
    chat = ChatService(runtime)

    async def collect_frames():
        return [frame async for frame in chat.stream_message(thread_id="root-1", user_id="owner-1", message="hello")]

    events = _decode_sse_frames(asyncio.run(collect_frames()))
    by_name = {event: payload for event, payload in events}

    assert "turn.failed" in by_name
    assert by_name["turn.failed"] == {
        "error": "RuntimeError",
        "message": "stream failed for test",
        "thread_id": "root-1",
    }


def test_stream_message_hides_internal_plan_chunks_but_keeps_answer_stream(tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    class PlanThenAnswerGraph:
        def __init__(self):
            self.values = {
                "messages": [AIMessage(content="真正回答会继续流式输出。")],
                "selected_model": "openai:gpt-4.1-mini",
                "selected_thinking_mode": "disabled",
            }

        async def astream(self, payload, *, config, context, stream_mode, version):
            del payload, config, context, stream_mode, version
            yield {
                "type": "messages",
                "ns": (),
                "data": (
                    AIMessageChunk(content='{"steps":[{"expected_tools":["web_search"]}]}'),
                    {"langgraph_node": "plan"},
                ),
            }
            yield {
                "type": "messages",
                "ns": (),
                "data": (
                    AIMessageChunk(content='{"status":"replan","missing":["final answer"]}'),
                    {"langgraph_node": "reflect"},
                ),
            }
            yield {
                "type": "messages",
                "ns": (),
                "data": (
                    AIMessageChunk(content="真正回答"),
                    {"langgraph_node": "agent_loop"},
                ),
            }

        def get_state(self, _config):
            return SimpleNamespace(values=self.values, interrupts=[])

    runtime = SimpleNamespace(
        settings=Settings(),
        graph=PlanThenAnswerGraph(),
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

    visible_frames = [frame for frame in frames if "event: visible_text.delta" in frame]
    assert not any("expected_tools" in frame for frame in visible_frames)
    assert not any('"status":"replan"' in frame for frame in visible_frames)
    assert any('"delta": "真正回答"' in frame for frame in visible_frames)


def test_stream_message_completed_prefers_final_ai_over_stale_visible_buffer(tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    class DraftThenFinalGraph:
        def __init__(self):
            self.values = {
                "messages": [],
                "selected_model": "openai:gpt-4.1-mini",
                "selected_thinking_mode": "disabled",
            }

        async def astream(self, payload, *, config, context, stream_mode, version):
            del config, context, stream_mode, version
            human = payload["messages"][-1]
            self.values = {
                "messages": [
                    human,
                    AIMessage(content="最终回答会保留下来。"),
                ],
                "selected_model": "openai:gpt-4.1-mini",
                "selected_thinking_mode": "disabled",
            }
            yield {
                "type": "messages",
                "ns": (),
                "data": (
                    AIMessageChunk(content="旧草稿不应该成为 completed 内容。"),
                    {"langgraph_node": "agent_loop"},
                ),
            }

        def get_state(self, _config):
            return SimpleNamespace(values=self.values, interrupts=[])

    runtime = SimpleNamespace(
        settings=Settings(),
        graph=DraftThenFinalGraph(),
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
    completed_frames = [frame for frame in frames if "event: visible_text.completed" in frame]

    assert any("最终回答会保留下来。" in frame for frame in completed_frames)
    assert not any("旧草稿不应该成为 completed 内容。" in frame for frame in completed_frames)


def test_stream_message_hides_tool_result_fallback_draft_chunks(tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    class FallbackDraftGraph:
        def __init__(self):
            self.values = {
                "messages": [AIMessage(content="最终中文回答。")],
                "selected_model": "openai:gpt-4.1-mini",
                "selected_thinking_mode": "disabled",
            }

        async def astream(self, payload, *, config, context, stream_mode, version):
            del payload, config, context, stream_mode, version
            yield {
                "type": "messages",
                "ns": (),
                "data": (
                    AIMessageChunk(content="我先根据已拿到的工具结果给出一个保守整理：\n- web_search: interim"),
                    {"langgraph_node": "agent_loop"},
                ),
            }

        def get_state(self, _config):
            return SimpleNamespace(values=self.values, interrupts=[])

    runtime = SimpleNamespace(
        settings=Settings(),
        graph=FallbackDraftGraph(),
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
    visible_frames = [frame for frame in frames if "event: visible_text.delta" in frame]

    assert not any("保守整理" in frame for frame in visible_frames)


def test_stream_message_hides_bare_tool_call_close_tag_from_visible_events(tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    class BareToolCloseTagGraph:
        def __init__(self):
            self.values = {
                "messages": [],
                "selected_model": "mimo:mimo-v2.5-pro",
                "selected_thinking_mode": "enabled",
            }

        async def astream(self, payload, *, config, context, stream_mode, version):
            del config, context, stream_mode, version
            human = payload["messages"][-1]
            self.values = {
                "messages": [human, AIMessage(content="</tool_call>")],
                "selected_model": "mimo:mimo-v2.5-pro",
                "selected_thinking_mode": "enabled",
            }
            yield {
                "type": "messages",
                "ns": (),
                "data": (
                    AIMessageChunk(content="</tool_call>"),
                    {"langgraph_node": "agent_loop"},
                ),
            }

        def get_state(self, _config):
            return SimpleNamespace(values=self.values, interrupts=[])

    runtime = SimpleNamespace(
        settings=Settings(),
        graph=BareToolCloseTagGraph(),
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
    visible_frames = [
        frame
        for frame in frames
        if (
            "event: visible_text.delta" in frame
            or "event: message.delta" in frame
            or "event: visible_text.completed" in frame
            or "event: message.completed" in frame
        )
    ]

    assert not any("</tool_call>" in frame for frame in visible_frames)
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


def test_send_message_skips_post_turn_side_effects_when_thread_turn_heartbeat_is_lost(tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    class LosingThreadLocks:
        def __init__(self):
            self.acquired: list[tuple[str, str, float]] = []
            self.heartbeats: list[tuple[str, str, float]] = []
            self.released: list[tuple[str, str]] = []

        def acquire_thread_turn(self, *, thread_id: str, owner: str, ttl_seconds: float) -> bool:
            self.acquired.append((thread_id, owner, ttl_seconds))
            return True

        def heartbeat_thread_turn(self, *, thread_id: str, owner: str, ttl_seconds: float) -> bool:
            self.heartbeats.append((thread_id, owner, ttl_seconds))
            return False

        def release_thread_turn(self, *, thread_id: str, owner: str) -> None:
            self.released.append((thread_id, owner))

    class SlowInvokeGraph:
        def __init__(self):
            self.values = {}

        def invoke(self, payload, *, config, context, version):
            del config, context, version
            time.sleep(0.03)
            self.values = {
                "messages": [payload["messages"][-1], AIMessage(content="done")],
                "selected_model": payload["selected_model"],
                "selected_thinking_mode": payload["selected_thinking_mode"],
            }
            return {}

        def get_state(self, _config):
            return SimpleNamespace(values=self.values, interrupts=[])

    class RecordingBackgroundWork:
        def __init__(self):
            self.submitted: list[str] = []

        def submit(self, *, key, func, delay_seconds=0.0, **kwargs):
            del func, delay_seconds, kwargs
            self.submitted.append(key)
            return True

        def release_job_key(self, key: str) -> None:
            del key

    locks = LosingThreadLocks()
    background_work = RecordingBackgroundWork()
    runtime = SimpleNamespace(
        settings=SettingsOverlay(
            Settings(runtime_thread_lock_ttl_seconds=9.0),
            runtime_thread_lock_heartbeat_seconds=0.01,
        ),
        graph=SlowInvokeGraph(),
        repo=repo,
        background_work=background_work,
        coordination_backend=CoordinationBackend(
            thread_turns=locks,
            job_deduper=InMemoryBackgroundJobDeduperBackend(),
            rate_limiter=InMemoryRateLimitBackend(),
        ),
    )
    chat = ChatService(runtime)

    with pytest.raises(ConcurrentTurnError, match="heartbeat was lost"):
        chat.send_message(thread_id="root-1", user_id="owner-1", message="hello")

    assert locks.heartbeats
    assert background_work.submitted == []
    assert locks.released == [("root-1", locks.acquired[0][1])]


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
        model="moonshot:kimi-k2.6",
        thinking_mode="disabled",
    )

    assert graph.last_context.skill_hints == ("plan",)
    assert graph.last_payload["task_brief"] == "map the rollout"
    assert graph.last_payload["active_skill_ids"] == ["plan"]
    assert graph.last_payload["selected_model"] == "moonshot:kimi-k2.6"
    assert graph.last_payload["selected_thinking_mode"] == "disabled"
    assert payload["active_skill_ids"] == ["plan"]
    assert payload["selected_model"] == "moonshot:kimi-k2.6"
    assert payload["selected_thinking_mode"] == "disabled"


def test_send_message_ignores_thinking_mode_for_models_without_thinking_support(tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    graph = RecordingGraph()
    runtime = SimpleNamespace(
        settings=Settings(
            model="ollama:gemma4-hauhau:q8",
            model_catalog=ModelCatalogConfig(
                models=(
                    ConfiguredModel(
                        id="ollama:gemma4-hauhau:q8",
                        label="gemma4-hauhau:q8",
                    ),
                ),
            ),
        ),
        graph=graph,
        repo=repo,
    )
    chat = ChatService(runtime)

    payload = chat.send_message(
        thread_id="root-1",
        user_id="owner-1",
        message="hello",
        model="ollama:gemma4-hauhau:q8",
        thinking_mode="enabled",
    )

    assert graph.last_payload["selected_model"] == "ollama:gemma4-hauhau:q8"
    assert graph.last_payload["selected_thinking_mode"] == ""
    assert payload["selected_model"] == "ollama:gemma4-hauhau:q8"
    assert payload["selected_thinking_mode"] == ""


def test_send_message_uses_runtime_model_catalog_for_custom_thinking_model(tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    graph = RecordingGraph()
    runtime = SimpleNamespace(
        settings=Settings(
            model="openai:custom-reasoning-pro",
            model_catalog=ModelCatalogConfig(
                models=(
                    ConfiguredModel(
                        id="openai:custom-reasoning-pro",
                        label="Custom Reasoning Pro",
                        supports_thinking=True,
                        default_thinking_enabled=True,
                    ),
                ),
            ),
        ),
        graph=graph,
        repo=repo,
    )
    chat = ChatService(runtime)

    payload = chat.send_message(
        thread_id="root-1",
        user_id="owner-1",
        message="hello",
        model="openai:custom-reasoning-pro",
    )

    assert graph.last_payload["selected_model"] == "openai:custom-reasoning-pro"
    assert graph.last_payload["selected_thinking_mode"] == "enabled"
    assert payload["selected_model"] == "openai:custom-reasoning-pro"
    assert payload["selected_thinking_mode"] == "enabled"


def test_send_message_records_postgres_trajectory_payload(tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    class ToolGraph:
        def __init__(self):
            self.values = {}

        def invoke(self, payload, *, config, context, version):
            del config, context, version
            human = payload["messages"][-1]
            self.values = {
                "messages": [
                    human,
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "id": "tool-1",
                                "name": "read_file",
                                "args": {"path": "README.md"},
                            }
                        ],
                    ),
                    ToolMessage(
                        content="Focus Agent",
                        tool_call_id="tool-1",
                        artifact={
                            "runtime": {
                                "cache_hit": True,
                                "fallback_used": False,
                                "parallel_batch_size": 2,
                            }
                        },
                    ),
                    AIMessage(content="done"),
                ],
                "llm_calls": 2,
                "task_brief": payload["task_brief"],
                "selected_model": payload["selected_model"],
                "selected_thinking_mode": payload["selected_thinking_mode"],
            }
            return {}

        def get_state(self, _config):
            return SimpleNamespace(values=self.values, interrupts=[])

    class RecordingTrajectoryRecorder:
        def __init__(self):
            self.records = []

        def record_turn(self, record):
            self.records.append(record)

    recorder = RecordingTrajectoryRecorder()
    runtime = SimpleNamespace(
        settings=Settings(
            trajectory_observation_max_chars=20,
            trajectory_answer_max_chars=20,
        ),
        graph=ToolGraph(),
        repo=repo,
        trajectory_recorder=recorder,
    )
    chat = ChatService(runtime)

    payload = chat.send_message(
        thread_id="root-1",
        user_id="owner-1",
        message="read README",
        request_id="req-chat-turn",
    )

    assert len(recorder.records) == 1
    record = recorder.records[0]
    assert payload["trace"]["metadata"]["request_id"] == "req-chat-turn"
    assert payload["trace"]["metadata"]["trace_id"] == record.trace_id
    assert record.kind == "chat.turn"
    assert record.status == "succeeded"
    assert record.thread_id == "root-1"
    assert record.request_id == "req-chat-turn"
    assert record.trace_id
    assert record.root_span_id
    assert record.user_id_hash != "owner-1"
    assert record.user_message == "read README"
    assert record.answer == "done"
    assert [step.tool for step in record.trajectory] == ["read_file"]
    assert record.trajectory[0].cache_hit is True
    assert record.trajectory[0].parallel_batch_size == 2
    assert record.metrics["tool_calls"] == 1
    assert record.metrics["llm_calls"] == 2


def test_stream_message_records_trajectory_after_completion(tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    class StreamingGraph:
        def __init__(self):
            self.values = {"messages": [AIMessage(content="previous")], "llm_calls": 1}

        async def astream(self, payload, *, config, context, stream_mode, version):
            del config, context, stream_mode, version
            human = payload["messages"][-1]
            self.values = {
                "messages": [
                    AIMessage(content="previous"),
                    human,
                    AIMessage(content="streamed answer"),
                ],
                "llm_calls": 2,
                "task_brief": payload["task_brief"],
                "selected_model": payload["selected_model"],
                "selected_thinking_mode": payload["selected_thinking_mode"],
            }
            if False:
                yield {}

        def get_state(self, _config):
            return SimpleNamespace(values=self.values, interrupts=[])

    class RecordingTrajectoryRecorder:
        def __init__(self):
            self.records = []

        def record_turn(self, record):
            self.records.append(record)

    recorder = RecordingTrajectoryRecorder()
    runtime = SimpleNamespace(
        settings=Settings(),
        graph=StreamingGraph(),
        repo=repo,
        branch_service=SimpleNamespace(
            refresh_conversation_title_after_first_turn=lambda **kwargs: None,
            refresh_branch_name_after_first_turn=lambda **kwargs: None,
        ),
        trajectory_recorder=recorder,
    )
    chat = ChatService(runtime)

    async def collect_frames():
        return [
            frame
            async for frame in chat.stream_message(
                thread_id="root-1",
                user_id="owner-1",
                message="new",
                request_id="req-stream-turn",
            )
        ]

    frames = asyncio.run(collect_frames())

    assert any("event: turn.completed" in frame for frame in frames)
    assert len(recorder.records) == 1
    assert recorder.records[0].request_id == "req-stream-turn"
    assert recorder.records[0].trace_id
    assert recorder.records[0].answer == "streamed answer"
    assert recorder.records[0].user_message == "new"
    assert recorder.records[0].metrics["llm_calls"] == 1


def test_trajectory_recorder_failure_does_not_fail_turn(tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")
    graph = RecordingGraph()

    class BrokenTrajectoryRecorder:
        def record_turn(self, record):
            del record
            raise RuntimeError("postgres unavailable")

    runtime = SimpleNamespace(
        settings=Settings(),
        graph=graph,
        repo=repo,
        trajectory_recorder=BrokenTrajectoryRecorder(),
    )
    chat = ChatService(runtime)

    payload = chat.send_message(
        thread_id="root-1",
        user_id="owner-1",
        message="hello",
        request_id="req-thread-state",
    )

    assert payload["assistant_message"] == "planned"
    assert payload["trace"]["metadata"]["request_id"] == "req-thread-state"


def test_serialize_message_keeps_usage_metadata():
    service = ChatService(ChatServicePorts(settings=Settings(), graph=FakeGraph(), repo=SimpleNamespace()))

    payload = service._serialize_message(
        AIMessage(
            content="done",
            usage_metadata={"input_tokens": 21, "output_tokens": 9, "total_tokens": 30},
        )
    )

    assert payload["content"] == "done"
    assert payload["usage_metadata"]["total_tokens"] == 30
    assert payload["usage_metadata"]["input_tokens"] == 21


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

    payload = chat.get_thread_state(
        thread_id="root-1",
        user_id="owner-1",
        request_id="req-snapshot",
    )

    system_messages = [message for message in payload["messages"] if message["type"] == "system"]
    assert system_messages
    assert payload["trace"]["metadata"]["request_id"] == "req-snapshot"
    assert "Imported conclusion from branch 'explore-alternatives':" in system_messages[-1]["content"]
    assert "Recovered conclusion from child branch." in system_messages[-1]["content"]
    assert payload["rolling_summary"].endswith(
        "Imported from explore-alternatives: Recovered conclusion from child branch."
    )
    assert graph.updates
    assert graph.updates[0][1] == "bootstrap_turn"


def test_get_thread_state_returns_longer_recent_history_window(tmp_path: Path):
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
    chat = ChatService(runtime)

    payload = chat.get_thread_state(thread_id="root-1", user_id="owner-1")

    assert len(payload["messages"]) == 60
    assert payload["messages"][0]["content"] == "message-0"
    assert payload["messages"][-1]["content"] == "message-59"


def test_get_thread_state_caps_history_window_for_large_threads(tmp_path: Path):
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
    chat = ChatService(runtime)

    payload = chat.get_thread_state(thread_id="root-1", user_id="owner-1")

    assert len(payload["messages"]) == chat._THREAD_STATE_MESSAGE_LIMIT
    assert payload["messages"][0]["content"] == "message-50"
    assert payload["messages"][-1]["content"] == "message-249"
