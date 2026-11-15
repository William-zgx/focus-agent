from __future__ import annotations

import pytest
from langgraph.store.memory import InMemoryStore

from tests.test_auth_ownership import _auth_header, _build_client


def test_attention_api_review_is_persistent_and_scoped(monkeypatch, tmp_path):
    client, settings = _build_client(monkeypatch, tmp_path)
    client.app.state.runtime.store = InMemoryStore()
    owner_headers = _auth_header(settings, user_id="owner-1", tenant_id="tenant-a")

    first = client.get("/v1/threads/root-1/attention", headers=owner_headers)
    assert first.status_code == 200
    assert first.json()["thread_id"] == "root-1"
    assert first.json()["diff"]["first_visit"] is True
    assert first.json()["policy"]["level"] == "quiet"

    reviewed = client.post(
        "/v1/threads/root-1/attention/reviewed",
        headers=owner_headers,
        json={"cursor": first.json()["current_cursor"]},
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["reviewed_at"] is not None

    after = client.get("/v1/threads/root-1/attention", headers=owner_headers)
    assert after.status_code == 200
    assert after.json()["diff"]["first_visit"] is False
    assert after.json()["current_cursor"]["reviewed_at"] == reviewed.json()["reviewed_at"]

    other_tenant = _auth_header(settings, user_id="owner-1", tenant_id="tenant-b")
    isolated = client.get("/v1/threads/root-1/attention", headers=other_tenant)
    assert isolated.status_code == 200
    assert isolated.json()["diff"]["first_visit"] is True


def test_attention_api_reuses_thread_ownership(monkeypatch, tmp_path):
    client, settings = _build_client(monkeypatch, tmp_path)
    client.app.state.runtime.store = InMemoryStore()
    intruder_headers = _auth_header(settings, user_id="intruder-1", tenant_id="tenant-a")

    read = client.get("/v1/threads/root-1/attention", headers=intruder_headers)
    review = client.post(
        "/v1/threads/root-1/attention/reviewed",
        headers=intruder_headers,
        json={
            "cursor": {
                "version": 1,
                "last_message_id": None,
                "seen_outcome_ids": [],
                "action_statuses": {},
            }
        },
    )

    assert read.status_code == 403
    assert review.status_code == 403


def test_attention_review_rejects_a_missing_presented_frontier(monkeypatch, tmp_path):
    client, settings = _build_client(monkeypatch, tmp_path)
    client.app.state.runtime.store = InMemoryStore()
    owner_headers = _auth_header(settings, user_id="owner-1", tenant_id="tenant-a")

    response = client.post(
        "/v1/threads/root-1/attention/reviewed",
        headers=owner_headers,
        json={
            "cursor": {
                "version": 1,
                "last_message_id": "missing-message",
                "seen_outcome_ids": [],
                "action_statuses": {},
            }
        },
    )

    assert response.status_code == 409
    assert "no longer exists" in response.json()["message"]


@pytest.mark.parametrize("tenant_id", [None, "t.a"])
def test_attention_review_accepts_missing_tenant_and_periods(monkeypatch, tmp_path, tenant_id):
    client, settings = _build_client(monkeypatch, tmp_path)
    client.app.state.runtime.store = InMemoryStore()
    owner_headers = _auth_header(settings, user_id="owner-1", tenant_id=tenant_id)
    first = client.get("/v1/threads/root-1/attention", headers=owner_headers)
    assert first.status_code == 200

    reviewed = client.post(
        "/v1/threads/root-1/attention/reviewed",
        headers=owner_headers,
        json={"cursor": first.json()["current_cursor"]},
    )
    assert reviewed.status_code == 200

    after = client.get("/v1/threads/root-1/attention", headers=owner_headers)
    assert after.status_code == 200
    assert after.json()["diff"]["first_visit"] is False
