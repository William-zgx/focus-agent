from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from focus_agent.api.routers.productivity import router
from focus_agent.config import Settings
from focus_agent.repositories.productivity_repository import InMemoryProductivityRepository
from focus_agent.repositories.user_repository import InMemoryUserRepository
from focus_agent.security.tokens import create_access_token
from focus_agent.services.auth import AuthService
from focus_agent.services.productivity import ProductivityService
from focus_agent.services.users import UserService


def _client() -> tuple[TestClient, Settings]:
    settings = Settings(
        auth_enabled=True,
        auth_jwt_secret="productivity-secret",
        auth_jwt_issuer="focus-agent-productivity-test",
    )
    user_repo = InMemoryUserRepository()
    user_service = UserService(user_repo, auth_enabled=True)
    user_service.create_user(user_id="owner-1", roles=["member"])
    user_service.create_user(user_id="other-1", roles=["member"])
    productivity_repo = InMemoryProductivityRepository()
    app = FastAPI()
    app.include_router(router)
    app.state.runtime = SimpleNamespace(
        settings=settings,
        user_repository=user_repo,
        user_service=user_service,
        auth_service=AuthService(user_repo, settings=settings),
        productivity_repository=productivity_repo,
        productivity_service=ProductivityService(productivity_repo),
    )
    return TestClient(app), settings


def _headers(settings: Settings, user_id: str) -> dict[str, str]:
    token = create_access_token(settings=settings, user_id=user_id, scopes=[])
    return {"Authorization": f"Bearer {token}"}


def test_notes_api_scopes_records_to_owner():
    client, settings = _client()

    created = client.post(
        "/v1/notes",
        headers=_headers(settings, "owner-1"),
        json={
            "title": "Owner note",
            "body": "Only mine",
            "tags": ["focus"],
            "source_thread_id": "thread-1",
            "source_artifact_id": "artifact-1",
        },
    )
    note_id = created.json()["note"]["note_id"]

    owner_list = client.get("/v1/notes?q=mine", headers=_headers(settings, "owner-1"))
    other_detail = client.get(f"/v1/notes/{note_id}", headers=_headers(settings, "other-1"))

    assert created.status_code == 201
    assert created.json()["note"]["status"] == "active"
    assert created.json()["note"]["source_thread_id"] == "thread-1"
    assert created.json()["note"]["source_artifact_id"] == "artifact-1"
    assert owner_list.status_code == 200
    assert [item["note_id"] for item in owner_list.json()["items"]] == [note_id]
    assert other_detail.status_code == 404


def test_tasks_api_updates_completes_and_archives_owner_tasks():
    client, settings = _client()

    created = client.post(
        "/v1/tasks",
        headers=_headers(settings, "owner-1"),
        json={
            "title": "Write tests",
            "description": "Cover owner scoping",
            "source_thread_id": "thread-1",
            "assignee_user_id": "owner-1",
        },
    )
    task_id = created.json()["task"]["task_id"]
    updated = client.patch(
        f"/v1/tasks/{task_id}",
        headers=_headers(settings, "owner-1"),
        json={"status": "in_progress"},
    )
    completed = client.post(
        f"/v1/tasks/{task_id}/complete",
        headers=_headers(settings, "owner-1"),
    )
    archived = client.post(
        f"/v1/tasks/{task_id}/archive",
        headers=_headers(settings, "owner-1"),
    )
    hidden = client.patch(
        f"/v1/tasks/{task_id}",
        headers=_headers(settings, "other-1"),
        json={"title": "Nope"},
    )

    assert created.status_code == 201
    assert created.json()["task"]["source_thread_id"] == "thread-1"
    assert created.json()["task"]["assignee_user_id"] == "owner-1"
    assert updated.json()["task"]["status"] == "in_progress"
    assert completed.json()["task"]["status"] == "completed"
    assert archived.json()["task"]["status"] == "archived"
    assert hidden.status_code == 404


def test_productivity_capture_api_creates_sourced_note_and_task():
    client, settings = _client()
    headers = _headers(settings, "owner-1")

    captured_note = client.post(
        "/v1/productivity/capture/note",
        headers=headers,
        json={
            "source_kind": "chat_answer",
            "source_id": "turn-1",
            "source_url": "/app/chat/thread-1",
            "captured_from": "chat",
            "payload": {
                "answer": "Use merge reviews before applying Agent Team output.",
                "thread_id": "thread-1",
            },
            "pinned_context": {"thread_id": "thread-1", "turn_id": "turn-1"},
        },
    )
    captured_task = client.post(
        "/v1/productivity/capture/task",
        headers=headers,
        json={
            "source_kind": "agent_team_review",
            "source_id": "review-1",
            "source_url": "/app/agent-team/session-1/review-1",
            "captured_from": "agent_team",
            "title": "Review selected diffs",
            "payload": {
                "description": "Validate changed files and test evidence.",
                "thread_id": "root-thread",
            },
        },
    )

    note = captured_note.json()["note"]
    task = captured_task.json()["task"]
    assert captured_note.status_code == 201
    assert note["title"] == "Use merge reviews before applying Agent Team output."
    assert note["source_kind"] == "chat_answer"
    assert note["source_id"] == "turn-1"
    assert note["source_url"] == "/app/chat/thread-1"
    assert note["source_thread_id"] == "thread-1"
    assert note["pinned_context"] == {"thread_id": "thread-1", "turn_id": "turn-1"}
    assert note["captured_from"] == "chat"
    assert captured_task.status_code == 201
    assert task["title"] == "Review selected diffs"
    assert task["description"] == "Validate changed files and test evidence."
    assert task["source_kind"] == "agent_team_review"
    assert task["source_id"] == "review-1"
    assert task["source_thread_id"] == "root-thread"
    assert task["captured_from"] == "agent_team"
