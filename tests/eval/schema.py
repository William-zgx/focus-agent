"""Core data structures for the agent eval framework."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from focus_agent.observability.trajectory import TrajectoryStep


@dataclass(slots=True)
class EvalCase:
    id: str
    input: dict[str, Any]
    expected: dict[str, Any]
    tags: list[str] = field(default_factory=list)
    capability: str | None = None
    risk_level: str | None = None
    agent_topology: dict[str, Any] = field(default_factory=dict)
    environment: dict[str, Any] = field(default_factory=dict)
    model_matrix: list[dict[str, Any]] = field(default_factory=list)
    model_policy: dict[str, Any] = field(default_factory=dict)
    retries: int = 0
    flakiness_budget: dict[str, Any] = field(default_factory=dict)
    acceptance: dict[str, Any] = field(default_factory=dict)
    scene: str = "long_dialog_research"
    skill_hints: list[str] = field(default_factory=list)
    prompt_id: str | None = None
    prompt_version: str | None = None
    setup: list[dict[str, str]] = field(default_factory=list)
    judge: dict[str, Any] = field(default_factory=lambda: {"rule": True, "llm": {"enabled": False}})
    origin: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> EvalCase:
        return cls(
            id=str(raw["id"]),
            input=dict(raw.get("input") or {}),
            expected=dict(raw.get("expected") or {}),
            tags=list(raw.get("tags") or []),
            capability=_optional_str(raw.get("capability")),
            risk_level=_optional_str(raw.get("risk_level")),
            agent_topology=dict(raw.get("agent_topology") or {}),
            environment=dict(raw.get("environment") or {}),
            model_matrix=[
                dict(item) for item in list(raw.get("model_matrix") or []) if isinstance(item, dict)
            ],
            model_policy=dict(raw.get("model_policy") or {}),
            retries=max(0, int(raw.get("retries") or 0)),
            flakiness_budget=dict(raw.get("flakiness_budget") or {}),
            acceptance=dict(raw.get("acceptance") or {}),
            scene=str(raw.get("scene") or "long_dialog_research"),
            skill_hints=list(raw.get("skill_hints") or []),
            prompt_id=_prompt_id(raw),
            prompt_version=_prompt_version(raw),
            setup=list(raw.get("setup") or []),
            judge=dict(raw.get("judge") or {"rule": True, "llm": {"enabled": False}}),
            origin=raw.get("origin"),
        )

    def to_dict(self, *, include_empty: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "input": self.input,
            "expected": self.expected,
            "tags": list(self.tags),
            "scene": self.scene,
            "skill_hints": list(self.skill_hints),
            "prompt_id": self.prompt_id,
            "prompt_version": self.prompt_version,
            "setup": list(self.setup),
            "judge": self.judge,
            "origin": self.origin,
        }
        optional = {
            "capability": self.capability,
            "risk_level": self.risk_level,
            "agent_topology": self.agent_topology,
            "environment": self.environment,
            "model_matrix": self.model_matrix,
            "model_policy": self.model_policy,
            "retries": self.retries,
            "flakiness_budget": self.flakiness_budget,
            "acceptance": self.acceptance,
        }
        for key, value in optional.items():
            if include_empty or value not in (None, "", [], {}, 0):
                payload[key] = value
        return payload


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


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _prompt_id(raw: dict[str, Any]) -> str | None:
    prompt_id = _optional_str(raw.get("prompt_id"))
    if prompt_id and "@" in prompt_id and not raw.get("prompt_version"):
        prompt_id, _, _ = prompt_id.rpartition("@")
    return prompt_id


def _prompt_version(raw: dict[str, Any]) -> str | None:
    prompt_version = _optional_str(raw.get("prompt_version"))
    if prompt_version:
        return prompt_version
    prompt_id = _optional_str(raw.get("prompt_id"))
    if prompt_id and "@" in prompt_id:
        _, _, prompt_version = prompt_id.rpartition("@")
        return prompt_version or None
    return None
