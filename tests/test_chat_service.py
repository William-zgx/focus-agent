import json
from pathlib import Path
from types import SimpleNamespace
import threading
import time

import pytest
from langchain.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

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


def test_sse_frame_serializes_message_objects():
    frame = ChatService._sse_frame(
        event="state.update",
        data={"messages": [HumanMessage(content="hello")]},
    )

    assert 'event: state.update' in frame
    assert '"content": "hello"' in frame


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


def test_latest_final_ai_text_hides_english_process_narration():
    service = ChatService(ChatServicePorts(settings=Settings(), graph=FakeGraph(), repo=SimpleNamespace()))

    assert (
        service._latest_final_ai_text(
            [
                AIMessage(content="确认可见的最终答案。"),
                AIMessage(content="Let me fetch the data first. I should look for: filings and price action."),
            ]
        )
        == "确认可见的最终答案。"
    )
    assert (
        service._latest_final_ai_text(
            [
                AIMessage(
                    content=(
                        "Wait, if the current date is 2026-05-10, "
                        "I should check one more source before answering."
                    )
                )
            ]
        )
        is None
    )
    assert (
        service._latest_final_ai_text(
            [
                AIMessage(content="Let me produce the final answer. Final answer: 这才是最终答案。"),
            ]
        )
        == "这才是最终答案。"
    )


def test_thread_state_messages_hide_textual_tool_protocol_ai_messages():
    service = ChatService(ChatServicePorts(settings=Settings(), graph=FakeGraph(), repo=SimpleNamespace()))

    payload = service._thread_state_messages(
        [
            HumanMessage(content="Search this."),
            AIMessage(
                content='="read="filepath" string="true">tool-observation://webfetch/call00ljJOwoeUmsjmBzMNhkx8505'
            ),
            AIMessage(content="最终安全回答。"),
        ]
    )

    assert [message["type"] for message in payload] == ["human", "ai"]
    assert [message["content"] for message in payload] == ["Search this.", "最终安全回答。"]


def test_thread_state_messages_hide_english_process_narration():
    service = ChatService(ChatServicePorts(settings=Settings(), graph=FakeGraph(), repo=SimpleNamespace()))

    payload = service._thread_state_messages(
        [
            HumanMessage(content="Search this."),
            AIMessage(content="Let me fetch the data first. I should look for: filings and price action."),
            AIMessage(
                content=(
                    "Wait, if the current date is 2026-05-10, "
                    "I should check one more source before answering."
                )
            ),
            SimpleNamespace(
                type="ai",
                content="I should call a tool before answering.",
                tool_calls=[{"id": "call-1", "name": "web_search", "args": {"q": "focus agent"}}],
                name=None,
                id="ai-tool-call",
                usage_metadata=None,
            ),
            AIMessage(content="Let me produce the final answer. Final answer: 这才是最终答案。"),
        ]
    )

    assert [message["type"] for message in payload] == ["human", "ai", "ai"]
    assert [message["content"] for message in payload] == ["Search this.", "", "这才是最终答案。"]
    assert payload[1]["tool_calls"][0]["name"] == "web_search"


def test_thread_state_messages_extract_visible_list_content_only():
    service = ChatService(ChatServicePorts(settings=Settings(), graph=FakeGraph(), repo=SimpleNamespace()))

    payload = service._thread_state_messages(
        [
            AIMessage(
                content=[
                    {"type": "reasoning", "text": "hidden reasoning"},
                    {"type": "input_text", "text": "hidden prompt"},
                    {"type": "tool_call", "text": '{"name":"web_search"}'},
                    {"type": "output_text", "text": "可见最终答案。"},
                ]
            )
        ]
    )

    assert len(payload) == 1
    assert payload[0]["content"] == "可见最终答案。"
    assert "hidden" not in payload[0]["content"]
    assert "web_search" not in payload[0]["content"]


def test_thread_state_messages_clear_protocol_content_but_keep_tool_calls():
    service = ChatService(ChatServicePorts(settings=Settings(), graph=FakeGraph(), repo=SimpleNamespace()))

    payload = service._thread_state_messages(
        [
            SimpleNamespace(
                type="ai",
                content='="read="filepath" string="true">tool-observation://webfetch/call-1',
                tool_calls=[{"id": "call-1", "name": "web_fetch", "args": {"url": "https://example.com"}}],
                name=None,
                id="ai-tools",
                usage_metadata=None,
            )
        ]
    )

    assert len(payload) == 1
    assert payload[0]["content"] == ""
    assert payload[0]["tool_calls"][0]["name"] == "web_fetch"


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
