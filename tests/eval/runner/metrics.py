"""Suite acceptance metrics for the test eval runner.

Case execution, usage, cost, and failure metrics live in the production harness.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from focus_agent.eval.runner.harness import _finite_number

from ..schema import EvalResult, JudgeVerdict

_SUITE_ACCEPTANCE_KEYS = ("max_p95_latency_ms", "min_success_rate")


def _apply_suite_acceptance(results: list[EvalResult]) -> list[EvalResult]:
    groups: dict[tuple[str, str], list[EvalResult]] = {}
    policies: dict[tuple[str, str], dict[str, Any]] = {}
    for result in results:
        metrics = result.metrics if isinstance(result.metrics, dict) else {}
        policy = metrics.get("acceptance_policy")
        if not isinstance(policy, Mapping):
            continue
        suite_policy = {key: policy[key] for key in _SUITE_ACCEPTANCE_KEYS if key in policy}
        if not suite_policy:
            continue
        key = (
            str(metrics.get("base_case_id") or result.case_id),
            str(metrics.get("model_label") or ""),
        )
        groups.setdefault(key, []).append(result)
        # Retries of one case must stay together even if a malformed caller
        # supplied different policy dicts on individual attempts.  Normal
        # runs use the same policy for every retry; keep the first one as the
        # canonical case policy rather than letting policy JSON split retries.
        policies.setdefault(key, suite_policy)

    for policy_key, group in groups.items():
        policy = policies[policy_key]
        checks: dict[str, dict[str, Any]] = {}
        if "max_p95_latency_ms" in policy:
            threshold = _finite_number(policy["max_p95_latency_ms"])
            latencies = [_finite_number(result.metrics.get("latency_ms")) for result in group]
            if threshold is None:
                checks["max_p95_latency_ms"] = {
                    "threshold": policy["max_p95_latency_ms"],
                    "status": "invalid",
                    "reason": "threshold_not_numeric",
                }
            elif any(value is None for value in latencies):
                checks["max_p95_latency_ms"] = {
                    "threshold": threshold,
                    "actual": None,
                    "status": "unknown",
                    "reason": "latency_evidence_missing",
                }
            else:
                actual = _percentile([float(value) for value in latencies], 95)
                checks["max_p95_latency_ms"] = {
                    "threshold": threshold,
                    "actual": actual,
                    "status": "pass" if actual <= threshold else "fail",
                }
        if "min_success_rate" in policy:
            threshold = _finite_number(policy["min_success_rate"])
            success_rate = sum(bool(result.passed) for result in group) / len(group)
            checks["min_success_rate"] = {
                "threshold": policy["min_success_rate"],
                "actual": success_rate,
                "status": (
                    "invalid"
                    if threshold is None
                    else "pass"
                    if success_rate >= threshold
                    else "fail"
                ),
            }
            if threshold is None:
                checks["min_success_rate"]["reason"] = "threshold_not_numeric"

        suite_passed = all(check.get("status") == "pass" for check in checks.values())
        runtime_kinds = sorted(
            {str(result.metrics.get("runtime_kind") or "unknown") for result in group}
        )
        for result in group:
            metrics = result.metrics if isinstance(result.metrics, dict) else {}
            acceptance = dict(metrics.get("acceptance") or {})
            acceptance.update(checks)
            metrics["acceptance"] = acceptance
            result.verdicts.append(
                JudgeVerdict(
                    kind="acceptance",
                    passed=suite_passed,
                    reasoning=(
                        "suite acceptance checks passed"
                        if suite_passed
                        else "; ".join(
                            f"{key}={value.get('status')}" for key, value in checks.items()
                        )
                    ),
                    confidence=1.0,
                    details={
                        "scope": "suite",
                        "checks": checks,
                        "runtime_kinds": runtime_kinds,
                        "provider_evaluation": "provider" in runtime_kinds,
                    },
                )
            )
            if not suite_passed:
                result.passed = False
    return results


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round(pct / 100.0 * (len(ordered) - 1)))))
    return ordered[index]
