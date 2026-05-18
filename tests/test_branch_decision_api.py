from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain.messages import HumanMessage

from focus_agent.api.routers.branch_decisions import router
from focus_agent.branch_decision import BranchDecisionService
from focus_agent.config import Settings
from focus_agent.core.governance import BranchDecisionAction, BranchDecisionEvent
from focus_agent.repositories.governance_repository import InMemoryGovernanceRepository
from focus_agent.services.coordination import create_in_memory_coordination_backend


class FakeGraph:
    def __init__(self):
        self.values = {
            "messages": [HumanMessage(content="请另开一个分支，并行探索另一个方案。")],
        }

    def get_state(self, _config):
        return SimpleNamespace(values=dict(self.values), interrupts=[])

    def update_state(self, _config, values, as_node=None):
        del _config, as_node
        self.values.update(values)


class FakeRepo:
    def assert_thread_owner(self, *, thread_id: str, owner_user_id: str) -> None:
        del thread_id, owner_user_id


def _client() -> tuple[TestClient, InMemoryGovernanceRepository, FakeGraph]:
    settings = Settings(
        auth_enabled=False,
        agent_branch_decision_enabled=True,
        agent_branch_decision_mode="shadow",
        agent_branch_recommendation_enabled=True,
        agent_branch_recommendation_mode="shadow",
    )
    repository = InMemoryGovernanceRepository()
    graph = FakeGraph()
    service = BranchDecisionService(
        settings=settings,
        graph=graph,
        governance_repository=repository,
        branch_service=SimpleNamespace(repo=FakeRepo()),
        coordination_backend=create_in_memory_coordination_backend(),
    )
    app = FastAPI()
    app.include_router(router)
    app.state.runtime = SimpleNamespace(settings=settings, branch_decision_service=service)
    return TestClient(app), repository, graph


def test_branch_decision_api_config_and_list() -> None:
    client, repository, _graph = _client()
    event = BranchDecisionEvent(
        user_id="anonymous",
        root_thread_id="root-1",
        source_thread_id="thread-1",
        action=BranchDecisionAction.SPLIT,
        score=0.8,
        threshold=0.7,
    )
    repository.save_branch_decision_event(event)

    config_response = client.get("/v1/branch-decisions/config")
    list_response = client.get("/v1/threads/thread-1/branch-decisions")

    assert config_response.status_code == 200
    assert config_response.json()["enabled"] is True
    assert config_response.json()["recommendation_user_visible"] is False
    assert config_response.json()["recommendation_diagnostics"]["shadow_records_events_only"] is True
    assert list_response.status_code == 200
    assert list_response.json()["items"][0]["decision_id"] == event.decision_id


def test_branch_decision_api_promote_and_dismiss() -> None:
    client, repository, graph = _client()
    event = BranchDecisionEvent(
        user_id="anonymous",
        root_thread_id="root-1",
        source_thread_id="thread-1",
        action=BranchDecisionAction.SPLIT,
        score=0.8,
        threshold=0.7,
    )
    repository.save_branch_decision_event(event)

    promote_response = client.post(
        f"/v1/threads/thread-1/branch-decisions/{event.decision_id}/promote"
    )
    dismiss_response = client.post(
        f"/v1/threads/thread-1/branch-decisions/{event.decision_id}/dismiss",
        json={"reason": "not_now"},
    )

    assert promote_response.status_code == 200
    assert promote_response.json()["status"] == "promoted"
    assert graph.values["branch_actions"][0]["source_decision_id"] == event.decision_id
    assert dismiss_response.status_code == 200
    assert dismiss_response.json()["status"] == "dismissed"
