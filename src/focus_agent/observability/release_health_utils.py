"""Small coercion helpers shared by release-health signal evaluators."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def overview(stats: Mapping[str, Any]) -> Mapping[str, Any]:
    stats_overview = stats.get("overview") if isinstance(stats, Mapping) else None
    if isinstance(stats_overview, Mapping):
        return stats_overview
    return stats


def check_by_name(runtime_status: Any, name: str) -> Any | None:
    for check in list(value(runtime_status, "checks", []) or []):
        if str(value(check, "name", "")) == name:
            return check
    return None


def value(source: Any, key: str, default: Any = None) -> Any:
    if isinstance(source, Mapping):
        return source.get(key, default)
    return getattr(source, key, default)


def number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def failed_report_status(status: str) -> bool:
    return status in {"fail", "failed", "error"}


def failed_report_rows(rows: Iterable[Mapping[str, Any]]) -> list[str]:
    failures: list[str] = []
    for index, row in enumerate(rows):
        name = str(row.get("name") or row.get("label") or f"row-{index + 1}")
        status = str(row.get("status") or "").lower()
        explicit_passed = row.get("passed")
        if explicit_passed is False or failed_report_status(status):
            failures.append(name)
    return failures
