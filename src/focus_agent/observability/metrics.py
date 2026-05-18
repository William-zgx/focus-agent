from __future__ import annotations

from typing import Any

try:
    from opentelemetry import metrics as otel_metrics  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - optional exporter dependency.
    otel_metrics = None  # type: ignore[assignment]


class _NoopMetric:
    def record(self, value: float | int, attributes: dict[str, Any] | None = None) -> None:
        return None

    def add(self, value: float | int, attributes: dict[str, Any] | None = None) -> None:
        return None


def _meter() -> Any:
    if otel_metrics is None:
        return None
    return otel_metrics.get_meter("focus_agent")


def _histogram(name: str, *, unit: str, description: str) -> Any:
    meter = _meter()
    if meter is None:
        return _NoopMetric()
    return meter.create_histogram(name, unit=unit, description=description)


def _counter(name: str, *, description: str) -> Any:
    meter = _meter()
    if meter is None:
        return _NoopMetric()
    return meter.create_counter(name, description=description)


def _up_down_counter(name: str, *, description: str) -> Any:
    meter = _meter()
    if meter is None:
        return _NoopMetric()
    return meter.create_up_down_counter(name, description=description)


TURN_DURATION = _histogram(
    "focus_agent.turn.duration_ms",
    unit="ms",
    description="End-to-end turn duration.",
)
TOOL_DURATION = _histogram(
    "focus_agent.tool.duration_ms",
    unit="ms",
    description="Tool execution duration.",
)
RUN_STATUS = _counter(
    "focus_agent.run.status",
    description="Run terminal status counter.",
)
LLM_TOKENS = _histogram(
    "focus_agent.llm.tokens",
    unit="token",
    description="LLM input/output tokens labelled by direction.",
)
ACTIVE_RUNS = _up_down_counter(
    "focus_agent.runs.active",
    description="In-flight runs gauge.",
)
MODEL_CHOICE = _counter(
    "focus_agent.model.choice",
    description="Model router choice counter.",
)


__all__ = [
    "ACTIVE_RUNS",
    "LLM_TOKENS",
    "MODEL_CHOICE",
    "RUN_STATUS",
    "TOOL_DURATION",
    "TURN_DURATION",
]
