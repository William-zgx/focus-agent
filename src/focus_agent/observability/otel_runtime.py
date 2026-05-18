from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse, urlunparse

from ..config import Settings

logger = logging.getLogger("focus_agent.observability.otel")


@dataclass(slots=True)
class OTelRuntime:
    enabled: bool
    ready: bool
    exporter_names: tuple[str, ...]
    detail: str
    tracer_provider: Any | None = None
    metric_exporter_names: tuple[str, ...] = ()
    meter_provider: Any | None = None
    shutdown_callback: Callable[[], None] | None = None

    def shutdown(self) -> None:
        if callable(self.shutdown_callback):
            try:
                self.shutdown_callback()
            except Exception:  # noqa: BLE001
                logger.warning("failed to shut down OpenTelemetry runtime", exc_info=True)


def initialize_otel_runtime(settings: Settings) -> OTelRuntime:
    settings.otel_tracer_provider = None
    settings.otel_meter_provider = None

    requested_trace_exporters = (
        _normalize_exporters(settings.otel_traces_exporters) if settings.tracing_enabled else ()
    )
    requested_metric_exporters = _normalize_exporters(
        getattr(settings, "otel_metrics_exporters", ()) or ()
    )
    if not requested_trace_exporters and not requested_metric_exporters:
        return OTelRuntime(
            enabled=bool(settings.tracing_enabled or requested_metric_exporters),
            ready=True,
            exporter_names=(),
            metric_exporter_names=(),
            detail="observability exporters disabled",
        )

    try:
        from opentelemetry.sdk.resources import Resource  # type: ignore[import-not-found]
    except Exception as exc:  # noqa: BLE001
        return OTelRuntime(
            enabled=True,
            ready=False,
            exporter_names=requested_trace_exporters,
            metric_exporter_names=requested_metric_exporters,
            detail=f"OpenTelemetry SDK unavailable: {exc}",
        )

    resource_attributes = _resource_attributes(settings)
    provider: Any | None = None
    meter_provider: Any | None = None
    configured_trace_exporters: list[str] = []
    configured_metric_exporters: list[str] = []
    failures: list[str] = []

    if requested_trace_exporters:
        try:
            from opentelemetry.sdk.trace import TracerProvider  # type: ignore[import-not-found]
            from opentelemetry.sdk.trace.export import (  # type: ignore[import-not-found]
                BatchSpanProcessor,
                ConsoleSpanExporter,
            )
        except Exception as exc:  # noqa: BLE001
            failures.append(f"OpenTelemetry trace SDK unavailable: {exc}")
        else:
            provider = TracerProvider(resource=Resource.create(resource_attributes))
            for exporter_name in requested_trace_exporters:
                if exporter_name == "console":
                    provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
                    configured_trace_exporters.append("console")
                    continue

                if exporter_name != "otlp":
                    failures.append(f"unsupported trace exporter '{exporter_name}'")
                    continue

                protocol = (settings.otel_exporter_otlp_protocol or "http/protobuf").strip().lower()
                if protocol != "http/protobuf":
                    failures.append(f"unsupported OTLP protocol '{protocol}'")
                    continue

                try:
                    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # type: ignore[import-not-found]
                        OTLPSpanExporter,
                    )
                except Exception as exc:  # noqa: BLE001
                    failures.append(f"OTLP HTTP trace exporter unavailable: {exc}")
                    continue

                endpoint = _resolve_otlp_traces_endpoint(settings)
                if not endpoint:
                    failures.append("OTLP trace exporter requested but no OTLP endpoint configured")
                    continue

                exporter = OTLPSpanExporter(
                    endpoint=endpoint,
                    headers=_parse_otlp_headers(settings.otel_exporter_otlp_headers),
                    timeout=max(float(settings.otel_exporter_otlp_timeout_ms), 0.0) / 1000.0,
                )
                provider.add_span_processor(BatchSpanProcessor(exporter))
                configured_trace_exporters.append("otlp")

    if requested_metric_exporters:
        try:
            from opentelemetry.sdk.metrics import MeterProvider  # type: ignore[import-not-found]
            from opentelemetry.sdk.metrics.export import (  # type: ignore[import-not-found]
                ConsoleMetricExporter,
                PeriodicExportingMetricReader,
            )
        except Exception as exc:  # noqa: BLE001
            failures.append(f"OpenTelemetry metrics SDK unavailable: {exc}")
        else:
            metric_readers = []
            for exporter_name in requested_metric_exporters:
                if exporter_name == "console":
                    metric_readers.append(PeriodicExportingMetricReader(ConsoleMetricExporter()))
                    configured_metric_exporters.append("console")
                    continue

                if exporter_name != "otlp":
                    failures.append(f"unsupported metric exporter '{exporter_name}'")
                    continue

                protocol = (settings.otel_exporter_otlp_protocol or "http/protobuf").strip().lower()
                if protocol != "http/protobuf":
                    failures.append(f"unsupported OTLP protocol '{protocol}'")
                    continue

                try:
                    from opentelemetry.exporter.otlp.proto.http.metric_exporter import (  # type: ignore[import-not-found]
                        OTLPMetricExporter,
                    )
                except Exception as exc:  # noqa: BLE001
                    failures.append(f"OTLP HTTP metric exporter unavailable: {exc}")
                    continue

                endpoint = _resolve_otlp_metrics_endpoint(settings)
                if not endpoint:
                    failures.append(
                        "OTLP metric exporter requested but no OTLP endpoint configured"
                    )
                    continue

                metric_readers.append(
                    PeriodicExportingMetricReader(
                        OTLPMetricExporter(
                            endpoint=endpoint,
                            headers=_parse_otlp_headers(settings.otel_exporter_otlp_headers),
                            timeout=max(float(settings.otel_exporter_otlp_timeout_ms), 0.0)
                            / 1000.0,
                        )
                    )
                )
                configured_metric_exporters.append("otlp")
            if metric_readers:
                meter_provider = MeterProvider(
                    resource=Resource.create(resource_attributes),
                    metric_readers=metric_readers,
                )

    settings.otel_tracer_provider = provider if configured_trace_exporters else None
    settings.otel_meter_provider = meter_provider if configured_metric_exporters else None

    if (configured_trace_exporters or configured_metric_exporters) and not failures:
        return OTelRuntime(
            enabled=True,
            ready=True,
            exporter_names=tuple(configured_trace_exporters),
            metric_exporter_names=tuple(configured_metric_exporters),
            detail=_success_detail(configured_trace_exporters, configured_metric_exporters),
            tracer_provider=settings.otel_tracer_provider,
            meter_provider=meter_provider,
            shutdown_callback=lambda: _shutdown_providers(settings, provider, meter_provider),
        )

    detail_parts = []
    if configured_trace_exporters:
        detail_parts.append(f"configured trace exporters {', '.join(configured_trace_exporters)}")
    if configured_metric_exporters:
        detail_parts.append(f"configured metric exporters {', '.join(configured_metric_exporters)}")
    if failures:
        detail_parts.append("; ".join(failures))
    if not detail_parts:
        detail_parts.append("no exporters configured")
    return OTelRuntime(
        enabled=True,
        ready=False,
        exporter_names=tuple(configured_trace_exporters or requested_trace_exporters),
        metric_exporter_names=tuple(configured_metric_exporters or requested_metric_exporters),
        detail="; ".join(detail_parts),
        tracer_provider=settings.otel_tracer_provider,
        meter_provider=meter_provider,
        shutdown_callback=lambda: _shutdown_providers(settings, provider, meter_provider),
    )


