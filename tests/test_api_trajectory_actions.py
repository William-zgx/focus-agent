from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

import focus_agent.api.main as api_main
from focus_agent.api.main import create_app


def _with_stub_frontend(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    (dist_dir / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "test-api-key")
    monkeypatch.setenv("WEB_APP_DIST_DIR", str(dist_dir))
    monkeypatch.setenv("WEB_APP_DEV_SERVER_URL", "")


class _FakeTrajectoryRepo:
    def list_turns(self, query):  # noqa: ARG002
        return []

    def get_turn(self, turn_id):  # noqa: ARG002
        return None

    def list_steps_by_turn_ids(self, turn_ids):  # noqa: ARG002
        return {}

    def get_turn_stats(self, query):  # noqa: ARG002
        return {}

    def export_turns(self, query):  # noqa: ARG002
        return []


def _build_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    auth_enabled: bool = False,
) -> TestClient:
    _with_stub_frontend(monkeypatch, tmp_path)
    monkeypatch.setenv("AUTH_ENABLED", "true" if auth_enabled else "false")
    app = create_app()
    app.state.runtime = SimpleNamespace(
        settings=SimpleNamespace(
            auth_enabled=auth_enabled,
            database_uri="postgresql://example",
            model="openai:gpt-4.1-mini",
        ),
        trajectory_recorder=_FakeTrajectoryRepo(),
    )
    return TestClient(app)


