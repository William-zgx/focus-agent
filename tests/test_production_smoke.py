from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts import production_smoke


def test_production_smoke_dry_run_writes_report(tmp_path: Path) -> None:
    report_path = tmp_path / "production-smoke.json"

    exit_code = production_smoke.main(
        [
            "--dry-run",
            "--base-url",
            "https://focus-agent.example.com",
            "--report-json",
            str(report_path),
        ]
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert report["report_type"] == "production_smoke"
    assert report["status"] == "dry-run"
    assert report["passed"] is True
    assert report["summary"]["total"] == 13
    assert set(report["summary"]["by_category"]) == {
        "api",
        "sdk",
        "web",
        "graph",
        "security",
        "rate-limit",
    }
    assert {check["status"] for check in report["checks"]} == {"dry-run"}
    assert report["checks"][0]["url"] == "https://focus-agent.example.com/healthz"
    graph_checks = {check["name"]: check for check in report["checks"] if check["category"] == "graph"}
    assert graph_checks["graph_min_conversation"]["expected_statuses"] == [200, 201]
    assert graph_checks["graph_min_chat_turn"]["expected_statuses"] == [200, 201]
    assert {check["category"] for check in report["checks"]} == {
        "api",
        "sdk",
        "web",
        "graph",
        "security",
        "rate-limit",
    }
    assert any(check["name"] == "graph_min_chat_turn" and check["method"] == "POST" for check in report["checks"])


def test_production_smoke_v2_stream_graph_and_thresholds(
    monkeypatch,
    tmp_path: Path,
) -> None:
    stream_path = tmp_path / "stream-events.json"
    stream_path.write_text(
        json.dumps(
            {
                "events": [
                    {"event": "visible_text.delta", "data": {"delta": "hello"}},
                    {"event": "turn.completed", "data": {"thread_id": "production-smoke"}},
                ]
            }
        ),
        encoding="utf-8",
    )

    def fake_http_check(
        name: str,
        url: str,
        *,
        auth_token: str | None,
        body: dict[str, Any] | None,
        category: str,
        method: str,
        expected_statuses,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        headers = {}
        if name == "rate_limit_probe":
            headers = {"X-RateLimit-Limit": "20", "X-RateLimit-Remaining": "19"}
        status_code = 201 if name == "graph_min_conversation" else 200
        return {
            "category": category,
            "expected_statuses": list(expected_statuses),
            "name": name,
            "url": url,
            "method": method,
            "status": "passed",
            "passed": True,
            "status_code": status_code,
            "detail": "OK",
            "response_headers": headers,
        }

    monkeypatch.setattr(production_smoke, "_http_check", fake_http_check)

    report = production_smoke.build_report(
        base_url="https://focus-agent.example.com",
        stream_events_json=stream_path,
        rate_limit_min_limit=10,
    )

    assert report["passed"] is True
    assert report["report_version"] == 2
    assert report["stream_events"]["status"] == "passed"
    assert report["stream_events"]["events_seen"] == ["turn.completed", "visible_text.delta"]
    assert report["graph_turn"]["status"] == "passed"
    assert report["thresholds"]["rate_limit"]["observed"]["limit"] == 20
    assert report["thresholds"]["rate_limit"]["min_limit"] == 10
    assert report["summary"]["v2_failed_checks"] == []


def test_production_smoke_live_requires_stream_contract_input(monkeypatch) -> None:
    def fake_http_check(
        name: str,
        url: str,
        *,
        auth_token: str | None,
        body: dict[str, Any] | None,
        category: str,
        method: str,
        expected_statuses,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        headers = {"X-RateLimit-Limit": "20", "X-RateLimit-Remaining": "19"} if name == "rate_limit_probe" else {}
        return {
            "category": category,
            "expected_statuses": list(expected_statuses),
            "name": name,
            "url": url,
            "method": method,
            "status": "passed",
            "passed": True,
            "status_code": 201 if name == "graph_min_conversation" else 200,
            "detail": "OK",
            "response_headers": headers,
        }

    monkeypatch.setattr(production_smoke, "_http_check", fake_http_check)

    report = production_smoke.build_report(base_url="https://focus-agent.example.com")

    assert report["passed"] is False
    assert report["stream_events"]["status"] == "failed"
    assert "stream_events" in report["summary"]["v2_failed_checks"]


def test_production_smoke_graph_auth_failure_blocks_graph_turn(monkeypatch, tmp_path: Path) -> None:
    stream_path = tmp_path / "stream-events.json"
    stream_path.write_text(
        json.dumps({"events": [{"event": "turn.completed", "data": {"thread_id": "production-smoke"}}]}),
        encoding="utf-8",
    )

    def fake_http_check(
        name: str,
        url: str,
        *,
        auth_token: str | None,
        body: dict[str, Any] | None,
        category: str,
        method: str,
        expected_statuses,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        status_code = 403 if name.startswith("graph_") else 200
        headers = {"X-RateLimit-Limit": "20", "X-RateLimit-Remaining": "19"} if name == "rate_limit_probe" else {}
        passed = status_code in expected_statuses
        return {
            "category": category,
            "expected_statuses": list(expected_statuses),
            "name": name,
            "url": url,
            "method": method,
            "status": "passed" if passed else "failed",
            "passed": passed,
            "status_code": status_code,
            "detail": "Forbidden" if status_code == 403 else "OK",
            "response_headers": headers,
        }

    monkeypatch.setattr(production_smoke, "_http_check", fake_http_check)

    report = production_smoke.build_report(
        base_url="https://focus-agent.example.com",
        stream_events_json=stream_path,
    )

    assert report["passed"] is False
    assert report["graph_turn"]["status"] == "failed"
    assert report["graph_turn"]["failed_checks"] == ["graph_min_conversation", "graph_min_chat_turn"]
