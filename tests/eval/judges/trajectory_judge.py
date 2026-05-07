"""Trajectory efficiency judge.

When `expected.optimal_tool_sequence` is provided, score the actual
tool sequence by Levenshtein-style edit distance / recall. Otherwise
fall back to "did we exceed max_tool_calls?" boolean.
"""

from __future__ import annotations

from collections import Counter
import json
from typing import Any

from ..schema import EvalCase, JudgeVerdict, TrajectoryStep


class TrajectoryJudge:
    kind = "trajectory"

    def evaluate(
        self,
        *,
        case: EvalCase,
        answer: str,  # noqa: ARG002
        trajectory: list[TrajectoryStep],
        state: dict[str, Any] | None = None,  # noqa: ARG002
        before_state: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> JudgeVerdict:
        actual = [step.tool for step in trajectory]
        expected = case.expected
        optimal = expected.get("optimal_tool_sequence")
        max_calls = expected.get("max_tool_calls")
        checks_run: list[str] = []
        failures: list[str] = []
        details: dict[str, object] = {
            "actual_sequence": actual,
        }

        if optimal:
            checks_run.append("optimal_tool_sequence")
            distance = _levenshtein(optimal, actual)
            recall = sum(1 for tool in optimal if tool in actual) / max(1, len(optimal))
            tolerance = int(expected.get("trajectory_tolerance", 1))
            details.update(
                {
                    "optimal_sequence": optimal,
                    "edit_distance": distance,
                    "recall": recall,
                }
            )
            if distance > tolerance:
                failures.append(f"edit_distance={distance} exceeded tolerance={tolerance}")

        if max_calls is not None:
            checks_run.append("max_tool_calls")
            details["max_tool_calls"] = int(max_calls)
            if len(actual) > int(max_calls):
                failures.append(f"tool_calls={len(actual)} exceeded max_tool_calls={max_calls}")

        cache_hits = sum(1 for step in trajectory if step.cache_hit)
        fallback_uses = sum(1 for step in trajectory if step.fallback_used)
        parallel_tool_calls = sum(1 for step in trajectory if (step.parallel_batch_size or 0) > 1)
        details.update(
            {
                "cache_hits": cache_hits,
                "fallback_uses": fallback_uses,
                "parallel_tool_calls": parallel_tool_calls,
            }
        )

        _check_count_expectation(
            failures=failures,
            checks_run=checks_run,
            label="cache_hits",
            actual=cache_hits,
            min_expected=expected.get("min_cache_hits"),
            max_expected=expected.get("max_cache_hits"),
        )
        _check_count_expectation(
            failures=failures,
            checks_run=checks_run,
            label="fallback_uses",
            actual=fallback_uses,
            min_expected=expected.get("min_fallback_uses"),
            max_expected=expected.get("max_fallback_uses"),
        )
        _check_count_expectation(
            failures=failures,
            checks_run=checks_run,
            label="parallel_tool_calls",
            actual=parallel_tool_calls,
            min_expected=expected.get("min_parallel_tool_calls"),
            max_expected=expected.get("max_parallel_tool_calls"),
        )

        _check_required_runtime_tools(
            failures=failures,
            checks_run=checks_run,
            label="must_hit_cache_tools_any_order",
            expected_tools=expected.get("must_hit_cache_tools_any_order"),
            actual_tools=[step.tool for step in trajectory if step.cache_hit],
        )
        _check_required_runtime_tools(
            failures=failures,
            checks_run=checks_run,
            label="must_use_fallback_tools_any_order",
            expected_tools=expected.get("must_use_fallback_tools_any_order"),
            actual_tools=[step.tool for step in trajectory if step.fallback_used],
        )
        _check_required_runtime_tools(
            failures=failures,
            checks_run=checks_run,
            label="must_parallelize_tools_any_order",
            expected_tools=expected.get("must_parallelize_tools_any_order"),
            actual_tools=[step.tool for step in trajectory if (step.parallel_batch_size or 0) > 1],
        )

        _check_collaboration_expectations(
            failures=failures,
            checks_run=checks_run,
            details=details,
            expected=expected,
            trajectory=trajectory,
        )

        if checks_run:
            return JudgeVerdict(
                kind=self.kind,
                passed=not failures,
                reasoning="; ".join(failures) if failures else "all trajectory checks passed",
                confidence=1.0,
                details={**details, "checks_run": checks_run, "failures": failures},
            )

        return JudgeVerdict(
            kind=self.kind,
            passed=True,
            reasoning="no trajectory expectation set",
            confidence=1.0,
            details={"skipped": True, "checks_run": []},
        )


def _levenshtein(a: list[str], b: list[str]) -> int:
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            curr[j] = min(
                curr[j - 1] + 1,
                prev[j] + 1,
                prev[j - 1] + cost,
            )
        prev = curr
    return prev[-1]


def _check_count_expectation(
    *,
    failures: list[str],
    checks_run: list[str],
    label: str,
    actual: int,
    min_expected: object,
    max_expected: object,
) -> None:
    if min_expected is None and max_expected is None:
        return
    checks_run.append(label)
    if min_expected is not None and actual < int(min_expected):
        failures.append(f"{label}={actual} fell below min_{label}={int(min_expected)}")
    if max_expected is not None and actual > int(max_expected):
        failures.append(f"{label}={actual} exceeded max_{label}={int(max_expected)}")


def _check_required_runtime_tools(
    *,
    failures: list[str],
    checks_run: list[str],
    label: str,
    expected_tools: object,
    actual_tools: list[str],
) -> None:
    if not expected_tools:
        return
    checks_run.append(label)
    missing = [tool for tool in list(expected_tools) if tool not in actual_tools]
    if missing:
        failures.append(f"{label} missing tools {missing!r}")


def _is_subsequence(needle: list[Any], haystack: list[Any]) -> bool:
    it = iter(haystack)
    return all(any(token == hit for hit in it) for token in needle)


def _check_collaboration_expectations(
    *,
    failures: list[str],
    checks_run: list[str],
    details: dict[str, object],
    expected: dict[str, Any],
    trajectory: list[TrajectoryStep],
) -> None:
    delegated_roles = _trajectory_delegated_roles(trajectory)
    role_runs = _collapse_adjacent(_trajectory_role_events(trajectory))
    handoffs = _trajectory_handoffs(trajectory)

    if expected.get("must_delegate_to_roles_any_order"):
        label = "must_delegate_to_roles_any_order"
        checks_run.append(label)
        expected_roles = _expected_list(expected[label])
        missing = [role for role in expected_roles if role not in delegated_roles]
        if missing:
            failures.append(f"{label} missing roles {missing!r}")

    if expected.get("must_delegate_to_roles_sequence"):
        label = "must_delegate_to_roles_sequence"
        checks_run.append(label)
        expected_roles = _expected_list(expected[label])
        if not _is_subsequence(expected_roles, delegated_roles):
            failures.append(
                f"delegated role sequence {delegated_roles!r} does not contain "
                f"required subsequence {expected_roles!r}"
            )

    if expected.get("must_not_delegate_to_roles"):
        label = "must_not_delegate_to_roles"
        checks_run.append(label)
        forbidden = [role for role in _expected_list(expected[label]) if role in delegated_roles]
        if forbidden:
            failures.append(f"{label} observed forbidden roles {forbidden!r}")

    if expected.get("must_record_handoffs_any_order"):
        label = "must_record_handoffs_any_order"
        checks_run.append(label)
        expected_handoffs = [_handoff_label(item) for item in _expected_list(expected[label])]
        missing = [handoff for handoff in expected_handoffs if handoff not in handoffs]
        if missing:
            failures.append(f"{label} missing handoffs {missing!r}")

    max_duplicate_tool_calls = expected.get("max_duplicate_tool_calls")
    if max_duplicate_tool_calls is not None:
        label = "max_duplicate_tool_calls"
        checks_run.append(label)
        duplicate_total, duplicate_details = _duplicate_tool_calls(trajectory)
        details["duplicate_tool_calls"] = duplicate_details
        details["duplicate_tool_call_count"] = duplicate_total
        if duplicate_total > int(max_duplicate_tool_calls):
            failures.append(
                f"duplicate_tool_calls={duplicate_total} exceeded "
                f"max_duplicate_tool_calls={int(max_duplicate_tool_calls)}"
            )

    max_repeated_role_runs = expected.get("max_repeated_role_runs")
    if max_repeated_role_runs is not None:
        label = "max_repeated_role_runs"
        checks_run.append(label)
        role_run_counts = dict(Counter(role_runs))
        offenders = {
            role: count
            for role, count in role_run_counts.items()
            if count > int(max_repeated_role_runs)
        }
        details["role_run_counts"] = role_run_counts
        if offenders:
            failures.append(
                f"{label} exceeded for roles {offenders!r}; "
                f"max_repeated_role_runs={int(max_repeated_role_runs)}"
            )

    if any(
        key in expected
        for key in {
            "must_delegate_to_roles_any_order",
            "must_delegate_to_roles_sequence",
            "must_not_delegate_to_roles",
            "must_record_handoffs_any_order",
            "max_repeated_role_runs",
        }
    ):
        details.update(
            {
                "delegated_roles": delegated_roles,
                "role_runs": role_runs,
                "handoffs": handoffs,
            }
        )


def _trajectory_role_events(trajectory: list[TrajectoryStep]) -> list[str]:
    events: list[str] = []
    for step in trajectory:
        roles = _step_primary_roles(step)
        if not roles:
            roles = _role_values(
                [
                    _mapping_value(step.runtime, "handoff_from"),
                    _mapping_value(step.runtime, "handoff_to"),
                ]
            )
        for role in roles:
            events.append(role)
    return events


def _trajectory_delegated_roles(trajectory: list[TrajectoryStep]) -> list[str]:
    events: list[str] = []
    for step in trajectory:
        roles = _step_primary_roles(step)
        roles.extend(
            role
            for role in _role_values(
                [
                    _mapping_value(step.runtime, "handoff_from"),
                    _mapping_value(step.runtime, "handoff_to"),
                ]
            )
            if role not in roles
        )
        for role in roles:
            events.append(role)
    return events


def _trajectory_handoffs(trajectory: list[TrajectoryStep]) -> list[str]:
    handoffs: list[str] = []
    for step in trajectory:
        current_roles = _step_primary_roles(step)
        from_roles = _role_values([_mapping_value(step.runtime, "handoff_from")])
        to_roles = _role_values([_mapping_value(step.runtime, "handoff_to")])
        if current_roles and to_roles:
            handoffs.extend(
                f"{source}->{target}" for source in current_roles for target in to_roles
            )
        if from_roles and current_roles:
            handoffs.extend(
                f"{source}->{target}" for source in from_roles for target in current_roles
            )
        if from_roles and to_roles:
            handoffs.extend(f"{source}->{target}" for source in from_roles for target in to_roles)
        elif from_roles and not current_roles:
            handoffs.extend(f"{source}->" for source in from_roles)
        handoffs.extend(to_roles)
    return handoffs


def _step_primary_roles(step: TrajectoryStep) -> list[str]:
    return _role_values(
        [
            _mapping_value(step.args, "role"),
            _mapping_value(step.args, "agent_role"),
            _mapping_value(step.runtime, "role"),
            _mapping_value(step.runtime, "branch_role"),
        ]
    )


def _role_values(values: list[Any]) -> list[str]:
    roles: list[str] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, (list, tuple, set)):
            candidates = value
        else:
            candidates = [value]
        for candidate in candidates:
            role = str(candidate).strip()
            if role and role not in roles:
                roles.append(role)
    return roles


