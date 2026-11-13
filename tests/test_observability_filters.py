from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from focus_agent.api.main import create_app
from focus_agent.api.route_utils import observability_filters


class _EmptyTrajectoryRepo:
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


def _build_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    (dist_dir / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "test-api-key")
    monkeypatch.setenv("WEB_APP_DIST_DIR", str(dist_dir))
    monkeypatch.setenv("WEB_APP_DEV_SERVER_URL", "")
    monkeypatch.setenv("AUTH_ENABLED", "false")
    app = create_app()
    app.state.runtime = SimpleNamespace(
        settings=SimpleNamespace(
            auth_enabled=False,
            database_uri="postgresql://example",
            model="openai:gpt-4.1-mini",
        ),
        trajectory_recorder=_EmptyTrajectoryRepo(),
    )
    return TestClient(app)


def test_observability_filter_dependency_signatures_and_pagination() -> None:
    filter_names = (
        "request_id",
        "trace_id",
        "thread_id",
        "root_thread_id",
        "parent_thread_id",
        "branch_id",
        "branch_role",
        "status",
        "scene",
        "kind",
        "tool",
        "model",
        "fallback_used",
        "cache_hit",
        "has_error",
        "started_after",
        "started_before",
        "min_latency_ms",
        "max_latency_ms",
        "min_tool_calls",
        "max_tool_calls",
    )
    base_signature = inspect.signature(observability_filters.observability_trajectory_params)
    list_signature = inspect.signature(observability_filters.observability_trajectory_list_params)

    assert tuple(base_signature.parameters) == filter_names + ("newest_first",)
    assert tuple(list_signature.parameters) == filter_names + (
        "limit",
        "offset",
        "newest_first",
    )
    for signature in (base_signature, list_signature):
        assert signature.parameters["status"].default.default is None
        assert signature.parameters["model"].default.alias == "model"
    assert "limit" not in base_signature.parameters
    assert "offset" not in base_signature.parameters
    assert list_signature.parameters["limit"].default.default == 100
    assert list_signature.parameters["limit"].default.metadata[0].ge == 0
    assert list_signature.parameters["offset"].default.default == 0
    assert list_signature.parameters["offset"].default.metadata[0].ge == 0

    multi_value_filters = {
        "branch_role": None,
        "status": ["failed", "succeeded"],
        "scene": None,
        "kind": None,
        "tool": None,
        "model": ["model-a", "model-b"],
    }
    base = observability_filters.observability_trajectory_params(**multi_value_filters)
    listed = observability_filters.observability_trajectory_list_params(
        **multi_value_filters,
        limit=7,
        offset=3,
        newest_first=False,
    )

    assert base.limit is None
    assert base.query().limit is None
    assert base.payload() == {
        "status": ["failed", "succeeded"],
        "model": ["model-a", "model-b"],
    }
    assert base.query().status == ["failed", "succeeded"]
    assert base.query().selected_model == ["model-a", "model-b"]
    assert listed.limit == 7
    assert listed.offset == 3
    assert listed.query().limit == 7
    assert listed.query().offset == 3
    assert listed.query().newest_first is False


def test_observability_openapi_repeated_filters_and_pagination(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _build_client(monkeypatch, tmp_path)

    response = client.get(
        "/v1/observability/trajectory",
        params=[
            ("status", "failed"),
            ("status", "succeeded"),
            ("model", "model-a"),
            ("model", "model-b"),
        ],
    )
    custom_page = client.get(
        "/v1/observability/trajectory",
        params={"limit": 7, "offset": 3},
    )
    openapi_response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["filters"]["status"] == ["failed", "succeeded"]
    assert response.json()["filters"]["model"] == ["model-a", "model-b"]
    assert response.json()["limit"] == 100
    assert response.json()["offset"] == 0
    assert custom_page.status_code == 200
    assert custom_page.json()["limit"] == 7
    assert custom_page.json()["offset"] == 3

    assert openapi_response.status_code == 200
    schema = openapi_response.json()
    list_parameters = schema["paths"]["/v1/observability/trajectory"]["get"]["parameters"]
    parameters_by_name = {parameter["name"]: parameter for parameter in list_parameters}
    assert parameters_by_name["limit"]["schema"] == {
        "default": 100,
        "minimum": 0,
        "title": "Limit",
        "type": "integer",
    }
    assert parameters_by_name["offset"]["schema"] == {
        "default": 0,
        "minimum": 0,
        "title": "Offset",
        "type": "integer",
    }
    assert parameters_by_name["newest_first"]["schema"]["default"] is True
    assert parameters_by_name["status"]["schema"]["anyOf"][0] == {
        "items": {"type": "string"},
        "type": "array",
    }
    assert parameters_by_name["model"]["schema"]["anyOf"][0] == {
        "items": {"type": "string"},
        "type": "array",
    }
    for path in ("/v1/observability/overview", "/v1/observability/trajectory/stats"):
        names = {parameter["name"] for parameter in schema["paths"][path]["get"]["parameters"]}
        assert "limit" not in names
        assert "offset" not in names
