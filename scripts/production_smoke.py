#!/usr/bin/env python3
"""Write a production smoke report for release review."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Sequence
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
    ("graph_min_conversation", "graph", "api", "POST", "/v1/conversations", (200, 201, 401, 403), {"title": "Production smoke"}),
    (
        "graph_min_chat_turn",
        "graph",
        "api",
        "POST",
        "/v1/chat/turns",
        (200, 401, 403, 422, 429),
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
        (200, 401, 403, 422, 429),
        {"thread_id": "production-smoke", "message": "rate-limit smoke"},
    ),
)
PASS_STATUSES = {"pass", "passed", "success", "succeeded", "ok", "dry-run"}


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _resolve_path(path: str | Path) -> Path:
    return Path(path)


def _join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _check_passed(check: dict[str, Any]) -> bool:
    status = str(check.get("status") or "").lower()
    return bool(check.get("passed", status in PASS_STATUSES))


def _headers_for_check(name: str, *, auth_token: str | None) -> dict[str, str]:
    if name == "security_wrong_jwt_denied":
        return {"Authorization": "Bearer invalid.production-smoke.jwt"}
    if auth_token:
        return {"Authorization": f"Bearer {auth_token}"}
    return {}


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
                "detail": response.reason,
            }
    except urllib_error.HTTPError as exc:
        status_code = int(exc.code)
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
            "detail": str(exc.reason),
        }
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
        }


def build_report(
    *,
    auth_token: str | None = None,
    base_url: str = DEFAULT_BASE_URL,
    dry_run: bool = False,
    timeout_seconds: float = 10.0,
    web_base_url: str | None = None,
) -> dict[str, Any]:
    checks = []
    resolved_web_base_url = web_base_url or base_url
    for name, category, base_kind, method, path, expected_statuses, body in DEFAULT_CHECKS:
        probe_base_url = resolved_web_base_url if base_kind == "web" else base_url
        url = _join_url(probe_base_url, path)
        check = (
            _dry_run_check(name, url, category=category, method=method, expected_statuses=expected_statuses)
            if dry_run
            else _http_check(
                name,
                url,
                auth_token=auth_token,
                body=body,
                category=category,
                method=method,
                expected_statuses=expected_statuses,
                timeout_seconds=timeout_seconds,
            )
        )
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
    status = "dry-run" if dry_run else ("passed" if not failed else "failed")
    return {
        "generated_at": _now(),
        "report_type": "production_smoke",
        "status": status,
        "passed": not failed,
        "dry_run": dry_run,
        "base_url": base_url,
        "web_base_url": resolved_web_base_url,
        "summary": {
            "total": len(checks),
            "passed": len(checks) - len(failed),
            "failed": len(failed),
            "failed_checks": failed,
            "by_category": by_category,
        },
        "checks": checks,
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
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(
        auth_token=args.auth_token,
        base_url=args.base_url,
        dry_run=bool(args.dry_run),
        timeout_seconds=float(args.timeout_seconds),
        web_base_url=args.web_base_url,
    )
    report_path = write_report(args.report_json, report)
    print(json.dumps({"status": report["status"], "report_json": str(report_path)}, indent=2))
    return 0 if bool(report["passed"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