def _mapping_value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return None


def _expected_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _handoff_label(value: Any) -> str:
    if isinstance(value, dict):
        source = value.get("from", value.get("handoff_from", value.get("source")))
        target = value.get("to", value.get("handoff_to", value.get("target")))
        if source is not None and target is not None:
            return f"{source}->{target}"
        if target is not None:
            return str(target)
        if source is not None:
            return f"{source}->"
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return f"{value[0]}->{value[1]}"
    return str(value)


def _duplicate_tool_calls(trajectory: list[TrajectoryStep]) -> tuple[int, list[dict[str, object]]]:
    counts: Counter[str] = Counter()
    examples: dict[str, dict[str, object]] = {}
    for step in trajectory:
        args = dict(step.args or {})
        signature = f"{step.tool}:{_json_key(args)}"
        counts[signature] += 1
        examples.setdefault(signature, {"tool": step.tool, "args": args})

    duplicate_details = [
        {**examples[signature], "count": count}
        for signature, count in counts.items()
        if count > 1
    ]
    duplicate_total = sum(int(item["count"]) - 1 for item in duplicate_details)
    return duplicate_total, duplicate_details


def _json_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, default=str)


def _collapse_adjacent(values: list[str]) -> list[str]:
    collapsed: list[str] = []
    for value in values:
        if not collapsed or collapsed[-1] != value:
            collapsed.append(value)
    return collapsed
