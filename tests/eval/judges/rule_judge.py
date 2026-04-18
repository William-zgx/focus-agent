"""Rule-based judge: regex / substring / tool-call assertions.

Deterministic, zero cost, runs first. If it fails on required checks
the case is marked failed without invoking the LLM judge.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from ..schema import EvalCase, JudgeVerdict, TrajectoryStep


class RuleJudge:
    kind = "rule"

    def evaluate(
        self,
        *,
        case: EvalCase,
        answer: str,
        trajectory: list[TrajectoryStep],
    ) -> JudgeVerdict:
        expected = case.expected
        failures: list[str] = []
        checks: list[str] = []

        contains_any = expected.get("answer_contains_any")
        if contains_any:
            checks.append("answer_contains_any")
            if not any(needle.lower() in answer.lower() for needle in contains_any):
                failures.append(f"answer missing any of {contains_any!r}")

        contains_all = expected.get("answer_contains_all")
        if contains_all:
            checks.append("answer_contains_all")
            missing = [n for n in contains_all if n.lower() not in answer.lower()]
            if missing:
                failures.append(f"answer missing required substrings {missing!r}")

        not_contains = expected.get("answer_must_not_contain")
        if not_contains:
            checks.append("answer_must_not_contain")
            for pattern in not_contains:
                if pattern.lower() in answer.lower():
                    failures.append(f"answer must not contain {pattern!r}")

        regex_required = expected.get("answer_regex")
        if regex_required:
            checks.append("answer_regex")
            if not re.search(regex_required, answer):
                failures.append(f"answer did not match regex {regex_required!r}")

        regex_forbidden = expected.get("answer_must_not_contain_regex")
        if regex_forbidden:
            checks.append("answer_must_not_contain_regex")
            if re.search(regex_forbidden, answer):
                failures.append(f"answer matched forbidden regex {regex_forbidden!r}")

        tool_names = [step.tool for step in trajectory]
        must_call_any = expected.get("must_call_tools_any_order")
        if must_call_any:
            checks.append("must_call_tools_any_order")
            missing = [t for t in must_call_any if t not in tool_names]
            if missing:
                failures.append(f"did not call required tools {missing!r}")

        must_call_seq = expected.get("must_call_tools_sequence")
        if must_call_seq:
            checks.append("must_call_tools_sequence")
            if not _is_subsequence(must_call_seq, tool_names):
                failures.append(
                    f"tool sequence {tool_names!r} does not contain required subsequence {must_call_seq!r}"
                )

        must_not_call = expected.get("must_not_call_tools")
        if must_not_call:
            checks.append("must_not_call_tools")
            forbidden_hits = [t for t in must_not_call if t in tool_names]
            if forbidden_hits:
                failures.append(f"called forbidden tools {forbidden_hits!r}")

        max_tool_calls = expected.get("max_tool_calls")
        if max_tool_calls is not None:
            checks.append("max_tool_calls")
            if len(trajectory) > int(max_tool_calls):
                failures.append(
                    f"tool_calls={len(trajectory)} exceeded max_tool_calls={max_tool_calls}"
                )

        return JudgeVerdict(
            kind=self.kind,
            passed=not failures,
            reasoning="; ".join(failures) if failures else "all rule checks passed",
            confidence=1.0,
            details={"checks_run": checks, "failures": failures},
        )


def _is_subsequence(needle: Iterable[Any], haystack: list[Any]) -> bool:
    it = iter(haystack)
    return all(any(token == hit for hit in it) for token in needle)
