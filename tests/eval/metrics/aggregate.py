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

from dataclasses import dataclass, field
from statistics import mean
from typing import Iterable

from ..schema import EvalResult


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, int(round(pct / 100.0 * (len(ordered) - 1)))))
    return ordered[k]


@dataclass(slots=True)
class MetricSummary:
    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    task_success: float = 0.0
    avg_tool_calls: float = 0.0
    avg_llm_calls: float = 0.0
    avg_input_tokens: float = 0.0
    avg_output_tokens: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    avg_cost_usd: float = 0.0
    forbidden_tool_violation_rate: float = 0.0
    per_tag_success: dict[str, float] = field(default_factory=dict)
    failed_case_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "task_success": round(self.task_success, 4),
            "avg_tool_calls": round(self.avg_tool_calls, 3),
            "avg_llm_calls": round(self.avg_llm_calls, 3),
            "avg_input_tokens": round(self.avg_input_tokens, 1),
            "avg_output_tokens": round(self.avg_output_tokens, 1),
            "p50_latency_ms": round(self.p50_latency_ms, 1),
            "p95_latency_ms": round(self.p95_latency_ms, 1),
            "avg_cost_usd": round(self.avg_cost_usd, 5),
            "forbidden_tool_violation_rate": round(self.forbidden_tool_violation_rate, 4),
            "per_tag_success": {k: round(v, 4) for k, v in self.per_tag_success.items()},
            "failed_case_ids": list(self.failed_case_ids),
        }


def aggregate_metrics(results: Iterable[EvalResult]) -> MetricSummary:
    results = list(results)
    summary = MetricSummary(total=len(results))
    if not results:
        return summary

    summary.passed = sum(1 for r in results if r.passed)
    summary.failed = summary.total - summary.passed
    summary.errors = sum(1 for r in results if r.error)
    summary.task_success = summary.passed / summary.total
    summary.failed_case_ids = [r.case_id for r in results if not r.passed]

    summary.avg_tool_calls = mean(r.metrics.get("tool_calls", 0) for r in results)
    summary.avg_llm_calls = mean(r.metrics.get("llm_calls", 0) for r in results)
    summary.avg_input_tokens = mean(r.metrics.get("input_tokens", 0) for r in results)
    summary.avg_output_tokens = mean(r.metrics.get("output_tokens", 0) for r in results)
    summary.avg_cost_usd = mean(float(r.metrics.get("cost_usd", 0.0)) for r in results)

    latencies = [float(r.metrics.get("latency_ms", 0.0)) for r in results]
    summary.p50_latency_ms = _percentile(latencies, 50)
    summary.p95_latency_ms = _percentile(latencies, 95)

    forbidden_hits = sum(
        1
        for r in results
        for v in r.verdicts
        if v.kind == "rule"
        and any("forbidden" in f for f in v.details.get("failures", []))
    )
    summary.forbidden_tool_violation_rate = forbidden_hits / summary.total

    tag_buckets: dict[str, list[bool]] = {}
    for r in results:
        for tag in r.tags:
            tag_buckets.setdefault(tag, []).append(r.passed)
    summary.per_tag_success = {
        tag: sum(1 for v in passes if v) / len(passes)
        for tag, passes in tag_buckets.items()
    }
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
