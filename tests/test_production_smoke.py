from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from scripts import production_smoke

RELEASE_BINDING = {
    "commit_sha": "a" * 40,
    "deployment_id": "deploy-production-42",
    "deployment_version": "1.2.3",
    "environment": "production",
}
RELEASE_ENV = {
    "RELEASE_COMMIT_SHA": RELEASE_BINDING["commit_sha"],
    "RELEASE_DEPLOYMENT_ID": RELEASE_BINDING["deployment_id"],
    "RELEASE_DEPLOYMENT_VERSION": RELEASE_BINDING["deployment_version"],
    "RELEASE_ENVIRONMENT": RELEASE_BINDING["environment"],
}


def _set_release_env(monkeypatch: pytest.MonkeyPatch, values: dict[str, str]) -> None:
    for env_name in production_smoke.RELEASE_IDENTITY_ENV.values():
        monkeypatch.delenv(env_name, raising=False)
    for env_name, value in values.items():
        monkeypatch.setenv(env_name, value)


def _stream_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "release_binding": dict(RELEASE_BINDING),
        "events": [
            {"event": "message.delta", "data": {"delta": "hello"}},
            {
                "event": "run.completed",
                "data": {"thread_id": "production-smoke", "status": "succeeded"},
            },
        ],
    }
    payload.update(overrides)
    return payload


