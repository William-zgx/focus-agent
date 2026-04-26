#!/usr/bin/env python3
"""Write an OpenTelemetry smoke report for release review."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request
from uuid import uuid4


DEFAULT_REPORT_JSON = Path("reports/release-gate/otel-smoke.json")
DEFAULT_SERVICE_NAME = "focus-agent"
SYNTHETIC_SPAN_NAME = "focus_agent.release.otel_smoke"
PASS_STATUSES = {"pass", "passed", "success", "succeeded", "ok", "dry-run", "skipped"}


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _check_passed(check: Mapping[str, Any]) -> bool:
    status = str(check.get("status") or "").lower()
    return bool(check.get("passed", status in PASS_STATUSES))


def _check(name: str, *, status: str, detail: str, passed: bool | None = None, **extra: Any) -> dict[str, Any]:
    payload = {
        "name": name,
        "status": status,
        "passed": status in PASS_STATUSES if passed is None else passed,
        "detail": detail,
    }
    payload.update(extra)
    return payload


def _safe_headers(headers: Any) -> dict[str, str]:
    if headers is None:
        return {}
    try:
        items = headers.items()
    except AttributeError:
        return {}
    return {str(key): str(value) for key, value in items}


def _resolve_endpoint(endpoint: str | None) -> str | None:
    return (
        endpoint
        or os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
        or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    )


def _resolve_traces_endpoint(endpoint: str) -> str:
    parsed = urllib_parse.urlparse(endpoint)
    if parsed.path.rstrip("/").endswith("/v1/traces"):
        return endpoint
    path = parsed.path.rstrip("/")
    traces_path = f"{path}/v1/traces" if path else "/v1/traces"
    return urllib_parse.urlunparse(parsed._replace(path=traces_path))


def _http_request(
    url: str,
    *,
    data: bytes | None = None,
    headers: Mapping[str, str] | None = None,
    method: str = "GET",
    timeout_seconds: float,
) -> dict[str, Any]:
    request = urllib_request.Request(url, data=data, headers=dict(headers or {}), method=method)
    try:
        with urllib_request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8", errors="replace")
            return {
                "ok": True,
                "status_code": int(response.status),
                "reason": str(getattr(response, "reason", "")),
                "headers": _safe_headers(getattr(response, "headers", None)),
                "body": body,
            }
    except urllib_error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else ""
        return {
            "ok": False,
            "status_code": int(exc.code),
            "reason": str(exc.reason),
            "headers": _safe_headers(getattr(exc, "headers", None)),
            "body": body,
        }
    except (OSError, TimeoutError, urllib_error.URLError) as exc:
        return {
            "ok": False,
            "status_code": None,
            "reason": str(exc),
            "headers": {},
            "body": "",
        }


def _synthetic_otlp_payload(*, service_name: str, trace_id: str, span_id: str) -> dict[str, Any]:
    start_time = int(datetime.now(UTC).timestamp() * 1_000_000_000)
    end_time = start_time + 1_000_000
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": service_name}},
                        {"key": "focus_agent.smoke", "value": {"boolValue": True}},
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "focus-agent-release-smoke"},
                        "spans": [
                            {
                                "traceId": trace_id,
                                "spanId": span_id,
                                "name": SYNTHETIC_SPAN_NAME,
                                "kind": "SPAN_KIND_INTERNAL",
                                "startTimeUnixNano": str(start_time),
                                "endTimeUnixNano": str(end_time),
                                "attributes": [
                                    {
                                        "key": "release.smoke",
                                        "value": {"stringValue": "otel_roundtrip"},
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }


def _export_synthetic_span(
    *,
    endpoint: str | None,
    service_name: str,
    timeout_seconds: float,
    trace_id: str,
    span_id: str,
) -> dict[str, Any]:
    if not endpoint:
        return _check(
            "span_export",
            status="failed",
            passed=False,
            detail="OTEL_EXPORTER_OTLP_ENDPOINT is not configured",
            trace_id=trace_id,
            span_id=span_id,
        )
    traces_endpoint = _resolve_traces_endpoint(endpoint)
    payload = _synthetic_otlp_payload(service_name=service_name, trace_id=trace_id, span_id=span_id)
    response = _http_request(
        traces_endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
        timeout_seconds=timeout_seconds,
    )
    passed = response["status_code"] in {200, 202, 204}
    return _check(
        "span_export",
        status="passed" if passed else "failed",
        passed=passed,
        detail="synthetic span export accepted" if passed else "synthetic span export failed",
        endpoint=traces_endpoint,
        trace_id=trace_id,
        span_id=span_id,
        evidence=response,
    )


def _collector_health_check(
    *,
    collector_health_url: str | None,
    timeout_seconds: float,
) -> dict[str, Any]:
    if not collector_health_url:
        return _check(
            "collector_health",
            status="skipped",
            passed=True,
            detail="collector health URL was not provided",
        )
    response = _http_request(collector_health_url, timeout_seconds=timeout_seconds)
    passed = response["status_code"] == 200
    return _check(
        "collector_health",
        status="passed" if passed else "failed",
        passed=passed,
        detail="collector health endpoint passed" if passed else "collector health endpoint failed",
        url=collector_health_url,
        evidence=response,
    )


def _trace_query_url(url: str, *, trace_id: str) -> str:
    if "{trace_id}" in url:
        return url.replace("{trace_id}", trace_id)
    parsed = urllib_parse.urlparse(url)
    query = urllib_parse.parse_qsl(parsed.query, keep_blank_values=True)
    if not any(key == "trace_id" for key, _value in query):
        query.append(("trace_id", trace_id))
    return urllib_parse.urlunparse(parsed._replace(query=urllib_parse.urlencode(query)))


def _payload_contains(value: Any, needle: str) -> bool:
    if isinstance(value, str):
        return needle in value
    if isinstance(value, Mapping):
        return any(_payload_contains(item, needle) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return any(_payload_contains(item, needle) for item in value)
    return False


def _trace_query_check(
    *,
    timeout_seconds: float,
    trace_id: str,
    trace_query_url: str | None,
) -> dict[str, Any]:
    if not trace_query_url:
        return _check(
            "trace_query",
            status="failed",
            passed=False,
            detail="--trace-query-url is required in live OTel smoke mode",
            trace_id=trace_id,
        )
    resolved_url = _trace_query_url(trace_query_url, trace_id=trace_id)
    response = _http_request(resolved_url, timeout_seconds=timeout_seconds)
    body = response.get("body") or ""
    try:
        parsed_body: Any = json.loads(body)
    except json.JSONDecodeError:
        parsed_body = body
    found = _payload_contains(parsed_body, trace_id) or _payload_contains(parsed_body, SYNTHETIC_SPAN_NAME)
    passed = response["status_code"] == 200 and found
    return _check(
        "trace_query",
        status="passed" if passed else "failed",
        passed=passed,
        detail="synthetic trace was found" if passed else "synthetic trace was not found",
        url=resolved_url,
        trace_id=trace_id,
        evidence=response,
    )


def build_report(
    *,
    collector_health_url: str | None = None,
    endpoint: str | None = None,
    service_name: str = DEFAULT_SERVICE_NAME,
    dry_run: bool = False,
    timeout_seconds: float = 10.0,
    trace_query_url: str | None = None,
) -> dict[str, Any]:
    resolved_endpoint = _resolve_endpoint(endpoint)
    trace_id = uuid4().hex
    span_id = uuid4().hex[:16]
    if dry_run:
        checks = [
            _check("service_name", status="dry-run", detail=f"planned service.name={service_name}"),
            _check(
                "otlp_endpoint",
                status="dry-run",
                detail=f"planned OTLP endpoint={resolved_endpoint or '<from deployment env>'}",
            ),
            _check(
                "collector_health",
                status="dry-run",
                detail=f"planned collector health check={collector_health_url or '<optional>'}",
            ),
            _check("span_export", status="dry-run", detail="planned synthetic span export"),
            _check(
                "trace_query",
                status="dry-run",
                detail=f"planned trace query check={trace_query_url or '<deployment query URL>'}",
            ),
        ]
        spans = [{"name": SYNTHETIC_SPAN_NAME, "status": "dry-run", "trace_id": trace_id, "span_id": span_id}]
        roundtrip = {
            "trace_id": trace_id,
            "span_id": span_id,
            "span_export": checks[3],
            "collector_health": checks[2],
            "trace_query": checks[4],
        }
    else:
        endpoint_check = _check(
            "otlp_endpoint",
            status="passed" if resolved_endpoint else "failed",
            passed=bool(resolved_endpoint),
            detail=resolved_endpoint or "OTEL_EXPORTER_OTLP_ENDPOINT is not configured",
        )
        collector_health = _collector_health_check(
            collector_health_url=collector_health_url,
            timeout_seconds=timeout_seconds,
        )
        span_export = _export_synthetic_span(
            endpoint=resolved_endpoint,
            service_name=service_name,
            timeout_seconds=timeout_seconds,
            trace_id=trace_id,
            span_id=span_id,
        )
        trace_query = _trace_query_check(
            timeout_seconds=timeout_seconds,
            trace_id=trace_id,
            trace_query_url=trace_query_url,
        )
        checks = [
            _check("service_name", status="passed", detail=f"service.name={service_name}"),
            endpoint_check,
            collector_health,
            span_export,
            trace_query,
        ]
        spans = [
            {
                "name": SYNTHETIC_SPAN_NAME,
                "status": "passed" if _check_passed(span_export) else "failed",
                "trace_id": trace_id,
                "span_id": span_id,
            }
        ]
        roundtrip = {
            "trace_id": trace_id,
            "span_id": span_id,
            "span_export": span_export,
            "collector_health": collector_health,
            "trace_query": trace_query,
        }

    failed = [check["name"] for check in checks if not _check_passed(check)]
    status = "dry-run" if dry_run else ("passed" if not failed else "failed")
    return {
        "generated_at": _now(),
        "report_type": "otel_smoke",
        "report_version": 2,
        "status": status,
        "passed": not failed,
        "dry_run": dry_run,
        "service_name": service_name,
        "endpoint": resolved_endpoint,
        "collector_health_url": collector_health_url,
        "trace_query_url": trace_query_url,
        "summary": {
            "total": len(checks),
            "passed": len(checks) - len(failed),
            "failed": len(failed),
            "failed_checks": failed,
            "spans": len(spans),
        },
        "checks": checks,
        "spans": spans,
        "roundtrip": roundtrip,
    }


def write_report(path: str | Path, report: dict[str, Any]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Plan OTel checks without exporting a span.")
    parser.add_argument("--endpoint", help="OTLP endpoint. Defaults to OTEL_EXPORTER_OTLP_ENDPOINT.")
    parser.add_argument("--service-name", default=DEFAULT_SERVICE_NAME, help="OTel service.name value.")
    parser.add_argument("--report-json", default=str(DEFAULT_REPORT_JSON), help="Structured report path.")
    parser.add_argument("--collector-health-url", help="Collector health endpoint URL, for example :13133/healthz.")
    parser.add_argument(
        "--trace-query-url",
        help="Trace backend query URL. Use {trace_id} as a placeholder, or the smoke appends trace_id=.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=10.0, help="Per-HTTP-call timeout.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(
        collector_health_url=args.collector_health_url,
        endpoint=args.endpoint,
        service_name=args.service_name,
        dry_run=bool(args.dry_run),
        timeout_seconds=float(args.timeout_seconds),
        trace_query_url=args.trace_query_url,
    )
    report_path = write_report(args.report_json, report)
    print(json.dumps({"status": report["status"], "report_json": str(report_path)}, indent=2))
    return 0 if bool(report["passed"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
