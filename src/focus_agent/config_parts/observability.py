from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

from .common import _coerce_bool, _split_csv


def load_observability_config(
    env: MutableMapping[str, str],
    defaults: Any,
) -> dict[str, object]:
    otel_traces_exporters = (
        _split_csv(env.get("OTEL_TRACES_EXPORTER"))
        if env.get("OTEL_TRACES_EXPORTER") is not None
        else (
            ("otlp",)
            if (
                env.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
                or env.get("OTEL_EXPORTER_OTLP_ENDPOINT")
            )
            else defaults.otel_traces_exporters
        )
    )
    return {
        "langsmith_project": env.get("LANGSMITH_PROJECT", defaults.langsmith_project),
        "tracing_enabled": (
            _coerce_bool(env.get("FOCUS_AGENT_TRACING_ENABLED"))
            if env.get("FOCUS_AGENT_TRACING_ENABLED") is not None
            else _coerce_bool(env.get("OTEL_TRACING_ENABLED")) or defaults.tracing_enabled
        ),
        "tracing_service_name": (
            env.get("OTEL_SERVICE_NAME")
            or env.get("FOCUS_AGENT_TRACING_SERVICE_NAME")
            or defaults.tracing_service_name
        ),
        "otel_traces_exporters": otel_traces_exporters,
        "otel_exporter_otlp_endpoint": env.get("OTEL_EXPORTER_OTLP_ENDPOINT") or None,
        "otel_exporter_otlp_traces_endpoint": (
            env.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or None
        ),
        "otel_exporter_otlp_headers": (
            env.get("OTEL_EXPORTER_OTLP_TRACES_HEADERS")
            or env.get("OTEL_EXPORTER_OTLP_HEADERS")
            or None
        ),
        "otel_exporter_otlp_protocol": (
            env.get("OTEL_EXPORTER_OTLP_TRACES_PROTOCOL")
            or env.get("OTEL_EXPORTER_OTLP_PROTOCOL")
            or defaults.otel_exporter_otlp_protocol
        ),
        "otel_exporter_otlp_timeout_ms": int(
            env.get(
                "OTEL_EXPORTER_OTLP_TRACES_TIMEOUT",
                env.get(
                    "OTEL_EXPORTER_OTLP_TIMEOUT",
                    str(defaults.otel_exporter_otlp_timeout_ms),
                ),
            )
        ),
    }