def test_trajectory_replay_action_returns_display_payload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}
    client = _build_client(monkeypatch, tmp_path)

    monkeypatch.setattr(
        api_main,
        "load_turn_export",
        lambda repo, *, turn_id: {
            "id": turn_id,
            "user_message": "Read README",
            "scene": "long_dialog_research",
            "trajectory": [{"tool": "read_file"}],
        },
    )

    def _fake_promote(record, **kwargs):
        captured["promote"] = {"record": record, **kwargs}
        return {
            "source_turn_id": str(record.get("id") or ""),
            "case_id": "obs-turn-1",
            "dataset_record": {
                "id": "obs-turn-1",
                "scene": "long_dialog_research",
                "input": {"user_message": "Read README"},
                "expected": {"max_tool_calls": 1},
                "tags": ["trajectory_replay"],
                "skill_hints": ["docs"],
                "setup": [],
                "judge": {"rule": True, "llm": {"enabled": False}},
                "origin": {"trajectory_id": record.get("id")},
            },
            "jsonl": '{"id":"obs-turn-1"}',
        }

    def _fake_replay(record, **kwargs):
        captured["replay"] = {"record": record, **kwargs}
        return {
            "source_turn_id": str(record.get("id") or ""),
            "replay_case": {
                "id": "obs-turn-1",
                "scene": "long_dialog_research",
                "input": {"user_message": "Read README"},
                "expected": {"max_tool_calls": 1},
                "tags": ["trajectory_replay"],
                "origin": {"trajectory_id": record.get("id")},
            },
            "replay_result": {
                "case_id": "obs-turn-1",
                "passed": True,
                "answer": "README summary",
                "verdicts": [
                    {
                        "kind": "rule",
                        "passed": True,
                        "reasoning": "all checks passed",
                        "confidence": 0.9,
                        "details": {},
                    }
                ],
                "trajectory": [
                    {
                        "tool": "read_file",
                        "args": {"path": "README.md"},
                        "observation": "Focus Agent is compact.",
                        "duration_ms": 12.0,
                    }
                ],
                "metrics": {"latency_ms": 35.0, "tool_calls": 1, "cache_hits": 0},
                "error": None,
                "tags": ["trajectory_replay"],
            },
            "comparison": {
                "case_id": "obs-turn-1",
                "trajectory_id": record.get("id"),
                "source_status": "failed",
                "source_failed": True,
                "replay_passed": True,
                "replay_error": None,
                "source_tools": ["read_file", "web_search"],
                "replay_tools": ["read_file"],
                "tool_path_changed": True,
                "source_tool_calls": 2,
                "replay_tool_calls": 1,
                "source_latency_ms": 90.0,
                "replay_latency_ms": 35.0,
                "source_fallback_uses": 1,
                "replay_fallback_uses": 0,
                "source_cache_hits": 0,
                "replay_cache_hits": 0,
                "source_answer_preview": "old",
                "replay_answer_preview": "README summary",
            },
        }

    monkeypatch.setattr(api_main, "build_promoted_dataset_payload", _fake_promote)
    monkeypatch.setattr(api_main, "run_replay_for_turn", _fake_replay)

    response = client.post(
        "/v1/observability/trajectory/turn-1/replay",
        json={
            "model": "moonshot:kimi-k2.6",
            "case_id_prefix": "obs",
            "copy_tool_trajectory": True,
            "copy_answer_substring": True,
            "answer_substring_chars": 80,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_turn_id"] == "turn-1"
    assert body["model_used"] == "moonshot:kimi-k2.6"
    assert body["replay_case"]["skill_hints"] == ["docs"]
    assert body["replay_case_jsonl"] == '{"id":"obs-turn-1"}'
    assert body["replay_result"]["trajectory"][0]["tool"] == "read_file"
    assert body["comparison"]["tool_path_changed"] is True
    assert captured["promote"]["case_id_prefix"] == "obs"
    assert captured["replay"]["model"] == "moonshot:kimi-k2.6"
    assert captured["replay"]["copy_answer_substring"] is True


def test_trajectory_promote_action_returns_dataset_preview(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}
    client = _build_client(monkeypatch, tmp_path)

    monkeypatch.setattr(
        api_main,
        "load_turn_export",
        lambda repo, *, turn_id: {
            "id": turn_id,
            "user_message": "Read README",
            "scene": "long_dialog_research",
            "trajectory": [],
        },
    )

    def _fake_promote(record, **kwargs):
        captured["promote"] = {"record": record, **kwargs}
        return {
            "source_turn_id": str(record.get("id") or ""),
            "case_id": "traj-turn-2",
            "dataset_record": {
                "id": "traj-turn-2",
                "scene": "long_dialog_research",
                "input": {"user_message": "Read README"},
                "expected": {},
                "tags": ["trajectory_replay"],
                "skill_hints": [],
                "setup": [],
                "judge": {"rule": False, "llm": {"enabled": False}},
                "origin": {"trajectory_id": record.get("id")},
            },
            "jsonl": '{"id":"traj-turn-2"}',
        }

    monkeypatch.setattr(api_main, "build_promoted_dataset_payload", _fake_promote)

    response = client.post(
        "/v1/observability/trajectory/turn-2/promote",
        json={
            "case_id_prefix": "traj",
            "copy_tool_trajectory": False,
            "copy_answer_substring": True,
            "answer_substring_chars": 64,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_turn_id"] == "turn-2"
    assert body["case_id"] == "traj-turn-2"
    assert body["dataset_record"]["origin"]["trajectory_id"] == "turn-2"
    assert body["jsonl"] == '{"id":"traj-turn-2"}'
    assert captured["promote"]["copy_answer_substring"] is True
    assert captured["promote"]["answer_substring_chars"] == 64


def test_trajectory_action_returns_404_when_turn_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _build_client(monkeypatch, tmp_path)
    monkeypatch.setattr(api_main, "load_turn_export", lambda repo, *, turn_id: None)

    response = client.post("/v1/observability/trajectory/missing/promote", json={})

    assert response.status_code == 404
    assert response.json()["message"] == "Trajectory turn not found: missing"


def test_trajectory_action_requires_auth_when_enabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _build_client(monkeypatch, tmp_path, auth_enabled=True)

    response = client.post("/v1/observability/trajectory/turn-1/replay", json={})

    assert response.status_code == 401
    assert response.json()["message"] == "Missing bearer token."
