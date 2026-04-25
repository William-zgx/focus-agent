import re
from pathlib import Path

from fastapi.testclient import TestClient

from focus_agent.api.contracts import (
    AgentTeamMergeBundleResponse,
    AgentTeamSessionListResponse,
    AgentTeamTaskListResponse,
    ApplyAgentTeamMergeDecisionRequest,
    CreateAgentTeamSessionRequest,
    CreateAgentTeamTaskRequest,
    DispatchAgentTeamSessionRequest,
    RecordAgentTeamTaskOutputRequest,
    UpdateAgentTeamTaskRequest,
)
from focus_agent.api.main import create_app


ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "apps" / "web"
SDK_ROOT = ROOT / "frontend-sdk"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _interface_body(text: str, name: str) -> str:
    match = re.search(rf"export interface {re.escape(name)} \{{(?P<body>.*?)\n\}}", text, re.S)
    assert match, f"missing TypeScript interface {name}"
    return match.group("body")


def _type_body(text: str, name: str) -> str:
    match = re.search(rf"export type {re.escape(name)} =(?P<body>.*?);", text, re.S)
    assert match, f"missing TypeScript type {name}"
    return match.group("body")


def _assert_interface_has_fields(body: str, fields: set[str]) -> None:
    for field in sorted(fields):
        assert re.search(rf"\b{re.escape(field)}\??:", body), f"missing TypeScript field {field}"


def test_agent_team_app_route_serves_built_spa_subpaths(monkeypatch, tmp_path: Path):
    dist_dir = tmp_path / "dist"
    assets_dir = dist_dir / "assets"
    assets_dir.mkdir(parents=True)
    (dist_dir / "index.html").write_text(
        "<!doctype html><html><body><div id='root'>agent-team-built-app</div></body></html>",
        encoding="utf-8",
    )
    (assets_dir / "main.js").write_text("console.log('agent-team')", encoding="utf-8")

    monkeypatch.setenv("WEB_APP_DIST_DIR", str(dist_dir))
    monkeypatch.setenv("WEB_APP_DEV_SERVER_URL", "")
    app = create_app()
    client = TestClient(app)

    route_response = client.get("/app/agent-team")
    session_route_response = client.get("/app/agent-team/session-123")
    asset_response = client.get("/app/assets/main.js")

    assert route_response.status_code == 200
    assert "agent-team-built-app" in route_response.text
    assert session_route_response.status_code == 200
    assert "agent-team-built-app" in session_route_response.text
    assert asset_response.status_code == 200
    assert "console.log('agent-team')" in asset_response.text


def test_agent_team_route_is_registered_in_frontend_router():
    router_text = _read(WEB_ROOT / "src" / "app" / "router.tsx")

    assert 'path: "/agent-team"' in router_text
    assert 'path: "/agent-team/$sessionId"' in router_text
    assert "component: AgentTeamWorkbenchPage" in router_text
    assert "agentTeamRoute" in router_text
    assert "agentTeamSessionRoute" in router_text


def test_agent_team_sdk_methods_match_backend_endpoints():
    client_text = _read(SDK_ROOT / "src" / "client.ts")

    expected_methods = {
        "createAgentTeamSession": "/v1/agent-team/sessions",
        "listAgentTeamSessions": "/v1/agent-team/sessions",
        "getAgentTeamSession": "/v1/agent-team/sessions/${encodeURIComponent(sessionId)}",
        "dispatchAgentTeamSession": "/v1/agent-team/sessions/${encodeURIComponent(sessionId)}/dispatch",
        "createAgentTeamTask": "/v1/agent-team/sessions/${encodeURIComponent(sessionId)}/tasks",
        "listAgentTeamTasks": "/v1/agent-team/sessions/${encodeURIComponent(sessionId)}/tasks",
        "getAgentTeamTaskStatus": "/v1/agent-team/tasks/${encodeURIComponent(taskId)}",
        "updateAgentTeamTask": "/v1/agent-team/tasks/${encodeURIComponent(taskId)}",
        "recordAgentTeamTaskOutput": "/v1/agent-team/tasks/${encodeURIComponent(taskId)}/outputs",
        "prepareAgentTeamMergeBundle": "/v1/agent-team/sessions/${encodeURIComponent(sessionId)}/merge-bundle",
        "recordAgentTeamMergeDecision": "/v1/agent-team/sessions/${encodeURIComponent(sessionId)}/merge-decision",
    }

    for method, endpoint in expected_methods.items():
        assert method in client_text
        assert endpoint in client_text


