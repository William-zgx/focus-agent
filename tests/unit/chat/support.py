import asyncio as asyncio
import json
import threading as threading
import time as time
from pathlib import Path
from types import SimpleNamespace

import pytest as pytest
from langchain.messages import (
    AIMessage,
)
from langchain.messages import (
    HumanMessage as HumanMessage,
)
from langchain.messages import (
    SystemMessage as SystemMessage,
)
from langchain.messages import (
    ToolMessage as ToolMessage,
)

from focus_agent.api.routers.harness_runs.replay_streaming import (
    _produce_run_stream as _produce_run_stream,
)
from focus_agent.branch_decision import BranchDecisionService
from focus_agent.config import (
    ConfiguredModel as ConfiguredModel,
)
from focus_agent.config import (
    ModelCatalogConfig as ModelCatalogConfig,
)
from focus_agent.config import (
    Settings,
)
from focus_agent.core.branching import (
    BranchActionKind as BranchActionKind,
)
from focus_agent.core.branching import (
    BranchActionNavigation as BranchActionNavigation,
)
from focus_agent.core.branching import (
    BranchMeta as BranchMeta,
)
from focus_agent.core.branching import (
    BranchRecord,
    BranchRole,
    BranchStatus,
)
from focus_agent.core.request_context import RequestContext as RequestContext
from focus_agent.repositories.governance_repository import InMemoryGovernanceRepository
from focus_agent.repositories.sqlite_branch_repository import SQLiteBranchRepository
from focus_agent.services.branches.actions import (
    branch_handoff_message_from_text as branch_handoff_message_from_text,
)
from focus_agent.services.branches.actions import (
    build_branch_action_proposal as build_branch_action_proposal,
)
from focus_agent.services.branches.actions import (
    infer_suggested_branch_name as infer_suggested_branch_name,
)
from focus_agent.services.branches.actions import (
    is_branch_action_dismissal as is_branch_action_dismissal,
)
from focus_agent.services.branches.actions import (
    is_branch_action_request as is_branch_action_request,
)
from focus_agent.services.branches.actions import (
    mark_branch_action_executed as mark_branch_action_executed,
)
from focus_agent.services.chat import (
    ChatService,
)
from focus_agent.services.chat import (
    ChatServicePorts as ChatServicePorts,
)
from focus_agent.services.chat import (
    ConcurrentTurnError as ConcurrentTurnError,
)
from focus_agent.services.chat import (
    ThreadStateUnavailableError as ThreadStateUnavailableError,
)
from focus_agent.services.chat.branch_actions import branch_action_intent as branch_action_intent
from focus_agent.services.coordination import (
    CoordinationBackend as CoordinationBackend,
)
from focus_agent.services.coordination import (
    InMemoryBackgroundJobDeduperBackend as InMemoryBackgroundJobDeduperBackend,
)
from focus_agent.services.coordination import (
    InMemoryRateLimitBackend as InMemoryRateLimitBackend,
)
from focus_agent.services.coordination import (
    InMemoryThreadTurnLockBackend as InMemoryThreadTurnLockBackend,
)
from focus_agent.services.coordination import (
    create_in_memory_coordination_backend,
)
from focus_agent.services.thread_turn_lease import ThreadTurnLeaseManager as ThreadTurnLeaseManager
from focus_agent.skills.registry import SkillRegistry as SkillRegistry


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


class FailingBackfillImportGraph(BackfillImportGraph):
    def update_state(self, _config, values, as_node=None):
        self.updates.append((values, as_node))
        raise RuntimeError("checkpoint unavailable")


class PostCommitFailingBackfillImportGraph(BackfillImportGraph):
    def update_state(self, config, values, as_node=None):
        super().update_state(config, values, as_node=as_node)
        raise RuntimeError("checkpoint response unavailable")


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

    def invoke(self, payload, *, config, context, version):
        del context, version
        state = self.values_by_thread.setdefault(self._thread_id(config), {})
        state["messages"] = list(state.get("messages", [])) + [
            *list(payload.get("messages", [])),
            AIMessage(content="normal answer"),
        ]
        return {}


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
    chat_service_factory,
    repo: SQLiteBranchRepository,
    *,
    graph: object | None = None,
    settings: Settings | None = None,
    **ports: object,
) -> ChatService:
    return chat_service_factory(
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
