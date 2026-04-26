from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts import otel_smoke


class _FakeResponse:
    def __init__(self, *, status: int = 200, body: dict[str, Any] | str | None = None) -> None:
        self.status = status
        self.reason = "OK"
        self.headers = {}
        if isinstance(body, str):
            self._body = body
        else:
            self._body = json.dumps(body or {})

    def read(self) -> bytes:
        return self._body.encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None


def test_otel_smoke_dry_run_writes_report(tmp_path: Path) -> None:
    report_path = tmp_path / "otel-smoke.json"

    exit_code = otel_smoke.main(
        [
            "--dry-run",
            "--endpoint",
            "http://otel-collector:4318",
            "--service-name",
            "focus-agent-prod",
            "--report-json",
            str(report_path),
        ]
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert report["report_type"] == "otel_smoke"
    assert report["status"] == "dry-run"
    assert report["passed"] is True
    assert report["summary"]["spans"] == 1
    assert {check["status"] for check in report["checks"]} == {"dry-run"}


def test_otel_smoke_live_fails_when_endpoint_is_missing(monkeypatch) -> None:
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", raising=False)

    report = otel_smoke.build_report(dry_run=False)

    assert report["status"] == "failed"
    assert "otlp_endpoint" in report["summary"]["failed_checks"]
    assert "trace_query" in report["summary"]["failed_checks"]


def test_otel_smoke_live_fails_when_trace_query_misses_span(monkeypatch) -> None:
    def fake_urlopen(request, timeout: float):
        if request.get_method() == "POST":
            return _FakeResponse(status=202, body={})
        return _FakeResponse(status=200, body={"traces": []})

    monkeypatch.setattr(otel_smoke.urllib_request, "urlopen", fake_urlopen)

    report = otel_smoke.build_report(
        endpoint="http://otel-collector:4318",
        trace_query_url="http://tempo.example.com/api/traces/{trace_id}",
    )

    assert report["status"] == "failed"
    assert report["roundtrip"]["span_export"]["status"] == "passed"
    assert report["roundtrip"]["trace_query"]["status"] == "failed"
    assert "trace_query" in report["summary"]["failed_checks"]


def test_otel_smoke_live_passes_collector_roundtrip_with_mocked_http(monkeypatch) -> None:
    def fake_urlopen(request, timeout: float):
        url = request.full_url
        if request.get_method() == "POST":
            payload = json.loads(request.data.decode("utf-8"))
            span = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
            assert span["name"] == otel_smoke.SYNTHETIC_SPAN_NAME
            return _FakeResponse(status=202, body={})
        if url.endswith("/healthz"):
            return _FakeResponse(status=200, body={"status": "ok"})
        trace_id = url.rsplit("/", 1)[-1]
        return _FakeResponse(
            status=200,
            body={"trace_id": trace_id, "spans": [{"name": otel_smoke.SYNTHETIC_SPAN_NAME}]},
        )

    monkeypatch.setattr(otel_smoke.urllib_request, "urlopen", fake_urlopen)

    report = otel_smoke.build_report(
        collector_health_url="http://otel-collector:13133/healthz",
        endpoint="http://otel-collector:4318",
        trace_query_url="http://tempo.example.com/api/traces/{trace_id}",
    )

    assert report["status"] == "passed"
    assert report["passed"] is True
    assert report["roundtrip"]["collector_health"]["status"] == "passed"
    assert report["roundtrip"]["span_export"]["status"] == "passed"
    assert report["roundtrip"]["trace_query"]["status"] == "passed"