def test_agent_team_sdk_and_web_contracts_share_api_shape():
    sdk_types = _read(SDK_ROOT / "src" / "types.ts")
    web_types = _read(WEB_ROOT / "src" / "features" / "agent-team" / "types.ts")

    session_request_fields = set(CreateAgentTeamSessionRequest.model_fields)
    dispatch_request_fields = set(DispatchAgentTeamSessionRequest.model_fields)
    task_create_fields = set(CreateAgentTeamTaskRequest.model_fields) - {"parent_thread_id"}
    task_update_fields = set(UpdateAgentTeamTaskRequest.model_fields)
    output_fields = set(RecordAgentTeamTaskOutputRequest.model_fields) - {"kind", "test_evidence"}
    merge_decision_fields = set(ApplyAgentTeamMergeDecisionRequest.model_fields) - {"approved", "action"}

    _assert_interface_has_fields(
        _interface_body(sdk_types, "FocusAgentAgentTeamCreateSessionRequest"),
        session_request_fields,
    )
    _assert_interface_has_fields(
        _interface_body(web_types, "AgentTeamCreateSessionRequest"),
        session_request_fields,
    )
    _assert_interface_has_fields(
        _interface_body(sdk_types, "FocusAgentAgentTeamDispatchRequest"),
        dispatch_request_fields,
    )
    _assert_interface_has_fields(
        _interface_body(web_types, "AgentTeamDispatchRequest"),
        dispatch_request_fields,
    )
    _assert_interface_has_fields(
        _interface_body(sdk_types, "FocusAgentAgentTeamCreateTaskRequest"),
        task_create_fields,
    )
    _assert_interface_has_fields(
        _interface_body(web_types, "AgentTeamCreateTaskRequest"),
        {"role", "goal", "scope", "dependencies"},
    )
    _assert_interface_has_fields(
        _interface_body(sdk_types, "FocusAgentAgentTeamUpdateTaskRequest"),
        task_update_fields,
    )
    _assert_interface_has_fields(
        _interface_body(sdk_types, "FocusAgentAgentTeamRecordTaskOutputRequest"),
        output_fields,
    )
    _assert_interface_has_fields(
        _interface_body(sdk_types, "FocusAgentAgentTeamMergeDecisionRequest"),
        merge_decision_fields | {"apply", "next_action"},
    )

    assert set(AgentTeamSessionListResponse.model_fields) == {"sessions", "items", "count"}
    assert set(AgentTeamTaskListResponse.model_fields) == {"tasks", "items", "count"}
    assert set(AgentTeamMergeBundleResponse.model_fields) == {"bundle"}

    for method in [
        "createAgentTeamSession",
        "getAgentTeamSession",
        "dispatchAgentTeamSession",
        "listAgentTeamTasks",
        "createAgentTeamTask",
        "prepareAgentTeamMergeBundle",
    ]:
        assert method in _interface_body(web_types, "AgentTeamClientContract")
        assert method in _read(SDK_ROOT / "src" / "client.ts")


def test_agent_team_role_and_status_unions_match_sdk_and_web_contracts():
    sdk_types = _read(SDK_ROOT / "src" / "types.ts")
    web_types = _read(WEB_ROOT / "src" / "features" / "agent-team" / "types.ts")

    for literal in [
        "planning",
        "running",
        "awaiting_review",
        "completed",
        "planner",
        "backend_executor",
        "frontend_executor",
        "test_engineer",
        "reviewer",
        "verifier",
        "pending",
        "blocked",
        "done",
    ]:
        assert f'"{literal}"' in _type_body(sdk_types, "FocusAgentAgentTeamSessionStatus") + _type_body(
            sdk_types,
            "FocusAgentAgentTeamTaskRole",
        ) + _type_body(sdk_types, "FocusAgentAgentTeamTaskStatus")
        assert f'"{literal}"' in web_types