def _write_json(path: Path, payload: Any) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _passing_http_check(
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
    del auth_token, body, timeout_seconds
    headers = (
        {"X-RateLimit-Limit": "20", "X-RateLimit-Remaining": "19"}
        if name == "rate_limit_probe"
        else {}
    )
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
    graph_checks = {
        check["name"]: check for check in report["checks"] if check["category"] == "graph"
    }
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
    assert any(
        check["name"] == "graph_min_chat_turn" and check["method"] == "POST"
        for check in report["checks"]
    )


def test_production_smoke_v2_stream_graph_and_thresholds(
    monkeypatch,
    tmp_path: Path,
) -> None:
    stream_path = tmp_path / "stream-events.json"
    stream_path.write_text(
        json.dumps(
            {
                "events": [
                    {"event": "message.delta", "data": {"delta": "hello"}},
                    {
                        "event": "run.completed",
                        "data": {"thread_id": "production-smoke", "status": "succeeded"},
                    },
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
    assert report["stream_events"]["events_seen"] == ["message.delta", "run.completed"]
    raw_stream_report = stream_path.read_bytes()
    assert report["stream_events"]["source"]["bytes"] == len(raw_stream_report)
    assert (
        report["stream_events"]["source"]["sha256"] == hashlib.sha256(raw_stream_report).hexdigest()
    )
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
        headers = (
            {"X-RateLimit-Limit": "20", "X-RateLimit-Remaining": "19"}
            if name == "rate_limit_probe"
            else {}
        )
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
        json.dumps(
            {
                "events": [
                    {
                        "event": "run.completed",
                        "data": {"thread_id": "production-smoke", "status": "succeeded"},
                    }
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
        status_code = 403 if name.startswith("graph_") else 200
        headers = (
            {"X-RateLimit-Limit": "20", "X-RateLimit-Remaining": "19"}
            if name == "rate_limit_probe"
            else {}
        )
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
    assert report["graph_turn"]["failed_checks"] == [
        "graph_min_conversation",
        "graph_min_chat_turn",
    ]


def test_production_stream_json_requires_matching_fresh_release_envelope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _set_release_env(
        monkeypatch,
        {**RELEASE_ENV, "RELEASE_ENVIRONMENT": "prod"},
    )
    stream_path = _write_json(tmp_path / "stream-events.json", _stream_payload())

    stream_report = production_smoke._build_stream_events_report(
        auth_token=None,
        dry_run=False,
        stream_events_json=stream_path,
        stream_events_url=None,
        timeout_seconds=1,
    )

    validation = stream_report["source"]["evidence_validation"]
    assert stream_report["passed"] is True
    assert stream_report["source"]["type"] == "file"
    assert validation["status"] == "passed"
    assert validation["trusted"] is True
    assert validation["timestamp_source"] == "generated_at"
    assert validation["declared_binding"]["environment"] == "production"
    assert validation["expected_binding"]["environment"] == "production"


def test_production_stream_json_requires_object_envelope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _set_release_env(monkeypatch, RELEASE_ENV)
    stream_path = _write_json(tmp_path / "stream-events.json", _stream_payload()["events"])

    stream_report = production_smoke._build_stream_events_report(
        auth_token=None,
        dry_run=False,
        stream_events_json=stream_path,
        stream_events_url=None,
        timeout_seconds=1,
    )

    assert stream_report["passed"] is False
    assert stream_report["source"]["evidence_validation"]["status"] == "failed"
    assert any("must be a JSON object" in error for error in stream_report["errors"])


def test_production_stream_json_uses_release_evidence_timestamp_priority(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _set_release_env(monkeypatch, RELEASE_ENV)
    stream_path = _write_json(
        tmp_path / "stream-events.json",
        _stream_payload(
            generated_at="2026-07-12T12:00:00",
            checked_at=datetime.now(UTC).isoformat(),
        ),
    )

    stream_report = production_smoke._build_stream_events_report(
        auth_token=None,
        dry_run=False,
        stream_events_json=stream_path,
        stream_events_url=None,
        timeout_seconds=1,
    )

    validation = stream_report["source"]["evidence_validation"]
    assert stream_report["passed"] is False
    assert validation["timestamp_source"] == "generated_at"
    assert any("timezone" in error for error in stream_report["errors"])


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(
            {"events": _stream_payload()["events"], "release_binding": RELEASE_BINDING},
            id="missing-timestamp",
        ),
        pytest.param(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "release_binding": {
                    field: value
                    for field, value in RELEASE_BINDING.items()
                    if field != "deployment_id"
                },
                "events": _stream_payload()["events"],
            },
            id="missing-binding-field",
        ),
    ],
)
def test_production_stream_json_rejects_missing_envelope_fields(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    payload: dict[str, Any],
) -> None:
    _set_release_env(monkeypatch, RELEASE_ENV)
    stream_path = _write_json(tmp_path / "stream-events.json", payload)

    stream_report = production_smoke._build_stream_events_report(
        auth_token=None,
        dry_run=False,
        stream_events_json=stream_path,
        stream_events_url=None,
        timeout_seconds=1,
    )

    assert stream_report["passed"] is False
    assert stream_report["source"]["evidence_validation"]["trusted"] is False
    assert any("missing" in error for error in stream_report["errors"])


@pytest.mark.parametrize("field", tuple(RELEASE_BINDING))
def test_production_stream_json_rejects_release_binding_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
) -> None:
    _set_release_env(monkeypatch, RELEASE_ENV)
    mismatched = dict(RELEASE_BINDING)
    mismatched[field] = "staging" if field == "environment" else f"other-{field}"
    stream_path = _write_json(
        tmp_path / f"stream-events-{field}.json",
        _stream_payload(release_binding=mismatched),
    )

    stream_report = production_smoke._build_stream_events_report(
        auth_token=None,
        dry_run=False,
        stream_events_json=stream_path,
        stream_events_url=None,
        timeout_seconds=1,
    )

    assert stream_report["passed"] is False
    assert stream_report["source"]["evidence_validation"]["trusted"] is False
    assert any(f"mismatch for {field}" in error for error in stream_report["errors"])


def test_production_stream_json_rejects_stale_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _set_release_env(monkeypatch, RELEASE_ENV)
    generated_at = datetime.now(UTC) - timedelta(
        seconds=production_smoke.DEFAULT_MAX_EVIDENCE_AGE_SECONDS + 60
    )
    stream_path = _write_json(
        tmp_path / "stream-events.json",
        _stream_payload(generated_at=generated_at.isoformat()),
    )

    stream_report = production_smoke._build_stream_events_report(
        auth_token=None,
        dry_run=False,
        stream_events_json=stream_path,
        stream_events_url=None,
        timeout_seconds=1,
    )

    assert stream_report["passed"] is False
    assert any("stale" in error for error in stream_report["errors"])


def test_production_stream_json_rejects_naive_timestamp(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _set_release_env(monkeypatch, RELEASE_ENV)
    stream_path = _write_json(
        tmp_path / "stream-events.json",
        _stream_payload(generated_at="2026-07-12T12:00:00"),
    )

    stream_report = production_smoke._build_stream_events_report(
        auth_token=None,
        dry_run=False,
        stream_events_json=stream_path,
        stream_events_url=None,
        timeout_seconds=1,
    )

    assert stream_report["passed"] is False
    assert any("timezone" in error for error in stream_report["errors"])


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(_stream_payload()["events"], id="list"),
        pytest.param({"events": _stream_payload()["events"]}, id="object"),
    ],
)
def test_local_stream_json_keeps_legacy_payload_compatibility(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    payload: Any,
) -> None:
    _set_release_env(monkeypatch, {})
    stream_path = _write_json(tmp_path / "stream-events.json", payload)

    stream_report = production_smoke._build_stream_events_report(
        auth_token=None,
        dry_run=False,
        stream_events_json=stream_path,
        stream_events_url=None,
        timeout_seconds=1,
    )

    validation = stream_report["source"]["evidence_validation"]
    assert stream_report["passed"] is True
    assert validation["identity_configuration"] == "absent"
    assert validation["required"] is False
    assert validation["trusted"] is False


def test_partial_release_identity_never_marks_stream_json_trusted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _set_release_env(monkeypatch, {"RELEASE_COMMIT_SHA": RELEASE_BINDING["commit_sha"]})
    stream_path = _write_json(tmp_path / "stream-events.json", _stream_payload())

    stream_report = production_smoke._build_stream_events_report(
        auth_token=None,
        dry_run=False,
        stream_events_json=stream_path,
        stream_events_url=None,
        timeout_seconds=1,
    )

    validation = stream_report["source"]["evidence_validation"]
    assert stream_report["passed"] is True
    assert validation["identity_configuration"] == "partial"
    assert validation["status"] == "untrusted"
    assert validation["trusted"] is False
    with pytest.raises(ValueError, match="release identity is incomplete"):
        production_smoke.write_report(
            tmp_path / "production-smoke.json",
            {"dry_run": False, "stream_events": stream_report},
        )


def test_current_report_attestation_cannot_wash_mismatched_stream_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _set_release_env(monkeypatch, RELEASE_ENV)
    stream_path = _write_json(
        tmp_path / "stream-events.json",
        _stream_payload(release_binding={**RELEASE_BINDING, "deployment_id": "other-deployment"}),
    )
    monkeypatch.setattr(production_smoke, "_http_check", _passing_http_check)

    report = production_smoke.build_report(
        base_url="https://focus-agent.example.com",
        stream_events_json=stream_path,
    )
    report["release_binding"] = dict(RELEASE_BINDING)
    report_path = production_smoke.write_report(tmp_path / "production-smoke.json", report)
    written = json.loads(report_path.read_text(encoding="utf-8"))

    assert written["release_binding"] == RELEASE_BINDING
    assert written["passed"] is False
    assert written["stream_events"]["passed"] is False
    assert "stream_events" in written["summary"]["v2_failed_checks"]


def test_stream_events_url_is_labeled_as_live_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_release_env(monkeypatch, RELEASE_ENV)
    monkeypatch.setattr(
        production_smoke,
        "_http_stream_events",
        lambda *args, **kwargs: (
            _stream_payload()["events"],
            {"type": "live_url", "url": args[0]},
        ),
    )

    stream_report = production_smoke._build_stream_events_report(
        auth_token=None,
        dry_run=False,
        stream_events_json=None,
        stream_events_url="https://focus-agent.example.com/events",
        timeout_seconds=1,
    )

    assert stream_report["passed"] is True
    assert stream_report["source"]["type"] == "live_url"
