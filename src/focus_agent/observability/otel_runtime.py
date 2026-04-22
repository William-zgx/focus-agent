from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Callable
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
    shutdown_callback: Callable[[], None] | None = None

    def shutdown(self) -> None:
        if callable(self.shutdown_callback):
            try:
                self.shutdown_callback()
            except Exception:  # noqa: BLE001
                logger.warning("failed to shut down OpenTelemetry runtime", exc_info=True)


def initialize_otel_runtime(settings: Settings) -> OTelRuntime:
    settings.otel_tracer_provider = None

    if not settings.tracing_enabled:
        return OTelRuntime(
            enabled=False,
            ready=True,
            exporter_names=(),
            detail="tracing disabled",
        )

    requested_exporters = _normalize_exporters(settings.otel_traces_exporters)
    if not requested_exporters:
        return OTelRuntime(
            enabled=True,
            ready=True,
            exporter_names=(),
            detail="tracing enabled without exporter",
        )

    try:
        from opentelemetry.sdk.resources import Resource  # type: ignore[import-not-found]
        from opentelemetry.sdk.trace import TracerProvider  # type: ignore[import-not-found]
        from opentelemetry.sdk.trace.export import (  # type: ignore[import-not-found]
            BatchSpanProcessor,
            ConsoleSpanExporter,
        )
    except Exception as exc:  # noqa: BLE001
        return OTelRuntime(
            enabled=True,
            ready=False,
            exporter_names=requested_exporters,
            detail=f"OpenTelemetry SDK unavailable: {exc}",
        )

    resource_attributes: dict[str, Any] = {
        "service.name": settings.tracing_service_name or "focus-agent",
        "service.version": settings.app_version,
        "deployment.environment.name": settings.app_environment,
    }
    if settings.deployment_name:
        resource_attributes["deployment.name"] = settings.deployment_name

    provider = TracerProvider(resource=Resource.create(resource_attributes))
    configured_exporters: list[str] = []
    failures: list[str] = []

    for exporter_name in requested_exporters:
        if exporter_name == "console":
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
            configured_exporters.append("console")
            continue

        if exporter_name != "otlp":
            failures.append(f"unsupported exporter '{exporter_name}'")
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
            failures.append(f"OTLP HTTP exporter unavailable: {exc}")
            continue

        endpoint = _resolve_otlp_traces_endpoint(settings)
        if not endpoint:
            failures.append("OTLP exporter requested but no OTLP endpoint configured")
            continue

        exporter = OTLPSpanExporter(
            endpoint=endpoint,
            headers=_parse_otlp_headers(settings.otel_exporter_otlp_headers),
            timeout=max(float(settings.otel_exporter_otlp_timeout_ms), 0.0) / 1000.0,
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))
        configured_exporters.append("otlp")

    settings.otel_tracer_provider = provider if configured_exporters else None

    if configured_exporters and not failures:
        return OTelRuntime(
            enabled=True,
            ready=True,
            exporter_names=tuple(configured_exporters),
            detail=f"exporting spans via {', '.join(configured_exporters)}",
            tracer_provider=provider,
            shutdown_callback=lambda: _shutdown_provider(settings, provider),
        )

    detail_parts = []
    if configured_exporters:
        detail_parts.append(f"configured {', '.join(configured_exporters)}")
    if failures:
        detail_parts.append("; ".join(failures))
    if not detail_parts:
        detail_parts.append("no exporters configured")
    return OTelRuntime(
        enabled=True,
        ready=False,
        exporter_names=tuple(configured_exporters or requested_exporters),
        detail="; ".join(detail_parts),
        tracer_provider=provider if configured_exporters else None,
        shutdown_callback=lambda: _shutdown_provider(settings, provider),
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


def _shutdown_provider(settings: Settings, provider: Any) -> None:
    try:
        shutdown = getattr(provider, "shutdown", None)
        if callable(shutdown):
            shutdown()
    finally:
        settings.otel_tracer_provider = None
