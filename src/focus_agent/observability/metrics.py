from __future__ import annotations

from collections.abc import Callable
from typing import Any

from focus_agent.runtime.thread_pool import tool_pool_active_workers, tool_pool_queue_size

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


def _observable_gauge(
    name: str,
    *,
    unit: str,
    description: str,
    callback: Callable[[], float | int],
) -> Any:
    meter = _meter()
    if meter is None or not hasattr(meter, "create_observable_gauge"):
        return _NoopMetric()

    def _observe(_options: Any) -> list[Any]:
        try:
            value = callback()
        except Exception:  # pragma: no cover - metrics must not affect runtime.
            value = 0
        observation = getattr(otel_metrics, "Observation", None)
        return [observation(value)] if observation is not None else [value]

    return meter.create_observable_gauge(
        name,
        callbacks=[_observe],
        unit=unit,
        description=description,
    )


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
TOOL_POOL_ACTIVE = _observable_gauge(
    "focus_agent.tool_pool.active",
    unit="worker",
    description="Active workers in the isolated tool thread pool.",
    callback=tool_pool_active_workers,
)
TOOL_POOL_QUEUE = _observable_gauge(
    "focus_agent.tool_pool.queue",
    unit="task",
    description="Queued tasks in the isolated tool thread pool.",
    callback=tool_pool_queue_size,
)


__all__ = [
    "ACTIVE_RUNS",
    "LLM_TOKENS",
    "MODEL_CHOICE",
    "RUN_STATUS",
    "TOOL_DURATION",
    "TOOL_POOL_ACTIVE",
    "TOOL_POOL_QUEUE",
    "TURN_DURATION",
]
