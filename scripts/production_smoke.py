#!/usr/bin/env python3
"""Write a production smoke report for release review."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib import error as urllib_error
from urllib import request as urllib_request


DEFAULT_REPORT_JSON = Path("reports/release-gate/production-smoke.json")
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_CHECKS: tuple[tuple[str, str, str, str, str, tuple[int, ...], dict[str, Any] | None], ...] = (
    ("api_healthz", "api", "api", "GET", "/healthz", (200,), None),
    ("api_readyz", "api", "api", "GET", "/readyz", (200,), None),
    ("api_models", "api", "api", "GET", "/v1/models", (200, 401, 403), None),
    ("api_trajectory_stats", "api", "api", "GET", "/v1/observability/trajectory/stats", (200, 401, 403), None),
    ("sdk_client_healthz", "sdk", "api", "GET", "/healthz", (200,), None),
    ("web_app", "web", "web", "GET", "/app", (200,), None),
    ("web_observability", "web", "web", "GET", "/app/observability/overview", (200,), None),
    ("web_agent_governance", "web", "web", "GET", "/app/agent/governance", (200,), None),
    ("graph_min_conversation", "graph", "api", "POST", "/v1/conversations", (200, 201), {"title": "Production smoke"}),
    (
        "graph_min_chat_turn",
        "graph",
        "api",
        "POST",
        "/v1/chat/turns",
        (200, 201),
        {"thread_id": "production-smoke", "message": "production smoke"},
    ),
    ("security_auth_required", "security", "api", "GET", "/v1/auth/me", (401, 403), None),
    ("security_wrong_jwt_denied", "security", "api", "GET", "/v1/auth/me", (401, 403), None),
    (
        "rate_limit_probe",
        "rate-limit",
        "api",
        "POST",
        "/v1/chat/turns",
        (200, 201, 429),
        {"thread_id": "production-smoke", "message": "rate-limit smoke"},
    ),
)
GRAPH_TURN_CHECKS = ("graph_min_conversation", "graph_min_chat_turn")
KNOWN_STREAM_EVENT_NAMES = {
    "agent.update",
    "custom",
    "message.completed",
    "message.delta",
    "reasoning.completed",
    "reasoning.delta",
    "status",
    "stream.chunk",
    "task.failed",
    "task.finished",
    "task.started",
    "task.update",
    "tool.call.delta",
    "tool.delta",
    "tool.end",
    "tool.error",
    "tool.requested",
    "tool.result",
    "tool.start",
    "tool_call.delta",
    "turn.closed",
    "turn.completed",
    "turn.failed",
    "turn.interrupt",
    "turn.status",
    "visible_text.completed",
    "visible_text.delta",
}
REQUIRED_STREAM_TERMINAL_EVENT = "turn.completed"
FAILED_STREAM_TERMINAL_EVENTS = {"turn.failed", "task.failed"}
PASS_STATUSES = {"pass", "passed", "success", "succeeded", "ok", "dry-run"}


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _resolve_path(path: str | Path) -> Path:
    return Path(path)


def _join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _check_passed(check: Mapping[str, Any]) -> bool:
    status = str(check.get("status") or "").lower()
    return bool(check.get("passed", status in PASS_STATUSES))


def _headers_for_check(name: str, *, auth_token: str | None) -> dict[str, str]:
    if name == "security_wrong_jwt_denied":
        return {"Authorization": "Bearer invalid.production-smoke.jwt"}
    if auth_token:
        return {"Authorization": f"Bearer {auth_token}"}
    return {}


def _safe_headers(headers: Any) -> dict[str, str]:
    if headers is None:
        return {}
    try:
        items = headers.items()
    except AttributeError:
        return {}
    return {str(key): str(value) for key, value in items}


def _read_response_body(response: Any) -> str:
    try:
        return response.read(64 * 1024).decode("utf-8", errors="replace")
    except (AttributeError, OSError, UnicodeDecodeError):
        return ""


def _json_body(body: str) -> Any | None:
    if not body.strip():
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return None


def _extract_thread_id(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get("root_thread_id") or payload.get("thread_id")
    text = str(value or "").strip()
    return text or None


def _dry_run_check(
    name: str,
    url: str,
    *,
    category: str,
    method: str,
    expected_statuses: Sequence[int],
) -> dict[str, Any]:
    return {
        "category": category,
        "expected_statuses": list(expected_statuses),
        "name": name,
        "url": url,
        "method": method,
        "status": "dry-run",
        "passed": True,
        "detail": "planned production smoke probe",
    }


def _http_check(
    name: str,
    url: str,
    *,
    auth_token: str | None,
    body: dict[str, Any] | None,
    category: str,
    method: str,
    expected_statuses: Sequence[int],
    timeout_seconds: float,
) -> dict[str, Any]:
    headers = _headers_for_check(name, auth_token=auth_token)
    data = None
    if body is not None:
        headers = {**headers, "Content-Type": "application/json"}
        data = json.dumps(body).encode("utf-8")
    request = urllib_request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib_request.urlopen(request, timeout=timeout_seconds) as response:
            status_code = int(response.status)
            body_text = _read_response_body(response)
            response_json = _json_body(body_text)
            passed = status_code in expected_statuses
            result = {
                "category": category,
                "expected_statuses": list(expected_statuses),
                "name": name,
                "url": url,
                "method": method,
                "status": "passed" if passed else "failed",
                "passed": passed,
                "status_code": status_code,
                "detail": str(getattr(response, "reason", "")),
                "response_headers": _safe_headers(getattr(response, "headers", None)),
            }
            if response_json is not None:
                result["response_json"] = response_json
            return result
    except urllib_error.HTTPError as exc:
        status_code = int(exc.code)
        body_text = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else ""
        response_json = _json_body(body_text)
        passed = status_code in expected_statuses
        result = {
            "category": category,
            "expected_statuses": list(expected_statuses),
            "name": name,
            "url": url,
            "method": method,
            "status": "passed" if passed else "failed",
            "passed": passed,
            "status_code": status_code,
            "detail": str(exc.reason),
            "response_headers": _safe_headers(getattr(exc, "headers", None)),
        }
        if response_json is not None:
            result["response_json"] = response_json
        return result
    except (OSError, TimeoutError, urllib_error.URLError) as exc:
        return {
            "category": category,
            "expected_statuses": list(expected_statuses),
            "name": name,
            "url": url,
            "method": method,
            "status": "failed",
            "passed": False,
            "detail": str(exc),
            "response_headers": {},
        }


def _http_stream_events(
    url: str,
    *,
    auth_token: str | None,
    timeout_seconds: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    headers = {"Accept": "text/event-stream", **_headers_for_check("stream_events", auth_token=auth_token)}
    request = urllib_request.Request(url, headers=headers, method="GET")
    with urllib_request.urlopen(request, timeout=timeout_seconds) as response:
        raw = _read_sse_sample(response)
        source = {
            "type": "url",
            "url": url,
            "status_code": int(getattr(response, "status", 0) or 0),
            "response_headers": _safe_headers(getattr(response, "headers", None)),
        }
        return _parse_sse_events(raw), source


def _read_sse_sample(response: Any) -> str:
    if not hasattr(response, "readline"):
        return response.read(256 * 1024).decode("utf-8", errors="replace")

    lines: list[str] = []
    for _index in range(1000):
        line_bytes = response.readline()
        if not line_bytes:
            break
        line = line_bytes.decode("utf-8", errors="replace")
        lines.append(line)
        if line in {"\n", "\r\n"}:
            events = _parse_sse_events("".join(lines))
            if any(event.get("event") in {REQUIRED_STREAM_TERMINAL_EVENT, *FAILED_STREAM_TERMINAL_EVENTS} for event in events):
                break
        if sum(len(line) for line in lines) >= 256 * 1024:
            break
    return "".join(lines)


def _parse_sse_events(raw: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    event_name = "message"
    data_lines: list[str] = []
    for line in raw.splitlines():
        if not line:
            if data_lines:
                events.append(_event_from_sse_frame(event_name, data_lines))
            event_name = "message"
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line.removeprefix("event:").strip()
            continue
        if line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").lstrip())
    if data_lines:
        events.append(_event_from_sse_frame(event_name, data_lines))
    return events


def _event_from_sse_frame(event_name: str, data_lines: Sequence[str]) -> dict[str, Any]:
    raw_data = "\n".join(data_lines)
    try:
        payload = json.loads(raw_data)
    except json.JSONDecodeError:
        payload = raw_data
    return {"event": event_name, "data": payload, "raw": raw_data}


def _events_from_json_payload(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    if "event" in payload:
        return [payload]
    stream_events = payload.get("stream_events")
    if isinstance(stream_events, dict) and isinstance(stream_events.get("events"), list):
        return list(stream_events["events"])
    if isinstance(stream_events, list):
        return list(stream_events)
    events = payload.get("events")
    if isinstance(events, list):
        return list(events)
    return []


def _normalize_stream_event(item: Any, *, index: int) -> tuple[dict[str, Any] | None, str | None]:
    if isinstance(item, str):
        return {"event": item, "data": {}}, None
    if not isinstance(item, dict):
        return None, f"event[{index}] must be an object or event name string"
    event_name = str(item.get("event") or item.get("name") or "").strip()
    if not event_name:
        return None, f"event[{index}] is missing event"
    data = item.get("data", {})
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return None, f"event[{index}] data must be an object"
    return {"event": event_name, "data": data}, None


def _validate_stream_events(
    events: Sequence[Any],
    *,
    source: dict[str, Any],
) -> dict[str, Any]:
    normalized_events: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, item in enumerate(events):
        event, error = _normalize_stream_event(item, index=index)
        if error:
            errors.append(error)
            continue
        if event is not None:
            normalized_events.append(event)

    events_seen = [event["event"] for event in normalized_events]
    unique_events = sorted(set(events_seen))
    unknown_events = sorted({event_name for event_name in events_seen if event_name not in KNOWN_STREAM_EVENT_NAMES})
    if unknown_events:
        errors.append(f"unknown stream events: {', '.join(unknown_events)}")
    if not normalized_events:
        errors.append("stream event report contains no events")
    if REQUIRED_STREAM_TERMINAL_EVENT not in events_seen:
        errors.append(f"missing required stream event: {REQUIRED_STREAM_TERMINAL_EVENT}")
    failed_terminals = sorted(FAILED_STREAM_TERMINAL_EVENTS.intersection(events_seen))
    if failed_terminals:
        errors.append(f"stream reported failure events: {', '.join(failed_terminals)}")

    passed = not errors
    return {
        "status": "passed" if passed else "failed",
        "passed": passed,
        "source": source,
        "required_events": [REQUIRED_STREAM_TERMINAL_EVENT],
        "known_event_count": len(KNOWN_STREAM_EVENT_NAMES),
        "event_count": len(normalized_events),
        "events_seen": unique_events,
        "errors": errors,
        "events": normalized_events[:25],
        "detail": "stream event contract validated" if passed else "stream event contract validation failed",
    }


def _build_stream_events_report(
    *,
    auth_token: str | None,
    dry_run: bool,
    stream_events_json: str | Path | None,
    stream_events_url: str | None,
    timeout_seconds: float,
) -> dict[str, Any]:
    if dry_run:
        return {
            "status": "dry-run",
            "passed": True,
            "source": {
                "type": "planned",
                "json": str(stream_events_json) if stream_events_json else None,
                "url": stream_events_url,
            },
            "required_events": [REQUIRED_STREAM_TERMINAL_EVENT],
            "event_count": 0,
            "events_seen": [],
            "errors": [],
            "detail": "planned stream event contract validation",
        }
    if stream_events_json:
        path = _resolve_path(stream_events_json)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {
                "status": "failed",
                "passed": False,
                "source": {"type": "file", "path": str(path)},
                "required_events": [REQUIRED_STREAM_TERMINAL_EVENT],
                "event_count": 0,
                "events_seen": [],
                "errors": [str(exc)],
                "detail": "failed to load stream event report",
            }
        return _validate_stream_events(_events_from_json_payload(payload), source={"type": "file", "path": str(path)})
    if stream_events_url:
        try:
            events, source = _http_stream_events(
                stream_events_url,
                auth_token=auth_token,
                timeout_seconds=timeout_seconds,
            )
        except (OSError, TimeoutError, urllib_error.URLError, urllib_error.HTTPError) as exc:
            return {
                "status": "failed",
                "passed": False,
                "source": {"type": "url", "url": stream_events_url},
                "required_events": [REQUIRED_STREAM_TERMINAL_EVENT],
                "event_count": 0,
                "events_seen": [],
                "errors": [str(exc)],
                "detail": "failed to load stream event URL",
            }
        return _validate_stream_events(events, source=source)
    return {
        "status": "failed",
        "passed": False,
        "source": {"type": "none"},
        "required_events": [REQUIRED_STREAM_TERMINAL_EVENT],
        "event_count": 0,
        "events_seen": [],
        "errors": ["stream event validation input is required in live mode"],
        "detail": "stream event validation input is required in live mode",
    }


def _build_graph_turn_report(*, checks: Sequence[Mapping[str, Any]], dry_run: bool) -> dict[str, Any]:
    graph_checks = [check for check in checks if check.get("name") in GRAPH_TURN_CHECKS]
    if dry_run:
        return {
            "status": "dry-run",
            "passed": True,
            "checks": [dict(check) for check in graph_checks],
            "required_checks": list(GRAPH_TURN_CHECKS),
            "detail": "planned graph conversation and turn probes",
        }
    missing = [name for name in GRAPH_TURN_CHECKS if not any(check.get("name") == name for check in graph_checks)]
    failed = [str(check.get("name")) for check in graph_checks if not _check_passed(check)]
    errors = [f"missing graph check: {name}" for name in missing]
    passed = not failed and not errors
    return {
        "status": "passed" if passed else "failed",
        "passed": passed,
        "checks": [dict(check) for check in graph_checks],
        "required_checks": list(GRAPH_TURN_CHECKS),
        "failed_checks": failed,
        "errors": errors,
        "detail": "graph turn probes passed" if passed else "graph turn probes failed",
    }


def _header_value(headers: Mapping[str, Any], name: str) -> str | None:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return str(value)
    return None


def _optional_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _build_threshold_report(
    *,
    checks: Sequence[Mapping[str, Any]],
    dry_run: bool,
    rate_limit_min_limit: int,
) -> dict[str, Any]:
    if dry_run:
        return {
            "status": "dry-run",
            "passed": True,
            "rate_limit": {
                "status": "dry-run",
                "passed": True,
                "probe_name": "rate_limit_probe",
                "min_limit": rate_limit_min_limit,
                "detail": "planned single-request rate-limit header threshold check",
            },
        }

    rate_check = next((check for check in checks if check.get("name") == "rate_limit_probe"), None)
    if rate_check is None:
        rate_limit = {
            "status": "failed",
            "passed": False,
            "probe_name": "rate_limit_probe",
            "min_limit": rate_limit_min_limit,
            "errors": ["missing rate_limit_probe check"],
        }
    else:
        headers = rate_check.get("response_headers") if isinstance(rate_check.get("response_headers"), dict) else {}
        limit = _optional_int(_header_value(headers, "X-RateLimit-Limit"))
        remaining = _optional_int(_header_value(headers, "X-RateLimit-Remaining"))
        retry_after = _header_value(headers, "Retry-After")
        errors: list[str] = []
        if not _check_passed(rate_check):
            errors.append("rate_limit_probe failed")
        if limit is None:
            errors.append("missing X-RateLimit-Limit header")
        elif limit < rate_limit_min_limit:
            errors.append(f"X-RateLimit-Limit {limit} is below minimum {rate_limit_min_limit}")
        if int(rate_check.get("status_code") or 0) == 429 and not retry_after:
            errors.append("429 response is missing Retry-After header")
        rate_limit_passed = not errors
        rate_limit = {
            "status": "passed" if rate_limit_passed else "failed",
            "passed": rate_limit_passed,
            "probe_name": "rate_limit_probe",
            "status_code": rate_check.get("status_code"),
            "headers": {
                "X-RateLimit-Limit": _header_value(headers, "X-RateLimit-Limit"),
                "X-RateLimit-Remaining": _header_value(headers, "X-RateLimit-Remaining"),
                "Retry-After": retry_after,
            },
            "observed": {
                "limit": limit,
                "remaining": remaining,
                "retry_after": retry_after,
            },
            "min_limit": rate_limit_min_limit,
            "errors": errors,
            "detail": "rate-limit headers satisfied thresholds" if rate_limit_passed else "rate-limit threshold check failed",
        }

    return {
        "status": "passed" if bool(rate_limit["passed"]) else "failed",
        "passed": bool(rate_limit["passed"]),
        "rate_limit": rate_limit,
    }


def build_report(
    *,
    auth_token: str | None = None,
    base_url: str = DEFAULT_BASE_URL,
    dry_run: bool = False,
    rate_limit_min_limit: int = 1,
    stream_events_json: str | Path | None = None,
    stream_events_url: str | None = None,
    timeout_seconds: float = 10.0,
    web_base_url: str | None = None,
) -> dict[str, Any]:
    checks = []
    resolved_web_base_url = web_base_url or base_url
    created_thread_id: str | None = None
    for name, category, base_kind, method, path, expected_statuses, body in DEFAULT_CHECKS:
        probe_base_url = resolved_web_base_url if base_kind == "web" else base_url
        url = _join_url(probe_base_url, path)
        probe_body = body
        if created_thread_id and name in {"graph_min_chat_turn", "rate_limit_probe"} and body is not None:
            probe_body = {**body, "thread_id": created_thread_id}
        check = (
            _dry_run_check(name, url, category=category, method=method, expected_statuses=expected_statuses)
            if dry_run
            else _http_check(
                name,
                url,
                auth_token=auth_token,
                body=probe_body,
                category=category,
                method=method,
                expected_statuses=expected_statuses,
                timeout_seconds=timeout_seconds,
            )
        )
        if name == "graph_min_conversation" and _check_passed(check):
            created_thread_id = _extract_thread_id(check.get("response_json"))
        checks.append(check)

    failed = [check["name"] for check in checks if not _check_passed(check)]
    by_category: dict[str, dict[str, int]] = {}
    for check in checks:
        category = str(check["category"])
        bucket = by_category.setdefault(category, {"total": 0, "passed": 0, "failed": 0})
        bucket["total"] += 1
        if _check_passed(check):
            bucket["passed"] += 1
        else:
            bucket["failed"] += 1

    stream_events = _build_stream_events_report(
        auth_token=auth_token,
        dry_run=dry_run,
        stream_events_json=stream_events_json,
        stream_events_url=stream_events_url,
        timeout_seconds=timeout_seconds,
    )
    graph_turn = _build_graph_turn_report(checks=checks, dry_run=dry_run)
    thresholds = _build_threshold_report(
        checks=checks,
        dry_run=dry_run,
        rate_limit_min_limit=rate_limit_min_limit,
    )
    v2_sections = {
        "stream_events": stream_events,
        "graph_turn": graph_turn,
        "thresholds": thresholds,
    }
    v2_failed = [name for name, section in v2_sections.items() if not _check_passed(section)]
    passed = not failed and not v2_failed
    status = "dry-run" if dry_run else ("passed" if passed else "failed")
    return {
        "generated_at": _now(),
        "report_type": "production_smoke",
        "report_version": 2,
        "status": status,
        "passed": passed,
        "dry_run": dry_run,
        "base_url": base_url,
        "web_base_url": resolved_web_base_url,
        "summary": {
            "total": len(checks),
            "passed": len(checks) - len(failed),
            "failed": len(failed),
            "failed_checks": failed,
            "by_category": by_category,
            "v2_failed_checks": v2_failed,
        },
        "checks": checks,
        "stream_events": stream_events,
        "graph_turn": graph_turn,
        "thresholds": thresholds,
    }


def write_report(path: str | Path, report: dict[str, Any]) -> Path:
    target = _resolve_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Plan probes without calling the service.")
    parser.add_argument("--auth-token", help="Bearer token used for authenticated positive probes.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Production API base URL.")
    parser.add_argument("--web-base-url", help="Production web base URL. Defaults to --base-url.")
    parser.add_argument("--timeout-seconds", type=float, default=10.0, help="Per-probe timeout.")
    parser.add_argument("--report-json", default=str(DEFAULT_REPORT_JSON), help="Structured report path.")
    parser.add_argument(
        "--stream-events-json",
        help="JSON stream event report to validate in live mode.",
    )
    parser.add_argument(
        "--stream-events-url",
        help="Minimal SSE URL to validate in live mode. The smoke performs one GET with Accept: text/event-stream.",
    )
    parser.add_argument(
        "--rate-limit-min-limit",
        type=int,
        default=1,
        help="Minimum accepted X-RateLimit-Limit value for the single rate-limit probe.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(
        auth_token=args.auth_token,
        base_url=args.base_url,
        dry_run=bool(args.dry_run),
        rate_limit_min_limit=int(args.rate_limit_min_limit),
        stream_events_json=args.stream_events_json,
        stream_events_url=args.stream_events_url,
        timeout_seconds=float(args.timeout_seconds),
        web_base_url=args.web_base_url,
    )
    report_path = write_report(args.report_json, report)
    print(json.dumps({"status": report["status"], "report_json": str(report_path)}, indent=2))
    return 0 if bool(report["passed"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
