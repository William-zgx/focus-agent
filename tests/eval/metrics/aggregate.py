"""Aggregate per-case EvalResults into suite-level metrics.

Metrics:
- task_success: % of cases passing all required judges.
- avg_tool_calls / avg_llm_calls / avg_input_tokens / avg_output_tokens
- p50_latency_ms / p95_latency_ms
- avg_cost_usd (when token cost table provided)
- forbidden_tool_violation_rate
- per-tag breakdown of task_success
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from statistics import mean
from typing import Any, Iterable

from ..schema import EvalResult


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, int(round(pct / 100.0 * (len(ordered) - 1)))))
    return ordered[k]


def _result_metrics(result: EvalResult) -> dict[str, Any]:
    metrics = getattr(result, "metrics", None) or {}
    return metrics if isinstance(metrics, dict) else {}


def _metric_number(metrics: dict[str, Any], key: str) -> float:
    value = metrics.get(key, 0.0)
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _metric_values(metrics: dict[str, Any], key: str) -> list[str]:
    value = metrics.get(key)
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple, set)):
        values: list[str] = []
        for item in value:
            if item not in (None, ""):
                values.append(str(item))
        return values
    return [str(value)]


def _first_metric_value(metrics: dict[str, Any], key: str) -> str:
    values = _metric_values(metrics, key)
    return values[0] if values else ""


def _success_breakdown(
    results: Iterable[EvalResult],
    metric_key: str,
) -> dict[str, float]:
    buckets: dict[str, list[bool]] = defaultdict(list)
    for result in results:
        metrics = _result_metrics(result)
        for value in _metric_values(metrics, metric_key):
            buckets[value].append(bool(getattr(result, "passed", False)))
    return {
        key: sum(1 for passed in passes if passed) / len(passes)
        for key, passes in sorted(buckets.items())
        if passes
    }


def _metric_mean(results: Iterable[EvalResult], key: str) -> float:
    return mean(_metric_number(_result_metrics(result), key) for result in results)


def _metric_hit_rate(results: list[EvalResult], key: str) -> float:
    if not results:
        return 0.0
    return (
        sum(1 for result in results if _metric_number(_result_metrics(result), key) > 0)
        / len(results)
    )


def _round_nested(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, dict):
        return {k: _round_nested(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_round_nested(v) for v in value]
    return value


def _compact_failure_label(kind: str, text: Any) -> str:
    compact = " ".join(str(text).split())
    if not compact:
        return f"{kind}: failed"
    lower = compact.lower()
    for marker in ("forbidden", "timeout", "missing", "environment", "handoff"):
        if marker in lower:
            return f"{kind}: {marker}"
    if len(compact) > 100:
        compact = f"{compact[:97]}..."
    return f"{kind}: {compact}"


def _verdict_failures(verdict: Any) -> list[Any]:
    details = getattr(verdict, "details", None) or {}
    if not isinstance(details, dict):
        return []
    failures = details.get("failures") or []
    if isinstance(failures, str):
        return [failures]
    if isinstance(failures, (list, tuple, set)):
        return list(failures)
    return []


def _failure_reason(result: EvalResult, metrics: dict[str, Any]) -> str:
    error = getattr(result, "error", None)
    if error:
        return _compact_failure_label("error", error)
    if _metric_number(metrics, "environment_assertions_failed") > 0:
        return "environment_assertions_failed"

    for verdict in getattr(result, "verdicts", []) or []:
        if getattr(verdict, "passed", True):
            continue
        kind = str(getattr(verdict, "kind", "judge") or "judge")
        failures = _verdict_failures(verdict)
        if failures:
            return _compact_failure_label(kind, failures[0])
        reasoning = getattr(verdict, "reasoning", "")
        if reasoning:
            return _compact_failure_label(kind, reasoning)
        return f"{kind}: failed"
    return "unknown_failure"


def _failure_clusters(results: Iterable[EvalResult]) -> list[dict[str, Any]]:
    clusters: dict[tuple[str, str, str], dict[str, Any]] = {}
    for result in results:
        if bool(getattr(result, "passed", False)):
            continue
        metrics = _result_metrics(result)
        capability = ", ".join(_metric_values(metrics, "capability")) or "unclassified"
        risk_level = ", ".join(_metric_values(metrics, "risk_level")) or "unclassified"
        reason = _failure_reason(result, metrics)
        key = (capability, risk_level, reason)
        cluster = clusters.setdefault(
            key,
            {
                "cluster": f"{capability} | {risk_level} | {reason}",
                "capability": capability,
                "risk_level": risk_level,
                "reason": reason,
                "count": 0,
                "case_ids": [],
            },
        )
        cluster["count"] += 1
        cluster["case_ids"].append(str(getattr(result, "case_id", "")))

    return sorted(
        clusters.values(),
        key=lambda item: (-int(item["count"]), str(item["cluster"])),
    )


def _flaky_case_ids(results: Iterable[EvalResult]) -> list[str]:
    buckets: dict[tuple[str, str], list[bool]] = defaultdict(list)
    for result in results:
        metrics = _result_metrics(result)
        base_case_id = str(metrics.get("base_case_id") or getattr(result, "case_id", ""))
        if not base_case_id:
            continue
        model_label = _first_metric_value(metrics, "model_label") or _first_metric_value(metrics, "model")
        buckets[(base_case_id, model_label)].append(bool(getattr(result, "passed", False)))

    return sorted(
        {
            case_id
            for (case_id, _model_label), passes in buckets.items()
            if len(passes) > 1 and any(passes) and not all(passes)
        }
    )


def _sorted_attempts(attempts: list[Any]) -> list[Any]:
    def key(value: Any) -> tuple[int, int | str]:
        try:
            return (0, int(value))
        except (TypeError, ValueError):
            return (1, str(value))

    return sorted({attempt for attempt in attempts if attempt not in (None, "")}, key=key)


def _declared_attempts(value: Any) -> int | float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    if number <= 0:
        return 0
    return int(number) if number.is_integer() else number


def _model_matrix(results: Iterable[EvalResult]) -> dict[str, dict[str, Any]]:
    raw: dict[str, dict[str, Any]] = {}
    for result in results:
        metrics = _result_metrics(result)
        model_label = _first_metric_value(metrics, "model_label") or _first_metric_value(metrics, "model")
        if not model_label:
            continue
        model = _first_metric_value(metrics, "model") or model_label
        entry = raw.setdefault(
            model_label,
            {
                "model": model,
                "total": 0,
                "passed": 0,
                "latencies": [],
                "costs": [],
                "cases": {},
            },
        )
        if not entry["model"] and model:
            entry["model"] = model
        passed = bool(getattr(result, "passed", False))
        case_id = str(getattr(result, "case_id", ""))
        base_case_id = str(metrics.get("base_case_id") or case_id)
        entry["total"] += 1
        entry["passed"] += 1 if passed else 0
        entry["latencies"].append(_metric_number(metrics, "latency_ms"))
        entry["costs"].append(_metric_number(metrics, "cost_usd"))

        cases = entry["cases"]
        case_entry = cases.setdefault(
            base_case_id,
            {
                "total": 0,
                "passed": 0,
                "attempts": [],
                "declared_attempts": 0,
                "case_ids": [],
            },
        )
        case_entry["total"] += 1
        case_entry["passed"] += 1 if passed else 0
        case_entry["attempts"].append(metrics.get("attempt"))
        case_entry["declared_attempts"] = max(
            case_entry["declared_attempts"],
            _declared_attempts(metrics.get("attempts")),
        )
        case_entry["case_ids"].append(case_id)

    matrix: dict[str, dict[str, Any]] = {}
    for model_label, entry in sorted(raw.items()):
        total = int(entry["total"])
        passed = int(entry["passed"])
        case_matrix: dict[str, dict[str, Any]] = {}
        for base_case_id, case_entry in sorted(entry["cases"].items()):
            case_total = int(case_entry["total"])
            case_passed = int(case_entry["passed"])
            case_matrix[base_case_id] = {
                "total": case_total,
                "passed": case_passed,
                "failed": case_total - case_passed,
                "task_success": case_passed / case_total if case_total else 0.0,
                "attempts": _sorted_attempts(case_entry["attempts"]),
                "declared_attempts": case_entry["declared_attempts"],
                "case_ids": sorted({case_id for case_id in case_entry["case_ids"] if case_id}),
            }
        matrix[model_label] = {
            "model": entry["model"],
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "task_success": passed / total if total else 0.0,
            "avg_latency_ms": mean(entry["latencies"]) if entry["latencies"] else 0.0,
            "avg_cost_usd": mean(entry["costs"]) if entry["costs"] else 0.0,
            "cases": case_matrix,
        }
    return matrix


@dataclass(slots=True)
class MetricSummary:
    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    task_success: float = 0.0
    avg_tool_calls: float = 0.0
    avg_llm_calls: float = 0.0
    avg_cache_hits: float = 0.0
    avg_fallback_uses: float = 0.0
    avg_parallel_tool_calls: float = 0.0
    avg_delegation_role_hits: float = 0.0
    avg_handoff_hits: float = 0.0
    avg_critic_gate_hits: float = 0.0
    avg_environment_assertions_failed: float = 0.0
    delegation_role_hit_rate: float = 0.0
    handoff_hit_rate: float = 0.0
    critic_gate_hit_rate: float = 0.0
    fallback_use_rate: float = 0.0
    parallel_tool_call_rate: float = 0.0
    environment_assertion_failure_rate: float = 0.0
    avg_input_tokens: float = 0.0
    avg_output_tokens: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    avg_cost_usd: float = 0.0
    forbidden_tool_violation_rate: float = 0.0
    per_tag_success: dict[str, float] = field(default_factory=dict)
    per_capability_success: dict[str, float] = field(default_factory=dict)
    per_risk_level_success: dict[str, float] = field(default_factory=dict)
    failed_case_ids: list[str] = field(default_factory=list)
    flaky_case_ids: list[str] = field(default_factory=list)
    failure_clusters: list[dict[str, Any]] = field(default_factory=list)
    model_matrix: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "task_success": round(self.task_success, 4),
            "avg_tool_calls": round(self.avg_tool_calls, 3),
            "avg_llm_calls": round(self.avg_llm_calls, 3),
            "avg_cache_hits": round(self.avg_cache_hits, 3),
            "avg_fallback_uses": round(self.avg_fallback_uses, 3),
            "avg_parallel_tool_calls": round(self.avg_parallel_tool_calls, 3),
            "avg_delegation_role_hits": round(self.avg_delegation_role_hits, 3),
            "avg_handoff_hits": round(self.avg_handoff_hits, 3),
            "avg_critic_gate_hits": round(self.avg_critic_gate_hits, 3),
            "avg_environment_assertions_failed": round(
                self.avg_environment_assertions_failed,
                3,
            ),
            "delegation_role_hit_rate": round(self.delegation_role_hit_rate, 4),
            "handoff_hit_rate": round(self.handoff_hit_rate, 4),
            "critic_gate_hit_rate": round(self.critic_gate_hit_rate, 4),
            "fallback_use_rate": round(self.fallback_use_rate, 4),
            "parallel_tool_call_rate": round(self.parallel_tool_call_rate, 4),
            "environment_assertion_failure_rate": round(
                self.environment_assertion_failure_rate,
                4,
            ),
            "avg_input_tokens": round(self.avg_input_tokens, 1),
            "avg_output_tokens": round(self.avg_output_tokens, 1),
            "p50_latency_ms": round(self.p50_latency_ms, 1),
            "p95_latency_ms": round(self.p95_latency_ms, 1),
            "avg_cost_usd": round(self.avg_cost_usd, 5),
            "forbidden_tool_violation_rate": round(self.forbidden_tool_violation_rate, 4),
            "per_tag_success": {k: round(v, 4) for k, v in self.per_tag_success.items()},
            "per_capability_success": {
                k: round(v, 4) for k, v in self.per_capability_success.items()
            },
            "per_risk_level_success": {
                k: round(v, 4) for k, v in self.per_risk_level_success.items()
            },
            "failed_case_ids": list(self.failed_case_ids),
            "flaky_case_ids": list(self.flaky_case_ids),
            "failure_clusters": _round_nested(self.failure_clusters),
            "model_matrix": _round_nested(self.model_matrix),
        }


def aggregate_metrics(results: Iterable[EvalResult]) -> MetricSummary:
    results = list(results)
    summary = MetricSummary(total=len(results))
    if not results:
        return summary

    summary.passed = sum(1 for r in results if bool(getattr(r, "passed", False)))
    summary.failed = summary.total - summary.passed
    summary.errors = sum(1 for r in results if getattr(r, "error", None))
    summary.task_success = summary.passed / summary.total
    summary.failed_case_ids = [
        str(getattr(r, "case_id", "")) for r in results if not bool(getattr(r, "passed", False))
    ]

    summary.avg_tool_calls = _metric_mean(results, "tool_calls")
    summary.avg_llm_calls = _metric_mean(results, "llm_calls")
    summary.avg_cache_hits = _metric_mean(results, "cache_hits")
    summary.avg_fallback_uses = _metric_mean(results, "fallback_uses")
    summary.avg_parallel_tool_calls = _metric_mean(results, "parallel_tool_calls")
    summary.avg_delegation_role_hits = _metric_mean(results, "delegation_role_hits")
    summary.avg_handoff_hits = _metric_mean(results, "handoff_hits")
    summary.avg_critic_gate_hits = _metric_mean(results, "critic_gate_hits")
    summary.avg_environment_assertions_failed = _metric_mean(
        results,
        "environment_assertions_failed",
    )
    summary.avg_input_tokens = _metric_mean(results, "input_tokens")
    summary.avg_output_tokens = _metric_mean(results, "output_tokens")
    summary.avg_cost_usd = _metric_mean(results, "cost_usd")

    summary.delegation_role_hit_rate = _metric_hit_rate(results, "delegation_role_hits")
    summary.handoff_hit_rate = _metric_hit_rate(results, "handoff_hits")
    summary.critic_gate_hit_rate = _metric_hit_rate(results, "critic_gate_hits")
    summary.fallback_use_rate = _metric_hit_rate(results, "fallback_uses")
    summary.parallel_tool_call_rate = _metric_hit_rate(results, "parallel_tool_calls")
    summary.environment_assertion_failure_rate = _metric_hit_rate(
        results,
        "environment_assertions_failed",
    )

    latencies = [_metric_number(_result_metrics(r), "latency_ms") for r in results]
    summary.p50_latency_ms = _percentile(latencies, 50)
    summary.p95_latency_ms = _percentile(latencies, 95)

    forbidden_hits = sum(
        1
        for r in results
        for v in getattr(r, "verdicts", []) or []
        if getattr(v, "kind", None) == "rule"
        and any("forbidden" in str(failure) for failure in _verdict_failures(v))
    )
    summary.forbidden_tool_violation_rate = forbidden_hits / summary.total

    tag_buckets: dict[str, list[bool]] = {}
    for r in results:
        for tag in getattr(r, "tags", []) or []:
            tag_buckets.setdefault(str(tag), []).append(bool(getattr(r, "passed", False)))
    summary.per_tag_success = {
        tag: sum(1 for v in passes if v) / len(passes)
        for tag, passes in tag_buckets.items()
    }
    summary.per_capability_success = _success_breakdown(results, "capability")
    summary.per_risk_level_success = _success_breakdown(results, "risk_level")
    summary.flaky_case_ids = _flaky_case_ids(results)
    summary.failure_clusters = _failure_clusters(results)
    summary.model_matrix = _model_matrix(results)
    return summary


def compare_baselines(
    *, baseline: MetricSummary | None, current: MetricSummary
) -> dict:
    """Return a delta dict and a list of regression flags for CI gating."""
    delta: dict[str, dict] = {}
    regressions: list[str] = []

    fields = [
        ("task_success", True),  # higher is better
        ("avg_tool_calls", False),
        ("avg_llm_calls", False),
        ("avg_input_tokens", False),
        ("avg_output_tokens", False),
        ("p95_latency_ms", False),
        ("avg_cost_usd", False),
        ("forbidden_tool_violation_rate", False),
    ]

    for name, higher_better in fields:
        cur = getattr(current, name)
        base = getattr(baseline, name) if baseline else None
        diff = (cur - base) if base is not None else None
        delta[name] = {"baseline": base, "current": cur, "delta": diff}

        if base is None:
            continue
        if name == "task_success" and (cur - base) < -0.02:
            regressions.append(f"task_success dropped {(cur-base)*100:.1f}pp")
        if name == "forbidden_tool_violation_rate" and cur > base + 1e-9:
            regressions.append(f"forbidden tool violations grew {base:.3f} -> {cur:.3f}")
        if not higher_better and base > 0 and (cur - base) / base > 0.20:
            regressions.append(
                f"{name} grew >20%: {base:.3f} -> {cur:.3f}"
            )

    return {"delta": delta, "regressions": regressions}
