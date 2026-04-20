"""Core data structures for the agent eval framework."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class TrajectoryStep:
    tool: str
    args: dict[str, Any]
    observation: str
    duration_ms: float = 0.0
    error: str | None = None
    cache_hit: bool = False
    fallback_used: bool = False
    fallback_group: str | None = None
    parallel_batch_size: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "args": self.args,
            "observation": self.observation[:2000],
            "duration_ms": self.duration_ms,
            "error": self.error,
            "cache_hit": self.cache_hit,
            "fallback_used": self.fallback_used,
            "fallback_group": self.fallback_group,
            "parallel_batch_size": self.parallel_batch_size,
        }


@dataclass(slots=True)
class EvalCase:
    id: str
    input: dict[str, Any]
    expected: dict[str, Any]
    tags: list[str] = field(default_factory=list)
    scene: str = "long_dialog_research"
    skill_hints: list[str] = field(default_factory=list)
    setup: list[dict[str, str]] = field(default_factory=list)
    judge: dict[str, Any] = field(default_factory=lambda: {"rule": True, "llm": {"enabled": False}})
    origin: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "EvalCase":
        return cls(
            id=str(raw["id"]),
            input=dict(raw.get("input") or {}),
            expected=dict(raw.get("expected") or {}),
            tags=list(raw.get("tags") or []),
            scene=str(raw.get("scene") or "long_dialog_research"),
            skill_hints=list(raw.get("skill_hints") or []),
            setup=list(raw.get("setup") or []),
            judge=dict(raw.get("judge") or {"rule": True, "llm": {"enabled": False}}),
            origin=raw.get("origin"),
        )


@dataclass(slots=True)
class JudgeVerdict:
    kind: str  # "rule" | "llm" | "trajectory"
    passed: bool
    reasoning: str = ""
    confidence: float = 1.0
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "passed": self.passed,
            "reasoning": self.reasoning,
            "confidence": self.confidence,
            "details": self.details,
        }


@dataclass(slots=True)
class EvalResult:
    case_id: str
    passed: bool
    answer: str
    verdicts: list[JudgeVerdict] = field(default_factory=list)
    trajectory: list[TrajectoryStep] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "passed": self.passed,
            "answer": self.answer,
            "verdicts": [v.to_dict() for v in self.verdicts],
            "trajectory": [s.to_dict() for s in self.trajectory],
            "metrics": self.metrics,
            "error": self.error,
            "tags": self.tags,
        }
