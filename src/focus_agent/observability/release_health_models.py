"""Shared release-health data contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


PASS = "pass"
WARN = "warn"
FAIL = "fail"


@dataclass(frozen=True, slots=True)
class ReleaseHealthThresholds:
    chat_failure_rate: float = 0.05
    chat_failure_min_turns: int = 20
    fallback_rate: float = 0.25
    fallback_min_tool_calls: int = 20
    fallback_rate_growth: float = 0.15


@dataclass(frozen=True, slots=True)
class ReleaseHealthSignal:
    key: str
    status: str
    summary: str
    detail: str = ""
    value: float | None = None
    threshold: float | None = None
    labels: dict[str, str] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status != FAIL

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "status": self.status,
            "summary": self.summary,
            "detail": self.detail,
            "value": self.value,
            "threshold": self.threshold,
            "labels": dict(self.labels),
            "details": dict(self.details),
        }


@dataclass(frozen=True, slots=True)
class ReleaseHealthReport:
    signals: tuple[ReleaseHealthSignal, ...]

    @property
    def passed(self) -> bool:
        return all(signal.passed for signal in self.signals)

    @property
    def failed(self) -> tuple[ReleaseHealthSignal, ...]:
        return tuple(signal for signal in self.signals if signal.status == FAIL)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "signals": [signal.to_dict() for signal in self.signals],
        }
