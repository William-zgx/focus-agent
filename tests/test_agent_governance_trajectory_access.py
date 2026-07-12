from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from focus_agent.api.deps import get_current_principal
from focus_agent.api.routers.agent_governance import router
from focus_agent.config import Settings
from focus_agent.core.users import User, UserStatus
from focus_agent.repositories.governance_repository import InMemoryGovernanceRepository
from focus_agent.repositories.postgres_trajectory_repository import (
    PostgresTrajectoryRepository,
    TrajectoryTurnQuery,
)
from focus_agent.security.tokens import Principal

_LIST_ENDPOINTS = (
    "/v1/agent/roles/decisions",
    "/v1/agent/tool-router/decisions",
    "/v1/agent/memory/curator/decisions",
    "/v1/agent/delegation/runs",
    "/v1/agent/model-router/decisions",
    "/v1/agent/self-repair/failures",
    "/v1/agent/review-queue",
    "/v1/agent/context/decisions",
    "/v1/agent/context/artifacts",
    "/v1/agent/task-ledger/runs",
    "/v1/agent/artifacts",
    "/v1/agent/critic/verdicts",
)


def _trajectory_row(*, owner_user_id: str, thread_id: str) -> dict[str, Any]:
    marker = f"{owner_user_id}:{thread_id}"
    return {
        "id": f"turn-{marker}",
        "request_id": f"request-{marker}",
        "trace_id": f"trace-{marker}",
        "thread_id": thread_id,
        "root_thread_id": thread_id,
        "status": "failed",
        "error": marker,
        "started_at": "2026-07-12T00:00:00Z",
        "_owner_user_id": owner_user_id,
        "plan_meta": {
            "role_route_plan": {
                "enabled": True,
                "route_reason": marker,
                "decisions": [{"role": "executor", "marker": marker}],
            },
            "tool_route_plan": {"enabled": True, "marker": marker},
            "memory_curator_decision": {"enabled": True, "marker": marker},
            "agent_runs": [{"run_id": f"run-{marker}", "marker": marker}],
            "model_route_decision": {"enabled": True, "marker": marker},
            "agent_failure_records": [
                {"failure_id": f"failure-{marker}", "marker": marker}
            ],
            "agent_review_queue": [{"item_id": f"review-{marker}", "marker": marker}],
            "context_budget_decision": {"enabled": True, "marker": marker},
            "context_artifact_refs": [
                {"artifact_id": f"context-{marker}", "marker": marker}
            ],
            "agent_task_ledger": {
                "enabled": True,
                "tasks": [{"task_id": f"task-{marker}", "marker": marker}],
            },
            "delegated_artifacts": [
                {"artifact_id": f"artifact-{marker}", "marker": marker}
            ],
            "critic_gate_result": {"enabled": True, "verdict": "pass", "marker": marker},
        },
    }


