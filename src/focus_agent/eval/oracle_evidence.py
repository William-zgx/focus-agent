"""Shared oracle evidence adaptation for production and compatibility eval runners."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .environment_oracle import run_environment_oracle
from .judges.environment_judge import environment_uses_oracle
from .schema import EvalCase, JudgeVerdict


def run_oracle_evidence(
    *, case: EvalCase, answer: str
) -> tuple[JudgeVerdict | None, dict[str, Any] | None]:
    result = run_environment_oracle(case, candidate_patch=answer)
    if result is None:
        return None, None
    payload = result.to_dict()
    verdict = JudgeVerdict(
        kind="environment_oracle",
        passed=result.passed,
        reasoning=result.reason,
        confidence=1.0,
        details=payload,
    )
    oracle_state = dict(payload) if environment_uses_oracle(case) else None
    return verdict, oracle_state


def has_invalid_environment(verdicts: Iterable[JudgeVerdict]) -> bool:
    return any(
        verdict.kind == "environment_oracle"
        and verdict.details.get("status") == "environment_invalid"
        for verdict in verdicts
    )


__all__ = ["has_invalid_environment", "run_oracle_evidence"]
