"""LLM-as-judge with a confidence-escalation path.

A small judge model returns {verdict, confidence, reasoning}. Low
confidence (< threshold) automatically escalates to a larger judge.
For offline / CI runs without API keys, `NullLLMJudge` returns a
neutral pass so the harness still works.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from ..schema import EvalCase, JudgeVerdict, TrajectoryStep


_JUDGE_SYSTEM_PROMPT = """You are an evaluator for an AI agent. Given a user task,
the agent's final answer, and its tool-call trace, decide whether the answer satisfies
the rubric.

Respond with a single JSON object and nothing else:
{"verdict": "pass" | "fail", "confidence": 0.0-1.0, "reasoning": "<short>"}

- pass requires the rubric to be fully satisfied.
- confidence is your own certainty, not the agent's.
- reasoning must stay under 40 words.
"""


class JudgeModel(Protocol):
    def invoke(self, prompt: str) -> str: ...


@dataclass(slots=True)
class LLMJudge:
    """LLM-as-judge with optional escalation.

    `primary` is the fast/cheap model. When its confidence is below
    `escalate_below` and `escalator` is provided, the judgement is
    re-run with the bigger model and the escalator's verdict wins.
    """

    kind: str = "llm"
    primary: JudgeModel | None = None
    escalator: JudgeModel | None = None
    escalate_below: float = 0.7

    def evaluate(
        self,
        *,
        case: EvalCase,
        answer: str,
        trajectory: list[TrajectoryStep],
    ) -> JudgeVerdict:
        rubric = ((case.judge.get("llm") or {}).get("rubric") or "").strip()
        enabled = bool((case.judge.get("llm") or {}).get("enabled"))
        if not enabled or not rubric:
            return JudgeVerdict(
                kind=self.kind,
                passed=True,
                reasoning="llm judge disabled for this case",
                confidence=1.0,
                details={"skipped": True},
            )

        if self.primary is None:
            return JudgeVerdict(
                kind=self.kind,
                passed=True,
                reasoning="no primary judge model configured (neutral pass)",
                confidence=0.5,
                details={"skipped": True, "reason": "no_primary_model"},
            )

        prompt = _build_prompt(
            case=case, answer=answer, trajectory=trajectory, rubric=rubric
        )
        primary_result = _invoke_judge(self.primary, prompt)
        if (
            self.escalator is not None
            and primary_result["confidence"] < self.escalate_below
        ):
            escalated = _invoke_judge(self.escalator, prompt)
            verdict = escalated
            verdict["escalated_from"] = primary_result
        else:
            verdict = primary_result

        return JudgeVerdict(
            kind=self.kind,
            passed=verdict["verdict"] == "pass",
            reasoning=verdict.get("reasoning", ""),
            confidence=float(verdict.get("confidence", 0.5)),
            details={k: v for k, v in verdict.items() if k not in {"verdict", "reasoning", "confidence"}},
        )


def _build_prompt(
    *,
    case: EvalCase,
    answer: str,
    trajectory: list[TrajectoryStep],
    rubric: str,
) -> str:
    user_message = (case.input.get("user_message") or "").strip()
    tool_trace = "\n".join(
        f"- {s.tool}({json.dumps(s.args, ensure_ascii=False)[:200]}) -> {s.observation[:200]}"
        for s in trajectory
    ) or "(no tool calls)"

    return (
        f"{_JUDGE_SYSTEM_PROMPT}\n\n"
        f"### Rubric\n{rubric}\n\n"
        f"### User Task\n{user_message}\n\n"
        f"### Agent Answer\n{answer}\n\n"
        f"### Tool Trace\n{tool_trace}\n"
    )


def _invoke_judge(model: JudgeModel, prompt: str) -> dict[str, Any]:
    raw = model.invoke(prompt)
    return _parse_verdict(raw)


def _parse_verdict(raw: str) -> dict[str, Any]:
    text = raw.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        text = match.group(0)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return {"verdict": "fail", "confidence": 0.0, "reasoning": f"unparsable: {raw[:120]}"}
    verdict = str(obj.get("verdict", "fail")).strip().lower()
    if verdict not in {"pass", "fail"}:
        verdict = "fail"
    try:
        confidence = float(obj.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    return {
        "verdict": verdict,
        "confidence": max(0.0, min(1.0, confidence)),
        "reasoning": str(obj.get("reasoning", ""))[:400],
    }


def make_callable_judge(fn: Callable[[str], str]) -> JudgeModel:
    """Wrap a plain callable into the JudgeModel protocol."""

    class _Adapter:
        def invoke(self, prompt: str) -> str:
            return fn(prompt)

    return _Adapter()