class _QueryFilteringTrajectoryRepository:
    def __init__(self) -> None:
        self.rows = [
            _trajectory_row(owner_user_id="user-a", thread_id="thread-a"),
            _trajectory_row(owner_user_id="user-b", thread_id="thread-b"),
        ]
        self.queries: list[TrajectoryTurnQuery] = []

    def list_turns(self, query: TrajectoryTurnQuery) -> list[dict[str, Any]]:
        assert isinstance(query, TrajectoryTurnQuery)
        self.queries.append(query)
        rows = self.rows
        if query.owner_user_id is not None:
            rows = [
                row
                for row in rows
                if row["_owner_user_id"] == query.owner_user_id
            ]
        if query.thread_id is not None:
            rows = [row for row in rows if row["thread_id"] == query.thread_id]
        if query.status is not None:
            statuses = {query.status} if isinstance(query.status, str) else set(query.status)
            rows = [row for row in rows if row["status"] in statuses]
        return rows if query.limit is None else rows[: query.limit]

    def get_turn(self, _turn_id: str) -> None:
        return None

    def list_steps_by_turn_ids(self, _turn_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        return {}

    def get_turn_stats(self, _query: TrajectoryTurnQuery) -> dict[str, Any]:
        return {"overview": {}, "by_status": []}


class _UserService:
    def __init__(
        self,
        roles_by_user: dict[str, list[str]],
        *,
        status_by_user: dict[str, UserStatus] | None = None,
    ) -> None:
        self.roles_by_user = roles_by_user
        self.status_by_user = status_by_user or {}

    def get_user(self, user_id: str) -> User:
        roles = self.roles_by_user.get(user_id, ["member"])
        return User(
            user_id=user_id,
            status=self.status_by_user.get(user_id, UserStatus.ACTIVE),
            roles=roles,
            created_at="2026-07-12T00:00:00Z",
            updated_at="2026-07-12T00:00:00Z",
        )


def _client(
    *,
    principal: Principal,
    roles_by_user: dict[str, list[str]] | None = None,
    status_by_user: dict[str, UserStatus] | None = None,
) -> tuple[TestClient, _QueryFilteringTrajectoryRepository]:
    repository = _QueryFilteringTrajectoryRepository()
    runtime = SimpleNamespace(
        settings=Settings(auth_enabled=True),
        trajectory_recorder=repository,
        governance_repository=InMemoryGovernanceRepository(),
        user_service=_UserService(
            roles_by_user or {},
            status_by_user=status_by_user,
        ),
    )
    app = FastAPI()
    app.include_router(router)
    app.state.runtime = runtime
    app.dependency_overrides[get_current_principal] = lambda: principal
    return TestClient(app), repository


@pytest.mark.parametrize("endpoint", _LIST_ENDPOINTS)
def test_governance_trajectory_lists_filter_by_principal_in_query_layer(
    endpoint: str,
) -> None:
    client, repository = _client(principal=Principal(user_id="user-a"))

    response = client.get(endpoint)

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert "user-a:thread-a" in str(response.json()["items"][0])
    assert "user-b:thread-b" not in response.text
    assert repository.queries
    assert all(query.owner_user_id == "user-a" for query in repository.queries)


@pytest.mark.parametrize("endpoint", _LIST_ENDPOINTS)
def test_governance_trajectory_lists_ignore_unprivileged_global_view_attempt(
    endpoint: str,
) -> None:
    client, repository = _client(principal=Principal(user_id="user-a"))

    response = client.get(endpoint, params={"global_view": "true"})

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert "user-a:thread-a" in str(response.json()["items"][0])
    assert "user-b:thread-b" not in response.text
    assert repository.queries
    assert all(query.owner_user_id == "user-a" for query in repository.queries)


@pytest.mark.parametrize("endpoint", _LIST_ENDPOINTS)
def test_governance_trajectory_lists_do_not_accept_cross_user_thread_override(
    endpoint: str,
) -> None:
    client, repository = _client(principal=Principal(user_id="user-a"))

    response = client.get(endpoint, params={"thread_id": "thread-b"})

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert "user-a:thread-a" in str(response.json()["items"][0])
    assert "user-b:thread-b" not in response.text
    assert repository.queries
    assert all(query.owner_user_id == "user-a" for query in repository.queries)
    assert all(query.thread_id is None for query in repository.queries)


@pytest.mark.parametrize(
    ("principal", "roles_by_user"),
    (
        (Principal(user_id="admin-user"), {"admin-user": ["admin"]}),
        (
            Principal(
                user_id="auditor-user",
                scopes=("governance:trajectories:read:global",),
            ),
            {"auditor-user": ["member"]},
        ),
    ),
)
def test_authorized_governance_global_view_is_explicit_and_unscoped(
    principal: Principal,
    roles_by_user: dict[str, list[str]],
) -> None:
    client, repository = _client(
        principal=principal,
        roles_by_user=roles_by_user,
    )

    response = client.get(
        "/v1/agent/tool-router/decisions",
    )

    assert response.status_code == 200
    assert response.json()["count"] == 2
    assert repository.queries
    assert all(query.owner_user_id is None for query in repository.queries)


def test_inactive_user_cannot_use_stale_global_governance_scope() -> None:
    client, repository = _client(
        principal=Principal(
            user_id="disabled-auditor",
            scopes=("governance:trajectories:read:global",),
        ),
        roles_by_user={"disabled-auditor": ["admin"]},
        status_by_user={"disabled-auditor": UserStatus.DISABLED},
    )

    response = client.get(
        "/v1/agent/tool-router/decisions",
    )

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert repository.queries
    assert all(query.owner_user_id == "disabled-auditor" for query in repository.queries)


def test_feedback_trend_failure_samples_are_filtered_by_principal_in_query_layer() -> None:
    client, repository = _client(principal=Principal(user_id="user-a"))

    response = client.get("/v1/agent/feedback/trend")

    assert response.status_code == 200
    samples = response.json()["top_failing_trajectory_samples"]
    assert len(samples) == 1
    assert samples[0]["thread_id"] == "thread-a"
    assert samples[0]["error"] == "user-a:thread-a"
    assert repository.queries
    assert all(query.owner_user_id == "user-a" for query in repository.queries)


def test_postgres_trajectory_owner_and_thread_filters_are_in_sql() -> None:
    repository = object.__new__(PostgresTrajectoryRepository)

    sql, params = repository._build_turn_select_sql(
        query=TrajectoryTurnQuery(
            owner_user_id="user-a",
            thread_id="thread-a",
            limit=50,
        ),
        select_clause="SELECT t.*",
    )

    assert "FROM focus_thread_access ta" in sql
    assert "ta.thread_id = t.thread_id" in sql
    assert "ta.owner_user_id = %(owner_user_id)s" in sql
    assert "t.thread_id = %(thread_id)s" in sql
    assert params["owner_user_id"] == "user-a"
    assert params["thread_id"] == "thread-a"
