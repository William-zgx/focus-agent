"""Billing, acceptance, and aggregate metrics for the eval harness."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from langchain.messages import AIMessage

from focus_agent.core.token_usage import message_token_usage

from ..schema import EvalCase, EvalResult, JudgeVerdict, TrajectoryStep

if TYPE_CHECKING:
    from .harness import EvalRuntime


def _build_metrics(
    *,
    case: EvalCase,
    state: dict[str, Any],
    trajectory: list[TrajectoryStep],
    latency_ms: float,
    runtime: EvalRuntime,
    verdicts: list[JudgeVerdict],
    model_label: str | None,
    model_name: str,
    base_case_id: str,
    attempt: int,
    attempts: int,
) -> dict[str, Any]:
    llm_calls = int(state.get("llm_calls") or 0)
    tool_calls = len(trajectory)
    # Token accounting is only authoritative when the provider reports both
    # prompt and completion usage. Missing usage must not become a fake $0.
    input_tokens = 0
    output_tokens = 0
    usage_messages = 0
    messages = state.get("messages", []) or []
    ai_messages = sum(isinstance(msg, AIMessage) for msg in messages)
    for msg in messages:
        usage = message_token_usage(msg)
        if usage is not None and _has_complete_usage(msg):
            input_tokens += int(usage.get("input_tokens", 0) or 0)
            output_tokens += int(usage.get("output_tokens", 0) or 0)
            usage_messages += 1

    prices_configured = (
        runtime.cost_per_1k_input is not None and runtime.cost_per_1k_output is not None
    )
    usage_complete = bool(usage_messages and usage_messages >= max(llm_calls, ai_messages))
    cost_known = usage_complete and prices_configured
    cost_usd = (
        input_tokens / 1000.0 * float(runtime.cost_per_1k_input)
        + output_tokens / 1000.0 * float(runtime.cost_per_1k_output)
        if cost_known
        else None
    )
    runtime_kind = _runtime_kind(runtime)
    is_harness_stability = "harness" in case.tags and "stability" in case.tags
    cache_hits = sum(1 for step in trajectory if step.cache_hit)
    fallback_uses = sum(1 for step in trajectory if step.fallback_used)
    parallel_tool_calls = sum(1 for step in trajectory if (step.parallel_batch_size or 0) > 1)
    role_hits = _delegation_role_hits(trajectory)
    handoff_hits = _handoff_hits(trajectory)
    critic_gate_hits = _critic_gate_hits(state, trajectory)
    environment_failures = sum(
        len(verdict.details.get("failures", []))
        for verdict in verdicts
        if verdict.kind == "environment"
    )
    metrics = {
        "latency_ms": latency_ms,
        "tool_calls": tool_calls,
        "llm_calls": llm_calls,
        "input_tokens": input_tokens if usage_complete else None,
        "output_tokens": output_tokens if usage_complete else None,
        "cost_usd": cost_usd,
        "cost_status": "measured" if cost_known else "unknown",
        "cost_unknown_reason": (
            None
            if cost_known
            else "usage_metadata_missing"
            if not usage_messages
            else "usage_metadata_incomplete"
            if not usage_complete
            else "price_missing"
        ),
        "usage_messages": usage_messages,
        "runtime_kind": runtime_kind,
        "provider_evaluation": runtime_kind == "provider",
        "model_quality_evidence": runtime_kind == "provider" and not is_harness_stability,
        "eval_layer": (
            "harness_stability"
            if is_harness_stability
            else "model_quality"
            if runtime_kind == "provider"
            else "fake_runtime"
        ),
        "acceptance_policy": dict(case.acceptance or {}),
        "cache_hits": cache_hits,
        "fallback_uses": fallback_uses,
        "parallel_tool_calls": parallel_tool_calls,
        "delegation_role_hits": role_hits,
        "handoff_hits": handoff_hits,
        "critic_gate_hits": critic_gate_hits,
        "environment_assertions_failed": environment_failures,
        "model_label": model_label,
        "model": model_name,
        "base_case_id": base_case_id,
        "attempt": attempt,
        "attempts": attempts,
        "capability": case.capability,
        "risk_level": case.risk_level,
    }
    metrics["acceptance"] = _initial_acceptance_checks(case.acceptance, metrics)
    return metrics


_SUITE_ACCEPTANCE_KEYS = ("max_p95_latency_ms", "min_success_rate")


def _runtime_kind(runtime: EvalRuntime) -> str:
    configured = str(runtime.runtime_kind or "").strip().lower()
    if configured in {"fake", "provider"}:
        return configured
    return "fake" if runtime.model_factory is not None else "provider"


def _has_complete_usage(message: Any) -> bool:
    input_keys = {"input_tokens", "prompt_tokens", "prompt_token_count"}
    output_keys = {"output_tokens", "completion_tokens", "completion_token_count"}
    seen_keys: set[str] = set()
    for payload in _usage_payloads(message):
        seen_keys.update(payload)
    return bool(seen_keys & input_keys and seen_keys & output_keys)


def _usage_payloads(message: Any) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for value in (
        getattr(message, "usage_metadata", None),
        getattr(message, "response_metadata", None),
        getattr(message, "additional_kwargs", None),
    ):
        if not isinstance(value, Mapping):
            continue
        payloads.append(dict(value))
        for key in ("token_usage", "usage", "usage_metadata"):
            nested = value.get(key)
            if isinstance(nested, Mapping):
                payloads.append(dict(nested))
    return payloads


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _initial_acceptance_checks(
    acceptance: Mapping[str, Any] | None,
    metrics: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    checks: dict[str, dict[str, Any]] = {}
    for key, raw_threshold in dict(acceptance or {}).items():
        if key not in {"max_cost_usd", "max_p95_latency_ms", "min_success_rate"}:
            continue
        threshold = _finite_number(raw_threshold)
        check: dict[str, Any] = {"threshold": raw_threshold}
        if threshold is None:
            check.update({"status": "invalid", "reason": "threshold_not_numeric"})
        elif key == "max_cost_usd":
            actual = metrics.get("cost_usd")
            check["actual"] = actual
            if actual is None:
                check.update({"status": "unknown", "reason": metrics.get("cost_unknown_reason")})
            else:
                check["status"] = "pass" if float(actual) <= threshold else "fail"
        else:
            check.update({"status": "deferred", "scope": "suite"})
        checks[key] = check
    return checks


def _evaluate_case_acceptance(
    *,
    case: EvalCase,
    metrics: dict[str, Any],
) -> JudgeVerdict | None:
    checks = dict(metrics.get("acceptance") or {})
    cost_check = checks.get("max_cost_usd")
    if not isinstance(cost_check, dict):
        return None
    status = str(cost_check.get("status") or "unknown")
    passed = status == "pass"
    if status == "unknown":
        reason = "max_cost_usd cannot be verified: billing evidence is unknown"
    elif status == "invalid":
        reason = "max_cost_usd threshold is invalid"
    elif status == "fail":
        reason = (
            f"cost_usd={cost_check.get('actual')} exceeded "
            f"max_cost_usd={cost_check.get('threshold')}"
        )
    else:
        reason = "case acceptance checks passed"
    return JudgeVerdict(
        kind="acceptance",
        passed=passed,
        reasoning=reason,
        confidence=1.0,
        details={
            "scope": "case",
            "checks": checks,
            "runtime_kind": metrics.get("runtime_kind"),
            "provider_evaluation": metrics.get("provider_evaluation", False),
        },
    )


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


def _failure_metrics(
    *,
    case: EvalCase,
    runtime: EvalRuntime,
    latency_ms: float | None,
    model_label: str | None,
    model_name: str,
    base_case_id: str,
    attempt: int,
    attempts: int,
) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "latency_ms": latency_ms,
        "tool_calls": 0,
        "llm_calls": 0,
        "input_tokens": None,
        "output_tokens": None,
        "cost_usd": None,
        "cost_status": "unknown",
        "cost_unknown_reason": "runtime_failed",
        "usage_messages": 0,
        "runtime_kind": _runtime_kind(runtime),
        "provider_evaluation": _runtime_kind(runtime) == "provider",
        "model_quality_evidence": False,
        "eval_layer": (
            "harness_stability"
            if "harness" in case.tags and "stability" in case.tags
            else "model_quality"
            if _runtime_kind(runtime) == "provider"
            else "fake_runtime"
        ),
        "acceptance_policy": dict(case.acceptance or {}),
        "model_label": model_label,
        "model": model_name,
        "base_case_id": base_case_id,
        "attempt": attempt,
        "attempts": attempts,
        "capability": case.capability,
        "risk_level": case.risk_level,
    }
    metrics["acceptance"] = _initial_acceptance_checks(case.acceptance, metrics)
    return metrics


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round(pct / 100.0 * (len(ordered) - 1)))))
    return ordered[index]


def _delegation_role_hits(trajectory: list[TrajectoryStep]) -> int:
    roles: set[str] = set()
    for step in trajectory:
        for key in ("role", "agent_role", "branch_role"):
            value = step.args.get(key) or step.runtime.get(key)
            if value:
                roles.add(str(value))
    return len(roles)


def _handoff_hits(trajectory: list[TrajectoryStep]) -> int:
    hits = 0
    for step in trajectory:
        runtime = step.runtime or {}
        if runtime.get("handoff_to") or runtime.get("handoff_from"):
            hits += 1
        if step.args.get("handoff_to") or step.args.get("handoff_from"):
            hits += 1
    return hits


def _critic_gate_hits(state: dict[str, Any], trajectory: list[TrajectoryStep]) -> int:
    hits = 0
    records = state.get("agent_review_queue") or state.get("critic_gate_records") or []
    if isinstance(records, list):
        hits += len(records)
    for step in trajectory:
        role = step.args.get("role") or step.runtime.get("role") or step.runtime.get("branch_role")
        if str(role or "").lower() == "critic":
            hits += 1
    return hits
