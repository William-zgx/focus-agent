import asyncio
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from focus_agent.api.routers.harness_runs import _produce_run_stream
from focus_agent.branch_decision import BranchDecisionService
from focus_agent.config import ConfiguredModel, ModelCatalogConfig, Settings
from focus_agent.core.branching import (
    BranchActionKind,
    BranchActionNavigation,
    BranchMeta,
    BranchRecord,
    BranchRole,
    BranchStatus,
)
from focus_agent.core.request_context import RequestContext
from focus_agent.repositories.governance_repository import InMemoryGovernanceRepository
from focus_agent.repositories.sqlite_branch_repository import SQLiteBranchRepository
from focus_agent.services.branch_actions import (
    branch_handoff_message_from_text,
    build_branch_action_proposal,
    infer_suggested_branch_name,
    is_branch_action_dismissal,
    is_branch_action_request,
    mark_branch_action_executed,
)
from focus_agent.services.chat import (
    ChatService,
    ChatServicePorts,
    ConcurrentTurnError,
    ThreadStateUnavailableError,
)
from focus_agent.services.chat.branch_actions import branch_action_intent
from focus_agent.services.coordination import (
    CoordinationBackend,
    InMemoryBackgroundJobDeduperBackend,
    InMemoryRateLimitBackend,
    InMemoryThreadTurnLockBackend,
    create_in_memory_coordination_backend,
)
from focus_agent.services.thread_turn_lease import ThreadTurnLeaseManager
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
            self.values["messages"] = list(self.values.get("messages", [])) + list(
                values["messages"]
            )
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
            self.values["messages"] = list(self.values.get("messages", [])) + list(
                values["messages"]
            )
        for key, value in values.items():
            if key != "messages":
                self.values[key] = value


class BranchRecommendationGraph(BranchActionGraph):
    def __init__(self, values: dict[str, object] | None = None):
        super().__init__(values)
        self.invoke_calls = 0
        self.last_payload = None

    def invoke(self, payload, *, config, context, version):
        del config, context, version
        self.invoke_calls += 1
        self.last_payload = payload
        self.values["messages"] = list(self.values.get("messages", [])) + [
            *list(payload.get("messages", [])),
            AIMessage(content="normal answer"),
        ]
        self.values["selected_model"] = payload.get("selected_model", "")
        self.values["selected_thinking_mode"] = payload.get("selected_thinking_mode", "")
        return {}


class StaleBranchRecommendationGraph(BranchRecommendationGraph):
    def update_state(self, _config, values, as_node=None):
        self.updates.append((values, as_node))
        if "messages" in values:
            self.values["messages"] = list(self.values.get("messages", [])) + list(
                values["messages"]
            )
        if "branch_actions" in values and "messages" in values:
            self.values["branch_actions"] = values["branch_actions"]
        if "branch_action_audit" in values and "messages" in values:
            self.values["branch_action_audit"] = values["branch_action_audit"]


class MultiThreadBranchActionGraph:
    def __init__(self, values_by_thread: dict[str, dict[str, object]] | None = None):
        self.values_by_thread = values_by_thread or {}
        self.updates: list[tuple[str, dict[str, object], str | None]] = []

    @staticmethod
    def _thread_id(config) -> str:
        return str((config or {}).get("configurable", {}).get("thread_id") or "")

    def get_state(self, config):
        return SimpleNamespace(
            values=self.values_by_thread.setdefault(self._thread_id(config), {}),
            interrupts=[],
        )

    def update_state(self, config, values, as_node=None):
        thread_id = self._thread_id(config)
        self.updates.append((thread_id, values, as_node))
        state = self.values_by_thread.setdefault(thread_id, {})
        if "messages" in values:
            state["messages"] = list(state.get("messages", [])) + list(values["messages"])
        for key, value in values.items():
            if key != "messages":
                state[key] = value


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


def _repo_with_merged_branch(tmp_path: Path) -> SQLiteBranchRepository:
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
    return repo


def _chat_for_repo(
    repo: SQLiteBranchRepository,
    *,
    graph: object | None = None,
    settings: Settings | None = None,
    **ports: object,
) -> ChatService:
    return ChatService(
        SimpleNamespace(
            settings=settings or Settings(),
            graph=graph or FakeGraph(),
            repo=repo,
            **ports,
        )
    )


def _branch_recommendation_service(settings: Settings, graph: object) -> BranchDecisionService:
    return BranchDecisionService(
        settings=settings,
        graph=graph,
        governance_repository=InMemoryGovernanceRepository(),
        coordination_backend=create_in_memory_coordination_backend(),
    )


