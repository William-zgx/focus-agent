from __future__ import annotations

from types import ModuleType
from typing import Any
import sys

from focus_agent.config import Settings
from focus_agent.observability.otel_runtime import initialize_otel_runtime


def _install_fake_otel(monkeypatch, capture: dict[str, Any]) -> None:
    opentelemetry_sdk_resources = ModuleType("opentelemetry.sdk.resources")
    opentelemetry_sdk_trace = ModuleType("opentelemetry.sdk.trace")
    opentelemetry_sdk_trace_export = ModuleType("opentelemetry.sdk.trace.export")
    opentelemetry_exporter_http = ModuleType("opentelemetry.exporter.otlp.proto.http.trace_exporter")

    class FakeResource:
        @staticmethod
        def create(attributes):
            capture["resource_attributes"] = dict(attributes)
            return dict(attributes)

    class FakeTracerProvider:
        def __init__(self, *, resource=None):
            capture["provider_resource"] = resource
            self._processors = []

        def add_span_processor(self, processor):
            self._processors.append(processor)
            capture.setdefault("processors", []).append(processor)

        def shutdown(self):
            capture["shutdown_called"] = True

    class FakeBatchSpanProcessor:
        def __init__(self, exporter):
            self.exporter = exporter

    class FakeConsoleSpanExporter:
        def __init__(self):
            capture["console_exporter_created"] = True

    class FakeOTLPSpanExporter:
        def __init__(self, **kwargs):
            capture["otlp_kwargs"] = dict(kwargs)

    opentelemetry_sdk_resources.Resource = FakeResource
    opentelemetry_sdk_trace.TracerProvider = FakeTracerProvider
    opentelemetry_sdk_trace_export.BatchSpanProcessor = FakeBatchSpanProcessor
    opentelemetry_sdk_trace_export.ConsoleSpanExporter = FakeConsoleSpanExporter
    opentelemetry_exporter_http.OTLPSpanExporter = FakeOTLPSpanExporter

    monkeypatch.setitem(sys.modules, "opentelemetry.sdk.resources", opentelemetry_sdk_resources)
    monkeypatch.setitem(sys.modules, "opentelemetry.sdk.trace", opentelemetry_sdk_trace)
    monkeypatch.setitem(sys.modules, "opentelemetry.sdk.trace.export", opentelemetry_sdk_trace_export)
    monkeypatch.setitem(
        sys.modules,
        "opentelemetry.exporter.otlp.proto.http.trace_exporter",
        opentelemetry_exporter_http,
    )


def test_initialize_otel_runtime_configures_console_and_otlp(monkeypatch) -> None:
    capture: dict[str, Any] = {}
    _install_fake_otel(monkeypatch, capture)
    settings = Settings(
        tracing_enabled=True,
        tracing_service_name="focus-agent-test",
        app_version="2.0.0",
        app_environment="staging",
        deployment_name="focus-agent-blue",
        otel_traces_exporters=("console", "otlp"),
        otel_exporter_otlp_endpoint="http://collector:4318",
        otel_exporter_otlp_headers="authorization=Bearer test,x-env=staging",
        otel_exporter_otlp_timeout_ms=2500,
    )

    runtime = initialize_otel_runtime(settings)

    assert runtime.ready is True
    assert runtime.exporter_names == ("console", "otlp")
    assert settings.otel_tracer_provider is not None
    assert capture["resource_attributes"]["service.name"] == "focus-agent-test"
    assert capture["resource_attributes"]["service.version"] == "2.0.0"
    assert capture["resource_attributes"]["deployment.environment.name"] == "staging"
    assert capture["resource_attributes"]["deployment.name"] == "focus-agent-blue"
    assert capture["otlp_kwargs"]["endpoint"] == "http://collector:4318/v1/traces"
    assert capture["otlp_kwargs"]["headers"] == {
        "authorization": "Bearer test",
        "x-env": "staging",
    }
    assert capture["otlp_kwargs"]["timeout"] == 2.5

    runtime.shutdown()

    assert capture["shutdown_called"] is True
    assert settings.otel_tracer_provider is None
