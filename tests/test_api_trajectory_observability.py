from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

import focus_agent.api.main as api_main
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

    def export_turns(self, query):
        if query.status == "succeeded":
            return []
        if query.status is not None:
            assert query.status == "failed"
        if query.limit is not None:
            assert query.limit in {1, 100}
        records = [
            {
                "id": "turn-1",
                "schema_version": 1,
                "kind": "chat.turn",
                "status": "failed",
                "thread_id": "thread-1",
                "root_thread_id": "root-1",
                "scene": "long_dialog_research",
                "user_message": "search docs",
                "answer": "answer",
                "selected_model": "openai:gpt-4.1-mini",
                "metrics": {"latency_ms": 1000.0, "tool_calls": 2, "fallback_uses": 1},
                "error": "boom",
                "trajectory": [{"tool": "web_search", "duration_ms": 44.0, "fallback_used": True}],
            },
            {
                "id": "turn-2",
                "schema_version": 1,
                "kind": "chat.turn",
                "status": "failed",
                "thread_id": "thread-1",
                "root_thread_id": "root-1",
                "scene": "long_dialog_research",
                "user_message": "read README",
                "answer": "read answer",
                "selected_model": "openai:gpt-4.1-mini",
                "metrics": {"latency_ms": 500.0, "tool_calls": 1, "fallback_uses": 0},
                "error": "still failed",
                "trajectory": [{"tool": "read_file", "duration_ms": 12.0}],
            },
        ]
        if query.limit is not None:
            return records[: query.limit]
        return records

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


def test_trajectory_batch_promote_preview_filters_failed_turns_and_honors_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: list[dict[str, object]] = []
    client = _build_client(monkeypatch, tmp_path)

    def _fake_promote(record, **kwargs):
        captured.append({"record": record, **kwargs})
        case_id = f"{kwargs['case_id_prefix']}-{record['id']}"
        return {
            "source_turn_id": record["id"],
            "case_id": case_id,
            "dataset_record": {
                "id": case_id,
                "scene": record["scene"],
                "input": {"user_message": record["user_message"]},
                "expected": {},
                "tags": ["trajectory_replay"],
                "skill_hints": [],
                "setup": [],
                "judge": {"rule": False},
                "origin": {"trajectory_id": record["id"]},
            },
            "jsonl": f'{{"id":"{case_id}"}}',
        }

    monkeypatch.setattr(api_main, "build_promoted_dataset_payload", _fake_promote)

    response = client.post(
        "/v1/observability/trajectory/batch/promote-preview",
        json={
            "status": ["failed"],
            "limit": 1,
            "case_id_prefix": "batch",
            "copy_answer_substring": True,
            "answer_substring_chars": 40,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["limit"] == 1
    assert body["filters"]["status"] == ["failed"]
    assert body["items"][0]["source_turn_id"] == "turn-1"
    assert body["items"][0]["dataset_record"]["origin"]["trajectory_id"] == "turn-1"
    assert body["jsonl"] == '{"id":"batch-turn-1"}'
    assert captured[0]["record"]["id"] == "turn-1"
    assert captured[0]["copy_answer_substring"] is True


def test_trajectory_batch_promote_preview_returns_empty_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    called = False
    client = _build_client(monkeypatch, tmp_path)

    def _fake_promote(record, **kwargs):  # noqa: ARG001
        nonlocal called
        called = True
        raise AssertionError("promote helper should not run for an empty batch")

    monkeypatch.setattr(api_main, "build_promoted_dataset_payload", _fake_promote)

    response = client.post(
        "/v1/observability/trajectory/batch/promote-preview",
        json={"status": ["succeeded"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 0
    assert body["items"] == []
    assert body["jsonl"] == ""
    assert body["filters"]["status"] == ["succeeded"]
    assert called is False


def test_trajectory_batch_replay_compare_returns_summary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _build_client(monkeypatch, tmp_path)

    def _fake_promote(record, **kwargs):
        case_id = f"{kwargs['case_id_prefix']}-{record['id']}"
        return {
            "source_turn_id": record["id"],
            "case_id": case_id,
            "dataset_record": {
                "id": case_id,
                "scene": record["scene"],
                "input": {"user_message": record["user_message"]},
                "expected": {},
                "tags": ["trajectory_replay"],
                "skill_hints": [],
                "setup": [],
                "judge": {"rule": False},
                "origin": {"trajectory_id": record["id"]},
            },
            "jsonl": f'{{"id":"{case_id}"}}',
        }

    def _fake_replay(record, **kwargs):
        case_id = f"{kwargs['case_id_prefix']}-{record['id']}"
        replay_passed = record["id"] == "turn-1"
        return {
            "source_turn_id": record["id"],
            "replay_result": {
                "case_id": case_id,
                "passed": replay_passed,
                "answer": f"replayed {record['id']}",
                "metrics": {"latency_ms": 25.0, "tool_calls": 1},
                "error": None if replay_passed else "mismatch",
            },
            "comparison": {
                "case_id": case_id,
                "trajectory_id": record["id"],
                "source_status": record["status"],
                "source_failed": record["status"] != "succeeded",
                "replay_passed": replay_passed,
                "replay_error": None if replay_passed else "mismatch",
                "source_tools": [step["tool"] for step in record["trajectory"]],
                "replay_tools": ["read_file"],
                "tool_path_changed": record["id"] == "turn-1",
                "source_tool_calls": record["metrics"]["tool_calls"],
                "replay_tool_calls": 1,
                "source_latency_ms": record["metrics"]["latency_ms"],
                "replay_latency_ms": 25.0,
                "source_fallback_uses": record["metrics"]["fallback_uses"],
                "replay_fallback_uses": 0,
                "source_cache_hits": 0,
                "replay_cache_hits": 0,
                "source_answer_preview": record["answer"],
                "replay_answer_preview": f"replayed {record['id']}",
            },
        }

    monkeypatch.setattr(api_main, "build_promoted_dataset_payload", _fake_promote)
    monkeypatch.setattr(api_main, "run_replay_for_turn", _fake_replay)

    response = client.post(
        "/v1/observability/trajectory/batch/replay-compare",
        json={"status": ["failed"], "case_id_prefix": "batch", "model": "moonshot:kimi-k2.6"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["filters"]["status"] == ["failed"]
    assert body["summary"] == {
        "total": 2,
        "passed": 1,
        "failed": 1,
        "source_failed": 2,
        "tool_path_changed": 1,
    }
    assert body["results"][0]["model_used"] == "moonshot:kimi-k2.6"
    assert body["results"][0]["replay_case_jsonl"] == '{"id":"batch-turn-1"}'
    assert body["results"][1]["comparison"]["replay_error"] == "mismatch"


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
    batch_response = client.post("/v1/observability/trajectory/batch/replay-compare", json={})

    assert response.status_code == 503
    assert "Trajectory observability requires" in response.json()["message"]
    assert batch_response.status_code == 503
    assert "Trajectory observability requires" in batch_response.json()["message"]
