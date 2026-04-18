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

        if optimal:
            distance = _levenshtein(optimal, actual)
            recall = sum(1 for tool in optimal if tool in actual) / max(1, len(optimal))
            tolerance = int(expected.get("trajectory_tolerance", 1))
            passed = distance <= tolerance
            return JudgeVerdict(
                kind=self.kind,
                passed=passed,
                reasoning=f"edit_distance={distance} (tolerance={tolerance}); recall={recall:.2f}",
                confidence=1.0,
                details={
                    "actual_sequence": actual,
                    "optimal_sequence": optimal,
                    "edit_distance": distance,
                    "recall": recall,
                },
            )

        if max_calls is not None:
            passed = len(actual) <= int(max_calls)
            return JudgeVerdict(
                kind=self.kind,
                passed=passed,
                reasoning=f"tool_calls={len(actual)} (max={max_calls})",
                confidence=1.0,
                details={"actual_sequence": actual, "max_tool_calls": int(max_calls)},
            )

        return JudgeVerdict(
            kind=self.kind,
            passed=True,
            reasoning="no trajectory expectation set",
            confidence=1.0,
            details={"skipped": True},
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