def test_chat_service_accepts_narrow_ports(tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")
    ports = ChatServicePorts(settings=Settings(), graph=FakeGraph(), repo=repo)
    chat = ChatService(ports)

    payload = chat.get_thread_state(thread_id="root-1", user_id="owner-1")

    assert payload["thread_id"] == "root-1"
    assert chat.ports is ports


def test_get_thread_state_does_not_mask_snapshot_read_failure(tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    class BrokenGraph:
        def get_state(self, _config):
            raise RuntimeError("graph unavailable")

    chat = ChatService(ChatServicePorts(settings=Settings(), graph=BrokenGraph(), repo=repo))

    with pytest.raises(ThreadStateUnavailableError):
        chat.get_thread_state(thread_id="root-1", user_id="owner-1")


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
    assert (
        payload["branch_actions"][0]["handoff_message"] == "你觉得华英农业下周会是什么样的走势呀？"
    )
    assert "华英农业" in payload["branch_actions"][0]["suggested_branch_name"]
    assert "已创建" not in payload["assistant_message"]
    assert graph.updates[-1][1] == "bootstrap_turn"


def test_send_message_defaults_generic_new_branch_to_child_branch(tmp_path: Path):
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
    chat = ChatService(runtime)

    payload = chat.send_message(
        thread_id="child-1",
        user_id="owner-1",
        message="新建分支，探索一下今天包车东线的时间段分配。",
    )

    assert payload["branch_actions"][0]["kind"] == "fork_child_branch"
    assert payload["branch_actions"][0]["target_parent_thread_id"] == "child-1"
    assert payload["branch_actions"][0]["handoff_message"] == "探索一下今天包车东线的时间段分配"


def test_send_message_pre_turn_recommendation_creates_child_card_without_invoke(
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
    chat = ChatService(runtime)

    payload = chat.send_message(
        thread_id="root-1",
        user_id="owner-1",
        message="深入细化一下下午东线每个时间段的安排。",
    )

    assert graph.invoke_calls == 0
    assert payload["branch_actions"][0]["kind"] == "fork_child_branch"
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
    assert "确认项" in payload["assistant_message"]


def test_send_message_pre_turn_recommendation_survives_stale_checkpoint_read(
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
    chat = ChatService(runtime)

    payload = chat.send_message(
        thread_id="root-1",
        user_id="owner-1",
        message="深入细化一下下午东线每个时间段的安排。",
    )

    assert graph.invoke_calls == 0
    assert payload["branch_actions"][0]["source"] == "branch_decision"
    assert payload["branch_actions"][0]["status"] == "pending"
    assert graph.values["branch_actions"][0]["action_id"] == payload["branch_actions"][0][
        "action_id"
    ]
    assert "确认项" in payload["assistant_message"]
    assert "branch_actions" in graph.updates[-1][0]
    assert "messages" in graph.updates[-1][0]


def test_send_message_pre_turn_recommendation_uses_thread_turn_lock(tmp_path: Path):
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
    chat = ChatService(runtime)

    chat._acquire_thread_turn(thread_id="root-1")
    try:
        with pytest.raises(ConcurrentTurnError, match="still processing the previous turn"):
            chat.send_message(
                thread_id="root-1",
                user_id="owner-1",
                message="深入细化一下下午东线每个时间段的安排。",
            )
    finally:
        chat._release_thread_turn(thread_id="root-1")

    assert graph.invoke_calls == 0
    assert "branch_actions" not in graph.values


def test_send_message_pre_turn_recommendation_creates_sibling_card_from_child(
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
    chat = ChatService(runtime)

    payload = chat.send_message(
        thread_id="child-1",
        user_id="owner-1",
        message="换个方向并行探索东线备用方案。",
    )

    assert graph.invoke_calls == 0
    assert payload["branch_actions"][0]["kind"] == "fork_sibling_branch"
    assert payload["branch_actions"][0]["target_parent_thread_id"] == "root-1"
    assert (
        payload["branch_decision_summary"]["latest_decision"]["recommendation_target"]
        == "fork_sibling_branch"
    )


def test_pre_turn_recommendation_execution_carries_question_to_sibling_branch(
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
    chat = ChatService(runtime)

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


def test_send_message_pre_turn_continue_recommendation_invokes_normally(tmp_path: Path):
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
    chat = ChatService(runtime)

    payload = chat.send_message(
        thread_id="root-1",
        user_id="owner-1",
        message="不用分支，继续回答这个问题。",
    )

    assert graph.invoke_calls == 1
    assert payload["branch_actions"] == []
    assert payload["assistant_message"] == "normal answer"


def test_send_message_pre_turn_shadow_recommendation_audits_without_card(tmp_path: Path):
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
    chat = ChatService(runtime)

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


def test_branch_action_execution_keeps_auto_name_pending_for_first_turn_refresh(tmp_path: Path):
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
    action_id = graph.values["branch_actions"][0]["action_id"]

    chat.execute_branch_action(thread_id="child-1", action_id=action_id, user_id="owner-1")

    assert branch_service.fork_calls[-1]["branch_name"] is None
    assert "华英农业" in branch_service.fork_calls[-1]["name_source"]


def test_branch_action_execution_uses_explicit_branch_title(tmp_path: Path):
    repo = _repo_with_child_branch(tmp_path)
    graph = BranchActionGraph({"messages": [HumanMessage(content="根线程里的基础上下文。")]})
    branch_service = BranchActionBranchService()
    runtime = SimpleNamespace(
        settings=Settings(),
        graph=graph,
        repo=repo,
        branch_service=branch_service,
    )
    chat = ChatService(runtime)

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


def test_branch_action_execution_carries_source_question_to_sibling_branch(tmp_path: Path):
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
    chat = ChatService(runtime)

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


def test_branch_action_execution_carries_inline_question_to_child_branch(tmp_path: Path):
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
    chat = ChatService(runtime)

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


def test_branch_action_execution_marks_copied_child_action_executed(tmp_path: Path):
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
    chat = ChatService(runtime)

    chat.send_message(thread_id="child-1", user_id="owner-1", message="帮我切换一个同级分支吧。")
    action_id = graph.values_by_thread["child-1"]["branch_actions"][0]["action_id"]
    chat.execute_branch_action(thread_id="child-1", action_id=action_id, user_id="owner-1")

    child_actions = graph.values_by_thread["child-new"]["branch_actions"]
    assert child_actions[0]["action_id"] == action_id
    assert child_actions[0]["status"] == "executed"
    assert child_actions[0]["navigation"]["thread_id"] == "child-new"


def test_branch_thread_state_hides_copied_branch_creation_turn():
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
    chat = ChatService(ChatServicePorts(settings=Settings(), graph=graph, repo=SimpleNamespace()))

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


def test_branch_thread_state_hides_copied_recommendation_handoff_after_auto_run():
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
    chat = ChatService(ChatServicePorts(settings=Settings(), graph=graph, repo=SimpleNamespace()))

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


def test_branch_thread_state_hides_copied_terminal_handoff_after_auto_run():
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
    chat = ChatService(ChatServicePorts(settings=Settings(), graph=graph, repo=SimpleNamespace()))

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


def test_branch_thread_state_hides_local_duplicate_handoff_before_answer():
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
    chat = ChatService(ChatServicePorts(settings=Settings(), graph=graph, repo=SimpleNamespace()))

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


def test_branch_thread_state_does_not_drop_messages_when_fork_count_is_stale():
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
    chat = ChatService(ChatServicePorts(settings=Settings(), graph=graph, repo=SimpleNamespace()))

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
    assert branch_action_intent(
        values={"branch_actions": [pending.model_dump(mode="json")]},
        message=message,
    ) is None
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
    chat = _chat_for_repo(_repo_with_merged_branch(tmp_path))

    with pytest.raises(PermissionError, match="Merged branches are read-only."):
        chat.send_message(thread_id="child-merged", user_id="owner-1", message="hello")


def test_send_message_rejects_merged_branch_when_graph_meta_is_stale(tmp_path: Path):
    chat = _chat_for_repo(_repo_with_merged_branch(tmp_path), graph=StaleBranchMetaGraph())

    with pytest.raises(PermissionError, match="Merged branches are read-only."):
        chat.send_message(thread_id="child-merged", user_id="owner-1", message="hello")


def test_compact_thread_context_rejects_merged_branch(tmp_path: Path):
    chat = _chat_for_repo(_repo_with_merged_branch(tmp_path))

    with pytest.raises(PermissionError, match="Merged branches are read-only."):
        chat.compact_thread_context(thread_id="child-merged", user_id="owner-1")


def test_preview_thread_context_increases_with_draft_message(tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    class ContextPreviewGraph:
        def get_state(self, _config):
            return SimpleNamespace(
                values={
                    "messages": [
                        HumanMessage(content="Known context"),
                        AIMessage(content="Known answer"),
                    ],
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
                "user_constraints": [
                    {"constraint": "Keep token usage separate from context usage."}
                ],
                "artifacts": [
                    {
                        "title": "Context usage decision",
                        "uri": "artifact://context/usage-decision",
                    }
                ],
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
    drift_report = graph.values["context_compaction"]["context_compaction_drift_report"]
    assert set(drift_report) >= {
        "recall",
        "precision",
        "grounding",
        "answerability",
        "overall_drift",
    }
    assert drift_report["drift_risk"] in {"low", "medium", "high"}
    assert "Context compaction snapshot:" in graph.values["rolling_summary"]
    assert "artifact://context/usage-decision" in graph.values["rolling_summary"]
    assert (
        payload["context_usage"]["last_compacted_at"]
        == graph.values["context_compaction"]["last_compacted_at"]
    )


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

    chat._schedule_post_turn_context_compaction(
        thread_id="root-1", user_id="owner-1", kind="chat.turn"
    )
    chat._schedule_post_turn_context_compaction(
        thread_id="root-2", user_id="owner-1", kind="chat.resume"
    )

    assert background_work.submitted == []
    assert [(spec.kind, spec.key, spec.payload) for spec in job_deduper.enqueued] == [
        (
            "context_compaction",
            "chat:context_compaction:root-1",
            {
                "thread_id": "root-1",
                "user_id": "owner-1",
                "trigger": "auto_post_turn",
                "force": False,
            },
        ),
        (
            "context_compaction",
            "chat:context_compaction:root-2",
            {
                "thread_id": "root-2",
                "user_id": "owner-1",
                "trigger": "auto_post_turn",
                "force": False,
            },
        ),
    ]
    assert all(spec.max_attempts == 3 for spec in job_deduper.enqueued)
    assert all(spec.dedupe_policy == "replace" for spec in job_deduper.enqueued)


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
    chat._schedule_branch_name_refresh_after_first_turn(
        thread_id="root-resume",
        user_id="owner-1",
        branch_meta=None,
        kind="chat.resume",
    )
    chat._schedule_branch_name_refresh_after_first_turn(
        thread_id="child-resume",
        user_id="owner-1",
        branch_meta=BranchMeta(
            branch_id="branch-resume",
            root_thread_id="root-resume",
            parent_thread_id="root-resume",
            return_thread_id="root-resume",
            branch_name="Resume Deep Dive",
            branch_role=BranchRole.DEEP_DIVE,
            branch_depth=1,
        ),
        kind="chat.resume",
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
        (
            "conversation_title",
            "chat:conversation_title:root-resume",
            {"root_thread_id": "root-resume", "user_id": "owner-1"},
        ),
        (
            "branch_title",
            "chat:branch_title:child-resume",
            {"child_thread_id": "child-resume", "user_id": "owner-1"},
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


def test_direct_root_turn_bootstraps_conversation_for_ai_title_refresh(tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))

    class ImmediateBackgroundWork:
        def submit(self, *, key, func, delay_seconds=0.0, **kwargs):
            del key, delay_seconds
            func(**kwargs)
            return True

    class RecordingBranchService:
        def __init__(self):
            self.calls: list[dict[str, str]] = []

        def refresh_conversation_title_after_first_turn(self, **kwargs):
            self.calls.append(dict(kwargs))
            repo.update_conversation_title(
                root_thread_id=kwargs["root_thread_id"],
                owner_user_id=kwargs["user_id"],
                title="Direct First Turn",
                title_pending_ai=False,
            )

    branch_service = RecordingBranchService()
    runtime = SimpleNamespace(
        settings=Settings(),
        graph=RecordingGraph(),
        repo=repo,
        branch_service=branch_service,
        background_work=ImmediateBackgroundWork(),
    )
    chat = ChatService(runtime)

    chat.send_message(thread_id="root-1", user_id="owner-1", message="Plan the launch")

    record = repo.get_conversation("root-1")
    assert record.title == "Direct First Turn"
    assert record.title_pending_ai is False
    assert branch_service.calls == [{"root_thread_id": "root-1", "user_id": "owner-1"}]


def test_sse_frame_serializes_message_objects():
    frame = ChatService._sse_frame(
        event="state.update",
        data={"messages": [HumanMessage(content="hello")]},
    )

    assert "event: state.update" in frame
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


def test_send_message_skips_post_turn_side_effects_when_thread_turn_heartbeat_is_lost(
    tmp_path: Path,
):
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
            return SimpleNamespace(
                values={"branch_meta": {"is_archived": True, "archived_at": "2026-04-12 10:00:00"}}
            )

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


def test_send_message_exposes_active_skill_metadata_per_turn(tmp_path: Path):
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
                "recommended_tools: search_code, run_workspace_command",
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

    class TurnMessageGraph:
        def __init__(self):
            self.values: dict[str, object] = {}
            self.last_payload = None

        def invoke(self, payload, *, config, context, version):
            del config, context, version
            self.last_payload = payload
            self.values = {
                "messages": [*list(payload["messages"]), AIMessage(content="planned")],
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

    graph = TurnMessageGraph()
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
    )

    assert graph.last_payload["messages"][0].response_metadata["focus_agent"][
        "active_skill_ids"
    ] == ["plan"]
    assert payload["active_skill_ids"] == ["plan"]
    assert payload["active_skills"][0]["skill_id"] == "plan"
    assert payload["active_skills"][0]["description"] == "Planning mode"
    assert payload["active_skills"][0]["recommended_tools"] == [
        "search_code",
        "run_workspace_command",
    ]
    human_message = payload["messages"][0]
    assert human_message["type"] == "human"
    assert human_message["metadata"]["active_skill_ids"] == ["plan"]
    assert human_message["metadata"]["active_skills"][0]["skill_id"] == "plan"
    assert human_message["metadata"]["skill_selection"]["prompt_mode"] == "explore"


def test_send_message_preserves_thread_active_skill_without_new_trigger(tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    skill_dir = tmp_path / "skills"
    stocks_dir = skill_dir / "stocks"
    stocks_dir.mkdir(parents=True, exist_ok=True)
    (stocks_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                "name: stocks",
                "description: Fetch read-only stock market data.",
                "aliases: [股票, 行情, A股]",
                "recommended_tools: [run_workspace_command, web_search]",
                "prompt_mode: execute",
                "---",
                "",
                "# Stocks",
                "",
                "Use this skill for stock market data.",
            ]
        ),
        encoding="utf-8",
    )

    class ActiveSkillGraph:
        def __init__(self):
            self.values: dict[str, object] = {
                "messages": [],
                "active_skill_ids": ["stocks"],
            }
            self.last_payload = None
            self.last_context = None

        def invoke(self, payload, *, config, context, version):
            del config, version
            self.last_payload = payload
            self.last_context = context
            self.values = {
                **self.values,
                "messages": [*list(payload["messages"]), AIMessage(content="done")],
                "active_skill_ids": list(payload.get("active_skill_ids", [])),
            }
            return {}

        def get_state(self, _config):
            return SimpleNamespace(values=self.values, interrupts=[])

        def update_state(self, _config, values, as_node=None):
            del _config, as_node
            self.values = {**self.values, **dict(values)}

    graph = ActiveSkillGraph()
    runtime = SimpleNamespace(
        settings=Settings(),
        graph=graph,
        repo=repo,
        skill_registry=SkillRegistry([skill_dir], semantic_match_enabled=False),
    )
    chat = ChatService(runtime)

    payload = chat.send_message(
        thread_id="root-1",
        user_id="owner-1",
        message="华钰矿业近一周表现",
    )

    assert graph.last_payload["active_skill_ids"] == ["stocks"]
    assert graph.last_context.skill_hints == ("stocks",)
    assert payload["active_skill_ids"] == ["stocks"]
    assert payload["active_skills"][0]["skill_id"] == "stocks"
    human_message = payload["messages"][0]
    assert human_message["metadata"]["active_skill_ids"] == ["stocks"]
    assert human_message["metadata"]["skill_selection"]["selection_source"] == "none"


def test_send_message_explicit_skill_name_overrides_thread_active_skill(tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    skill_dir = tmp_path / "skills"
    stocks_dir = skill_dir / "stocks"
    stocks_dir.mkdir(parents=True, exist_ok=True)
    (stocks_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                "name: stocks",
                "description: Fetch stock market data.",
                "aliases: [股票, A股]",
                "primary_tools: [run_workspace_command]",
                "prompt_mode: execute",
                "---",
                "# Stocks",
            ]
        ),
        encoding="utf-8",
    )
    china_dir = skill_dir / "china-stock-analysis"
    china_dir.mkdir(parents=True, exist_ok=True)
    (china_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                "name: china-stock-analysis",
                "description: Analyze China A-share financial statements.",
                "aliases: [A股分析, 财报分析]",
                "primary_tools: [run_skill_entrypoint]",
                "prompt_mode: execute",
                "---",
                "# China Stock Analysis",
            ]
        ),
        encoding="utf-8",
    )

    class ActiveSkillGraph:
        def __init__(self):
            self.values: dict[str, object] = {
                "messages": [],
                "active_skill_ids": ["stocks"],
            }
            self.last_payload = None
            self.last_context = None

        def invoke(self, payload, *, config, context, version):
            del config, version
            self.last_payload = payload
            self.last_context = context
            self.values = {
                **self.values,
                "messages": [*list(payload["messages"]), AIMessage(content="done")],
                "active_skill_ids": list(payload.get("active_skill_ids", [])),
            }
            return {}

        def get_state(self, _config):
            return SimpleNamespace(values=self.values, interrupts=[])

        def update_state(self, _config, values, as_node=None):
            del _config, as_node
            self.values = {**self.values, **dict(values)}

    graph = ActiveSkillGraph()
    runtime = SimpleNamespace(
        settings=Settings(),
        graph=graph,
        repo=repo,
        skill_registry=SkillRegistry([skill_dir], semantic_match_enabled=False),
    )
    chat = ChatService(runtime)

    payload = chat.send_message(
        thread_id="root-1",
        user_id="owner-1",
        message="调用china-stock-analysis技能（本地路径：.focus_agent/skills/china-stock-analysis/SKILL.md）分析中兴通讯",
    )

    assert graph.last_payload["active_skill_ids"] == ["china-stock-analysis"]
    assert graph.last_context.skill_hints == ("china-stock-analysis",)
    assert payload["active_skill_ids"] == ["china-stock-analysis"]
    human_message = payload["messages"][0]
    assert human_message["metadata"]["skill_selection"]["selection_source"] == "explicit"


def test_send_message_semantically_activates_build_fix_for_real_failure_request(tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    skill_dir = tmp_path / "skills"
    build_fix_dir = skill_dir / "build-fix"
    build_fix_dir.mkdir(parents=True, exist_ok=True)
    (build_fix_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                "name: build-fix",
                (
                    "description: Triage and fix repository build, type-check, lint, "
                    "or test failures using the project's real commands and verification path."
                ),
                "triggers: build-fix:, fix-build:, check-fix:",
                (
                    "when_to_use: make check is failing, Frontend or SDK type-checks are broken, "
                    "Lint or pytest failures need a focused repair workflow"
                ),
                "recommended_tools: git_status, git_diff, search_code, read_file, write_text_artifact",
                "prompt_mode: execute",
                "---",
                "",
                "# Build Fix",
                "",
                "Use the repository's real validation commands.",
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
        message="我这边 make check、lint、pytest 都失败了，帮我定位根因并修复。",
        model="moonshot:kimi-k2.6",
        thinking_mode="disabled",
    )

    assert graph.last_context.skill_hints == ("build-fix",)
    assert graph.last_payload["active_skill_ids"] == ["build-fix"]
    assert graph.last_payload["prompt_mode"] == "execute"
    assert payload["active_skill_ids"] == ["build-fix"]


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
                    AIMessage(
                        content="done",
                        response_metadata={
                            "token_usage": {
                                "prompt_tokens": 11,
                                "completion_tokens": 7,
                                "total_tokens": 18,
                            }
                        },
                    ),
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
    assert record.metrics["input_tokens"] == 11
    assert record.metrics["output_tokens"] == 7
    assert record.metrics["total_tokens"] == 18


def test_send_message_records_child_trajectory_under_resolved_root(tmp_path: Path):
    repo = _repo_with_child_branch(tmp_path)

    class ChildGraph:
        def __init__(self):
            self.values_by_thread: dict[str, dict[str, object]] = {}

        @staticmethod
        def _thread_id(config):
            return str((config or {}).get("configurable", {}).get("thread_id") or "")

        def invoke(self, payload, *, config, context, version):
            del version
            thread_id = self._thread_id(config)
            assert thread_id == "child-1"
            assert context.root_thread_id == "root-1"
            self.values_by_thread[thread_id] = {
                "messages": [*list(payload["messages"]), AIMessage(content="child answer")],
                "llm_calls": 1,
                "task_brief": payload["task_brief"],
                "selected_model": payload["selected_model"],
                "selected_thinking_mode": payload["selected_thinking_mode"],
            }
            return {}

        def get_state(self, config):
            return SimpleNamespace(
                values=self.values_by_thread.get(self._thread_id(config), {}),
                interrupts=[],
            )

        def update_state(self, config, values, as_node=None):
            del as_node
            thread_id = self._thread_id(config)
            self.values_by_thread[thread_id] = {
                **self.values_by_thread.get(thread_id, {}),
                **dict(values),
            }

    class RecordingTrajectoryRecorder:
        def __init__(self):
            self.records = []

        def record_turn(self, record):
            self.records.append(record)

    recorder = RecordingTrajectoryRecorder()
    chat = _chat_for_repo(
        repo,
        graph=ChildGraph(),
        trajectory_recorder=recorder,
    )

    payload = chat.send_message(
        thread_id="child-1",
        user_id="owner-1",
        message="continue on child",
    )

    assert payload["root_thread_id"] == "root-1"
    assert payload["branch_meta"]["branch_id"] == "branch-1"
    assert len(recorder.records) == 1
    record = recorder.records[0]
    assert record.thread_id == "child-1"
    assert record.root_thread_id == "root-1"
    assert record.branch_id == "branch-1"
    assert record.parent_thread_id == "root-1"


def test_stream_harness_run_records_trajectory_and_schedules_title_refresh(tmp_path: Path):
    repo = SQLiteBranchRepository(str(tmp_path / "branches.sqlite3"))
    repo.ensure_thread_owner(thread_id="root-1", root_thread_id="root-1", owner_user_id="owner-1")

    class StreamGraph:
        def __init__(self):
            self.values = {
                "messages": [
                    HumanMessage(content="stream this"),
                    AIMessage(
                        content="streamed done",
                        usage_metadata={"input_tokens": 9, "output_tokens": 4, "total_tokens": 13},
                    ),
                ],
                "llm_calls": 1,
                "task_brief": "stream this",
            }

        def get_state(self, _config):
            return SimpleNamespace(values=self.values, interrupts=[])

    class EmptyHarness:
        async def stream_chunks(self, **_kwargs):
            if False:
                yield {}

    class RecordingRunManager:
        def __init__(self):
            self.record = SimpleNamespace(
                abort_event=asyncio.Event(),
                abort_action="interrupt",
            )
            self.statuses: list[object] = []

        async def set_status(self, _run_id, status, error=None):
            del error
            self.statuses.append(status)

        def get(self, _run_id):
            return self.record

    class RecordingStreamBridge:
        def __init__(self):
            self.events: list[tuple[str, dict[str, object]]] = []
            self.ended = False

        async def publish(self, _run_id, event_name, payload):
            self.events.append((event_name, payload))

        async def publish_end(self, _run_id):
            self.ended = True

    class RecordingTrajectoryRecorder:
        def __init__(self):
            self.records = []

        def record_turn(self, record):
            self.records.append(record)

    class ImmediateBackgroundWork:
        def submit(self, *, key, func, delay_seconds=0.0, **kwargs):
            del key, delay_seconds
            func(**kwargs)
            return True

    class RecordingBranchService:
        def __init__(self):
            self.calls: list[dict[str, str]] = []

        def refresh_conversation_title_after_first_turn(self, **kwargs):
            self.calls.append(dict(kwargs))

    graph = StreamGraph()
    run_manager = RecordingRunManager()
    stream_bridge = RecordingStreamBridge()
    recorder = RecordingTrajectoryRecorder()
    branch_service = RecordingBranchService()
    runtime = SimpleNamespace(
        settings=Settings(context_auto_compaction_enabled=False),
        graph=graph,
        harness=EmptyHarness(),
        checkpointer=None,
        repo=repo,
        run_manager=run_manager,
        stream_bridge=stream_bridge,
        trajectory_recorder=recorder,
        branch_service=branch_service,
        background_work=ImmediateBackgroundWork(),
    )
    chat = ChatService(runtime)

    asyncio.run(
        _produce_run_stream(
            runtime=runtime,
            chat=chat,
            run_id="run-1",
            thread_id="root-1",
            user_id="owner-1",
            payload={"messages": [HumanMessage(content="stream this")]},
            context=SimpleNamespace(root_thread_id="root-1"),
            branch_meta=None,
            initial_values={"messages": [], "llm_calls": 0},
            request_id="req-stream",
            kind="chat.turn",
        )
    )

    assert recorder.records[0].kind == "chat.turn"
    assert recorder.records[0].metrics["total_tokens"] == 13
    assert branch_service.calls == [{"root_thread_id": "root-1", "user_id": "owner-1"}]
    assert any(event_name == "run.completed" for event_name, _ in stream_bridge.events)
    assert stream_bridge.ended is True


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
    service = ChatService(
        ChatServicePorts(settings=Settings(), graph=FakeGraph(), repo=SimpleNamespace())
    )

    payload = service._serialize_message(
        AIMessage(
            content="done",
            usage_metadata={"input_tokens": 21, "output_tokens": 9, "total_tokens": 30},
        )
    )

    assert payload["content"] == "done"
    assert payload["usage_metadata"]["total_tokens"] == 30
    assert payload["usage_metadata"]["input_tokens"] == 21


def test_serialize_message_normalizes_response_metadata_token_usage():
    service = ChatService(
        ChatServicePorts(settings=Settings(), graph=FakeGraph(), repo=SimpleNamespace())
    )

    payload = service._serialize_message(
        AIMessage(
            content="done",
            response_metadata={"token_usage": {"prompt_tokens": 13, "completion_tokens": 5}},
        )
    )

    assert payload["usage_metadata"] == {
        "input_tokens": 13,
        "output_tokens": 5,
        "total_tokens": 18,
    }


def test_serialize_message_exposes_focus_agent_metadata():
    service = ChatService(
        ChatServicePorts(settings=Settings(), graph=FakeGraph(), repo=SimpleNamespace())
    )

    payload = service._serialize_message(
        HumanMessage(
            content="plan: map the rollout",
            response_metadata={
                "focus_agent": {
                    "active_skill_ids": ["plan"],
                    "active_skills": [{"skill_id": "plan", "name": "plan"}],
                }
            },
        )
    )

    assert payload["metadata"]["active_skill_ids"] == ["plan"]
    assert payload["metadata"]["active_skills"][0]["skill_id"] == "plan"


def test_serialize_ai_message_exposes_focus_agent_turn_metadata_from_response_metadata():
    service = ChatService(
        ChatServicePorts(settings=Settings(), graph=FakeGraph(), repo=SimpleNamespace())
    )
    skill_execution_plan = {
        "active_skill_ids": ["plan"],
        "required_tools": ["read_file"],
    }
    execution_contract = {
        "required_tools": ["read_file"],
        "deliverable": "skill plan",
    }
    answer_verification = {
        "checks": ["required tools rendered"],
    }

    payload = service._serialize_message(
        AIMessage(
            content="done",
            response_metadata={
                "focus_agent": {
                    "skill_execution_plan": skill_execution_plan,
                    "execution_contract": execution_contract,
                    "answer_verification": answer_verification,
                }
            },
        )
    )

    assert "turn_metadata" in payload
    assert payload["turn_metadata"]["skill_execution_plan"] == skill_execution_plan
    assert payload["turn_metadata"]["execution_contract"] == execution_contract
    assert payload["turn_metadata"]["answer_verification"] == answer_verification


def test_serialize_dict_ai_message_exposes_focus_agent_turn_metadata_from_response_metadata():
    service = ChatService(
        ChatServicePorts(settings=Settings(), graph=FakeGraph(), repo=SimpleNamespace())
    )
    skill_execution_plan = {
        "active_skill_ids": ["plan"],
        "required_tools": ["read_file"],
    }
    execution_contract = {
        "required_tools": ["read_file"],
        "deliverable": "skill plan",
    }

    payload = service._serialize_message(
        {
            "type": "ai",
            "content": "done",
            "response_metadata": {
                "focus_agent": {
                    "skill_execution_plan": skill_execution_plan,
                    "execution_contract": execution_contract,
                }
            },
        }
    )

    assert "turn_metadata" in payload
    assert payload["turn_metadata"]["skill_execution_plan"] == skill_execution_plan
    assert payload["turn_metadata"]["execution_contract"] == execution_contract


def test_latest_final_ai_text_hides_english_process_narration():
    service = ChatService(
        ChatServicePorts(settings=Settings(), graph=FakeGraph(), repo=SimpleNamespace())
    )

    assert (
        service._latest_final_ai_text(
            [
                AIMessage(content="确认可见的最终答案。"),
                AIMessage(
                    content="Let me fetch the data first. I should look for: filings and price action."
                ),
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
                AIMessage(
                    content="Let me produce the final answer. Final answer: 这才是最终答案。"
                ),
            ]
        )
        == "这才是最终答案。"
    )


def test_latest_final_ai_text_ignores_draft_before_later_tool_activity():
    service = ChatService(
        ChatServicePorts(settings=Settings(), graph=FakeGraph(), repo=SimpleNamespace())
    )

    assert (
        service._latest_final_ai_text(
            [
                HumanMessage(content="查证配置。"),
                AIMessage(content="初步答复，但还不完整。"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call-1",
                            "name": "search_code",
                            "args": {"query": "skill_install"},
                        }
                    ],
                ),
                ToolMessage(content='{"results":[]}', tool_call_id="call-1"),
            ]
        )
        is None
    )


def test_thread_state_messages_hide_textual_tool_protocol_ai_messages():
    service = ChatService(
        ChatServicePorts(settings=Settings(), graph=FakeGraph(), repo=SimpleNamespace())
    )

    payload = service._thread_state_messages(
        [
            HumanMessage(content="Search this."),
            AIMessage(
                content='="read="filepath" string="true">tool-observation://webfetch/call00ljJOwoeUmsjmBzMNhkx8505'
            ),
            AIMessage(
                content=(
                    '<tool_req name="run_shell_command">\n'
                    '<arg name="command" string="true">cd /home/focus/.focus_agent/skills/stocks '
                    "&& python3 scripts/stocks_client.py quote 601020.SS</arg>\n"
                    '<arg name="timeout" string="false">30</arg>\n'
                    "</tool_req>"
                )
            ),
            AIMessage(content="最终安全回答。"),
        ]
    )

    assert [message["type"] for message in payload] == ["human", "ai"]
    assert [message["content"] for message in payload] == ["Search this.", "最终安全回答。"]


def test_thread_state_messages_hide_draft_answer_before_later_tool_activity():
    service = ChatService(
        ChatServicePorts(settings=Settings(), graph=FakeGraph(), repo=SimpleNamespace())
    )

    payload = service._thread_state_messages(
        [
            HumanMessage(content="查证配置。"),
            AIMessage(content="初步答复，但还不完整。"),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call-1",
                        "name": "search_code",
                        "args": {"query": "skill_install"},
                    }
                ],
            ),
            ToolMessage(content='{"results":[]}', tool_call_id="call-1"),
        ]
    )

    assert [message["type"] for message in payload] == ["human", "ai", "tool"]
    assert payload[1]["content"] == ""
    assert payload[1]["tool_calls"][0]["name"] == "search_code"
    assert payload[2]["tool_call_id"] == "call-1"


def test_thread_state_messages_hide_english_process_narration():
    service = ChatService(
        ChatServicePorts(settings=Settings(), graph=FakeGraph(), repo=SimpleNamespace())
    )

    payload = service._thread_state_messages(
        [
            HumanMessage(content="Search this."),
            AIMessage(
                content="Let me fetch the data first. I should look for: filings and price action."
            ),
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
    service = ChatService(
        ChatServicePorts(settings=Settings(), graph=FakeGraph(), repo=SimpleNamespace())
    )

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
    service = ChatService(
        ChatServicePorts(settings=Settings(), graph=FakeGraph(), repo=SimpleNamespace())
    )

    payload = service._thread_state_messages(
        [
            SimpleNamespace(
                type="ai",
                content='="read="filepath" string="true">tool-observation://webfetch/call-1',
                tool_calls=[
                    {"id": "call-1", "name": "web_fetch", "args": {"url": "https://example.com"}}
                ],
                name=None,
                id="ai-tools",
                usage_metadata=None,
            )
        ]
    )

    assert len(payload) == 1
    assert payload[0]["content"] == ""
    assert payload[0]["tool_calls"][0]["name"] == "web_fetch"


def test_thread_state_messages_preserve_dict_system_messages():
    service = ChatService(
        ChatServicePorts(settings=Settings(), graph=FakeGraph(), repo=SimpleNamespace())
    )

    payload = service._thread_state_messages(
        [
            {
                "type": "system",
                "content": "Imported conclusion from branch 'explore-alternatives':\nDone.",
                "id": "merge-notice-1",
            }
        ]
    )

    assert payload == [
        {
            "type": "system",
            "content": "Imported conclusion from branch 'explore-alternatives':\nDone.",
            "tool_calls": None,
            "name": None,
            "id": "merge-notice-1",
            "usage_metadata": None,
        }
    ]


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
    assert (
        "Imported conclusion from branch 'explore-alternatives':" in system_messages[-1]["content"]
    )
    assert "Recovered conclusion from child branch." in system_messages[-1]["content"]
    assert payload["rolling_summary"].endswith(
        "Imported from explore-alternatives: Recovered conclusion from child branch."
    )
    assert graph.updates
    assert graph.updates[0][1] == "bootstrap_turn"


def test_get_thread_state_dedupes_dict_imported_conclusion_notice(tmp_path: Path):
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
    chat = ChatService(runtime)

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
