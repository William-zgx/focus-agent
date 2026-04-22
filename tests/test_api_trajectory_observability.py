from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from focus_agent.api.main import create_app
from focus_agent.observability.trajectory import TurnTrajectoryRecord


def _with_stub_frontend(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    (dist_dir / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "test-api-key")
    monkeypatch.setenv("WEB_APP_DIST_DIR", str(dist_dir))
    monkeypatch.setenv("WEB_APP_DEV_SERVER_URL", "")
    monkeypatch.setenv("AUTH_ENABLED", "false")


@dataclass
class _FakeTrajectoryRepo:
    def list_turns(self, query):
        if query.turn_ids:
            assert query.turn_ids == ["turn-1"]
        elif query.request_id is not None:
            assert query.request_id == "req-query"
            assert query.trace_id == "trace-query"
            assert query.thread_id == "thread-1"
            assert query.status == "failed"
        return [
            {
                "id": "turn-1",
                "schema_version": 1,
                "kind": "chat.turn",
                "status": "failed",
                "thread_id": "thread-1",
                "root_thread_id": "root-1",
                "request_id": "req-query",
                "trace_id": "trace-query",
                "root_span_id": "span-root",
                "environment": "staging",
                "deployment": "focus-agent-blue",
                "app_version": "1.2.3",
                "parent_thread_id": None,
                "branch_id": None,
                "branch_role": "execute",
                "scene": "long_dialog_research",
                "turn_index": 3,
                "task_brief": "search docs",
                "user_message": "search docs",
                "answer": "answer",
                "selected_model": "openai:gpt-4.1-mini",
                "selected_thinking_mode": "medium",
                "error": "boom",
                "started_at": datetime(2026, 4, 21, 10, 0, tzinfo=timezone.utc),
                "finished_at": datetime(2026, 4, 21, 10, 0, 1, tzinfo=timezone.utc),
                "created_at": datetime(2026, 4, 21, 10, 0, 2, tzinfo=timezone.utc),
                "metrics": {"latency_ms": 1000.0, "tool_calls": 2},
                "plan_meta": {},
                "latency_ms": 1000.0,
                "tool_calls": 2,
                "llm_calls": 1,
                "cache_hits": 0,
                "fallback_uses": 1,
            }
        ]

    def get_turn_stats(self, query):
        if query.request_id is not None:
            assert query.request_id == "req-query"
        if query.trace_id is not None:
            assert query.trace_id == "trace-query"
        if query.fallback_used is not None:
            assert query.fallback_used is True
        return {
            "overview": {"turn_count": 1, "non_succeeded_count": 1, "avg_latency_ms": 1000.0},
            "by_status": [{"key": "failed", "turn_count": 1, "avg_latency_ms": 1000.0}],
            "by_scene": [{"key": "long_dialog_research", "turn_count": 1}],
            "by_branch_role": [{"key": "execute", "turn_count": 1}],
            "by_model": [{"key": "openai:gpt-4.1-mini", "turn_count": 1, "avg_latency_ms": 1000.0}],
            "by_day": [{"key": "2026-04-21", "turn_count": 1, "non_succeeded_count": 1, "avg_latency_ms": 1000.0}],
            "by_tool": [{"key": "web_search", "turn_count": 1, "step_count": 1}],
        }

    def get_turn(self, turn_id):
        assert turn_id == "turn-1"
        return TurnTrajectoryRecord(
            id="turn-1",
            schema_version=1,
            kind="chat.turn",
            status="failed",
            thread_id="thread-1",
            root_thread_id="root-1",
            request_id="req-query",
            trace_id="trace-query",
            root_span_id="span-root",
            environment="staging",
            deployment="focus-agent-blue",
            app_version="1.2.3",
            user_id_hash="hashed",
            scene="long_dialog_research",
            started_at=datetime(2026, 4, 21, 10, 0, tzinfo=timezone.utc),
            finished_at=datetime(2026, 4, 21, 10, 0, 1, tzinfo=timezone.utc),
            answer="answer",
            error="boom",
            selected_model="openai:gpt-4.1-mini",
            selected_thinking_mode="medium",
            metrics={"latency_ms": 1000.0, "tool_calls": 2},
            plan_meta={},
            trajectory=[],
        )

    def list_steps_by_turn_ids(self, turn_ids):
        assert turn_ids == ["turn-1"]
        return {
            "turn-1": [
                {
                    "turn_id": "turn-1",
                    "step_index": 0,
                    "tool": "web_search",
                    "args": {"query": "docs"},
                    "observation": "found docs",
                    "duration_ms": 44.0,
                    "cache_hit": False,
                    "fallback_used": True,
                    "fallback_group": "web_search",
                    "parallel_batch_size": None,
                    "runtime": {},
                    "observation_truncated": False,
                    "error": None,
                    "created_at": datetime(2026, 4, 21, 10, 0, tzinfo=timezone.utc),
                }
            ]
        }


def _runtime_stub(*, auth_enabled: bool = False, trajectory_recorder=None, trajectory_enabled=None):
    return SimpleNamespace(
        settings=SimpleNamespace(
            auth_enabled=auth_enabled,
            database_uri="postgresql://example",
            app_version="1.2.3",
            app_environment="staging",
            deployment_name="focus-agent-blue",
            trajectory_enabled=trajectory_enabled,
        ),
        graph=object(),
        repo=object(),
        branch_service=object(),
        tool_registry=object(),
        skill_registry=object(),
        trajectory_recorder=trajectory_recorder if trajectory_recorder is not None else _FakeTrajectoryRepo(),
    )


def _build_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    _with_stub_frontend(monkeypatch, tmp_path)
    app = create_app()
    app.state.runtime = _runtime_stub()
    return TestClient(app)


def test_trajectory_api_list_detail_and_stats(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _build_client(monkeypatch, tmp_path)

    list_response = client.get(
        "/v1/observability/trajectory",
        params={
            "request_id": "req-query",
            "trace_id": "trace-query",
            "thread_id": "thread-1",
            "status": "failed",
        },
    )
    stats_response = client.get(
        "/v1/observability/trajectory/stats",
        params={"request_id": "req-query", "trace_id": "trace-query", "fallback_used": "true"},
    )
    detail_response = client.get("/v1/observability/trajectory/turn-1")

    assert list_response.status_code == 200
    assert list_response.json()["count"] == 1
    assert list_response.json()["filters"]["request_id"] == "req-query"
    assert list_response.json()["filters"]["trace_id"] == "trace-query"
    assert list_response.json()["filters"]["thread_id"] == "thread-1"
    assert list_response.json()["filters"]["status"] == ["failed"]
    assert list_response.json()["items"][0]["status"] == "failed"
    assert list_response.json()["items"][0]["trace_id"] == "trace-query"

    assert stats_response.status_code == 200
    assert stats_response.json()["stats"]["overview"]["turn_count"] == 1
    assert stats_response.json()["stats"]["by_model"][0]["key"] == "openai:gpt-4.1-mini"
    assert stats_response.json()["stats"]["by_day"][0]["key"] == "2026-04-21"
    assert stats_response.json()["filters"]["request_id"] == "req-query"
    assert stats_response.json()["filters"]["fallback_used"] is True

    assert detail_response.status_code == 200
    assert detail_response.json()["item"]["id"] == "turn-1"
    assert detail_response.json()["item"]["request_id"] == "req-query"
    assert detail_response.json()["item"]["trace_id"] == "trace-query"
    assert detail_response.json()["item"]["trajectory"][0]["tool"] == "web_search"


def test_observability_overview_readyz_and_metrics(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _build_client(monkeypatch, tmp_path)

    overview_response = client.get(
        "/v1/observability/overview",
        params={"request_id": "req-query", "trace_id": "trace-query", "fallback_used": "true"},
    )
    readyz_response = client.get("/readyz")
    metrics_response = client.get("/metrics")

    assert overview_response.status_code == 200
    overview_body = overview_response.json()
    assert overview_body["trajectory_available"] is True
    assert overview_body["filters"]["request_id"] == "req-query"
    assert overview_body["runtime"]["ready"] is True
    assert overview_body["runtime"]["checks"][-1]["name"] == "trajectory_recorder"
    assert overview_body["stats"]["overview"]["turn_count"] == 1

    assert readyz_response.status_code == 200
    readyz_body = readyz_response.json()
    assert readyz_body["status"] == "ok"
    assert readyz_body["ready"] is True
    assert readyz_body["deployment"] == "focus-agent-blue"

    assert metrics_response.status_code == 200
    assert "text/plain; version=0.0.4" in metrics_response.headers["content-type"]
    assert "focus_agent_runtime_ready 1" in metrics_response.text
    assert 'focus_agent_runtime_build_info{version="1.2.3",environment="staging",deployment="focus-agent-blue"} 1' in metrics_response.text
    assert "focus_agent_trajectory_turn_count 1" in metrics_response.text


def test_readyz_returns_503_for_degraded_runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _with_stub_frontend(monkeypatch, tmp_path)
    app = create_app()
    app.state.runtime = _runtime_stub(trajectory_recorder=None, trajectory_enabled=True)
    app.state.runtime.trajectory_recorder = None
    client = TestClient(app)

    response = client.get("/readyz")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["ready"] is False
    trajectory_check = next(item for item in body["checks"] if item["name"] == "trajectory_recorder")
    assert trajectory_check["ready"] is False


def test_trajectory_api_detail_returns_404_when_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class _MissingRepo(_FakeTrajectoryRepo):
        def get_turn(self, turn_id):
            return None

    _with_stub_frontend(monkeypatch, tmp_path)
    app = create_app()
    app.state.runtime = _runtime_stub(trajectory_recorder=_MissingRepo())
    client = TestClient(app)

    response = client.get("/v1/observability/trajectory/missing")

    assert response.status_code == 404
    assert response.json()["message"] == "Trajectory turn not found: missing"


def test_trajectory_api_requires_auth_when_enabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _with_stub_frontend(monkeypatch, tmp_path)
    app = create_app()
    app.state.runtime = _runtime_stub(auth_enabled=True)
    client = TestClient(app)

    response = client.get("/v1/observability/trajectory")

    assert response.status_code == 401
    assert response.json()["message"] == "Missing bearer token."


def test_trajectory_api_returns_503_without_repository(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _with_stub_frontend(monkeypatch, tmp_path)
    app = create_app()
    app.state.runtime = _runtime_stub(trajectory_recorder=None)
    app.state.runtime.trajectory_recorder = None
    app.state.runtime.settings.database_uri = None
    client = TestClient(app)

    response = client.get("/v1/observability/trajectory")

    assert response.status_code == 503
    assert "Trajectory observability requires" in response.json()["message"]
