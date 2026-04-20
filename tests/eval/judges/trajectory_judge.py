"""Trajectory efficiency judge.

When `expected.optimal_tool_sequence` is provided, score the actual
tool sequence by Levenshtein-style edit distance / recall. Otherwise
fall back to "did we exceed max_tool_calls?" boolean.
"""

from __future__ import annotations

from ..schema import EvalCase, JudgeVerdict, TrajectoryStep


class TrajectoryJudge:
    kind = "trajectory"

    def evaluate(
        self,
        *,
        case: EvalCase,
        answer: str,  # noqa: ARG002
        trajectory: list[TrajectoryStep],
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