def _normalize_exporters(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    for raw_value in values:
        value = str(raw_value or "").strip().lower()
        if not value or value == "none":
            continue
        normalized.append(value)
    return tuple(dict.fromkeys(normalized))


def _resolve_otlp_traces_endpoint(settings: Settings) -> str | None:
    explicit = str(settings.otel_exporter_otlp_traces_endpoint or "").strip()
    if explicit:
        return explicit

    base = str(settings.otel_exporter_otlp_endpoint or "").strip()
    if not base:
        return None

    parsed = urlparse(base)
    if not parsed.path or parsed.path == "/":
        return urlunparse(parsed._replace(path="/v1/traces"))
    return base


def _resolve_otlp_metrics_endpoint(settings: Settings) -> str | None:
    explicit = str(getattr(settings, "otel_exporter_otlp_metrics_endpoint", None) or "").strip()
    if explicit:
        return explicit

    base = str(settings.otel_exporter_otlp_endpoint or "").strip()
    if not base:
        return None

    parsed = urlparse(base)
    if not parsed.path or parsed.path == "/":
        return urlunparse(parsed._replace(path="/v1/metrics"))
    return base


def _parse_otlp_headers(raw_headers: str | None) -> dict[str, str] | None:
    text = str(raw_headers or "").strip()
    if not text:
        return None

    parsed: dict[str, str] = {}
    for item in text.split(","):
        key, separator, value = item.partition("=")
        if not separator:
            continue
        normalized_key = key.strip()
        normalized_value = value.strip()
        if normalized_key and normalized_value:
            parsed[normalized_key] = normalized_value
    return parsed or None


def _resource_attributes(settings: Settings) -> dict[str, Any]:
    resource_attributes: dict[str, Any] = {
        "service.name": settings.tracing_service_name or "focus-agent",
        "service.version": settings.app_version,
        "deployment.environment.name": settings.app_environment,
    }
    if settings.deployment_name:
        resource_attributes["deployment.name"] = settings.deployment_name
    return resource_attributes


def _success_detail(trace_exporters: list[str], metric_exporters: list[str]) -> str:
    parts: list[str] = []
    if trace_exporters:
        parts.append(f"exporting spans via {', '.join(trace_exporters)}")
    if metric_exporters:
        parts.append(f"exporting metrics via {', '.join(metric_exporters)}")
    return "; ".join(parts) if parts else "observability exporters disabled"


def _shutdown_providers(
    settings: Settings,
    tracer_provider: Any | None,
    meter_provider: Any | None,
) -> None:
    try:
        for provider in (tracer_provider, meter_provider):
            shutdown = getattr(provider, "shutdown", None)
            if callable(shutdown):
                shutdown()
    finally:
        settings.otel_tracer_provider = None
        settings.otel_meter_provider = None
