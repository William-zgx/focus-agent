from __future__ import annotations

from contextlib import AbstractContextManager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
from typing import Any
from uuid import uuid4

from ..config import Settings
from ..core.branching import BranchMeta


@dataclass(frozen=True, slots=True)
class TraceCorrelation:
    request_id: str | None
    trace_id: str
    root_span_id: str
    environment: str | None
    deployment: str | None
    app_version: str


@dataclass(frozen=True, slots=True)
class TraceSpanContext:
    trace_id: str
    span_id: str
    parent_span_id: str | None
    name: str
    attributes: dict[str, Any]

    def runtime_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
        }
        if self.parent_span_id:
            payload["parent_span_id"] = self.parent_span_id
        return payload


_CURRENT_CORRELATION: ContextVar[TraceCorrelation | None] = ContextVar(
    "focus_agent_trace_correlation",
    default=None,
)
_CURRENT_SPAN: ContextVar[TraceSpanContext | None] = ContextVar(
    "focus_agent_trace_span",
    default=None,
)
_TRACING_ENABLED: ContextVar[bool] = ContextVar("focus_agent_tracing_enabled", default=False)
_TRACING_SERVICE_NAME: ContextVar[str] = ContextVar("focus_agent_tracing_service_name", default="focus-agent")
_OTEL_TRACER_PROVIDER: ContextVar[Any | None] = ContextVar("focus_agent_otel_tracer_provider", default=None)


def build_trace_correlation(
    *,
    settings: Settings,
    request_id: str | None = None,
    trace_id: str | None = None,
    root_span_id: str | None = None,
) -> TraceCorrelation:
    normalized_request_id = _normalize_optional_string(request_id)
    seed = normalized_request_id or uuid4().hex
    return TraceCorrelation(
        request_id=normalized_request_id,
        trace_id=_normalize_hex_identifier(trace_id, hex_chars=32, fallback_seed=f"{seed}:trace"),
        root_span_id=_normalize_hex_identifier(
            root_span_id,
            hex_chars=16,
            fallback_seed=f"{seed}:root-span",
        ),
        environment=_normalize_optional_string(getattr(settings, "app_environment", None)),
        deployment=_normalize_optional_string(getattr(settings, "deployment_name", None)),
        app_version=str(getattr(settings, "app_version", "")),
    )


class TraceSpanScope(AbstractContextManager["TraceSpanScope"]):
    """Small tracing facade that works without an OpenTelemetry dependency."""

    def __init__(
        self,
        *,
        name: str,
        correlation: TraceCorrelation | None,
        enabled: bool,
        service_name: str,
        otel_tracer_provider: Any | None = None,
        attributes: dict[str, Any] | None = None,
        span_id: str | None = None,
        parent_span_id: str | None = None,
    ) -> None:
        self.name = name
        self.correlation = correlation or _CURRENT_CORRELATION.get()
        self.enabled = bool(enabled and self.correlation is not None)
        self.service_name = _normalize_optional_string(service_name) or "focus-agent"
        self.otel_tracer_provider = otel_tracer_provider if otel_tracer_provider is not None else _OTEL_TRACER_PROVIDER.get()
        self.span: TraceSpanContext | None = None
        self._attributes = dict(attributes or {})
        self._span_id = span_id
        self._parent_span_id = parent_span_id
        self._correlation_token = None
        self._span_token = None
        self._enabled_token = None
        self._service_name_token = None
        self._otel_provider_token = None
        self._otel_scope: Any = None
        self._otel_span: Any = None

    def __enter__(self) -> TraceSpanScope:
        self._enabled_token = _TRACING_ENABLED.set(self.enabled)
        self._service_name_token = _TRACING_SERVICE_NAME.set(self.service_name)
        if self.otel_tracer_provider is not None:
            self._otel_provider_token = _OTEL_TRACER_PROVIDER.set(self.otel_tracer_provider)
        if self.correlation is not None:
            self._correlation_token = _CURRENT_CORRELATION.set(self.correlation)
        if self.enabled and self.correlation is not None:
            parent_span = _CURRENT_SPAN.get()
            parent_span_id = self._parent_span_id
            if parent_span_id is None and parent_span is not None:
                parent_span_id = parent_span.span_id
            span_id = self._span_id or _new_span_id()
            attributes = {
                **self.correlation_attributes(self.correlation, service_name=self.service_name),
                **self._attributes,
            }
            self.span = TraceSpanContext(
                trace_id=self.correlation.trace_id,
                span_id=span_id,
                parent_span_id=parent_span_id,
                name=self.name,
                attributes=attributes,
            )
            self._span_token = _CURRENT_SPAN.set(self.span)
            self._start_otel_span()
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool | None:
        if exc is not None:
            self.record_exception(exc)
            self.set_attribute("otel.status_code", "ERROR")
        elif self.enabled:
            self.set_attribute("otel.status_code", "OK")
        if self._otel_scope is not None:
            self._otel_scope.__exit__(exc_type, exc, traceback)
        if self._span_token is not None:
            _CURRENT_SPAN.reset(self._span_token)
        if self._correlation_token is not None:
            _CURRENT_CORRELATION.reset(self._correlation_token)
        if self._enabled_token is not None:
            _TRACING_ENABLED.reset(self._enabled_token)
        if self._service_name_token is not None:
            _TRACING_SERVICE_NAME.reset(self._service_name_token)
        if self._otel_provider_token is not None:
            _OTEL_TRACER_PROVIDER.reset(self._otel_provider_token)
        return None

    def set_attribute(self, key: str, value: Any) -> None:
        if self.span is not None:
            self.span.attributes[key] = value
        if self._otel_span is not None:
            with _suppress_otel_errors():
                self._otel_span.set_attribute(key, value)

    def record_exception(self, exc: BaseException) -> None:
        if self._otel_span is not None:
            with _suppress_otel_errors():
                self._otel_span.record_exception(exc)

    def runtime_payload(self) -> dict[str, Any]:
        return self.span.runtime_payload() if self.span is not None else {}

    @staticmethod
    def correlation_attributes(correlation: TraceCorrelation, *, service_name: str = "focus-agent") -> dict[str, Any]:
        attributes: dict[str, Any] = {
            "service.name": _normalize_optional_string(service_name) or "focus-agent",
            "focus_agent.trace_id": correlation.trace_id,
            "focus_agent.root_span_id": correlation.root_span_id,
            "focus_agent.app_version": correlation.app_version,
        }
        if correlation.request_id:
            attributes["focus_agent.request_id"] = correlation.request_id
        if correlation.environment:
            attributes["deployment.environment"] = correlation.environment
        if correlation.deployment:
            attributes["deployment.name"] = correlation.deployment
        return attributes

    def _start_otel_span(self) -> None:
        if self.span is None:
            return
        try:
            provider = self.otel_tracer_provider
            if provider is not None:
                tracer = provider.get_tracer("focus_agent")
            else:
                from opentelemetry import trace as otel_trace  # type: ignore[import-not-found]

                tracer = otel_trace.get_tracer("focus_agent")
            self._otel_scope = tracer.start_as_current_span(
                self.name,
                attributes=self.span.attributes,
            )
            self._otel_span = self._otel_scope.__enter__()
        except Exception:  # noqa: BLE001
            self._otel_scope = None
            self._otel_span = None


def start_trace_span(
    *,
    name: str,
    settings: Settings | None = None,
    trace_correlation: TraceCorrelation | None = None,
    attributes: dict[str, Any] | None = None,
    span_id: str | None = None,
    parent_span_id: str | None = None,
) -> TraceSpanScope:
    enabled = bool(getattr(settings, "tracing_enabled", _TRACING_ENABLED.get()))
    service_name = (
        getattr(settings, "tracing_service_name", None)
        if settings is not None
        else _TRACING_SERVICE_NAME.get()
    )
    otel_tracer_provider = (
        getattr(settings, "otel_tracer_provider", None)
        if settings is not None
        else _OTEL_TRACER_PROVIDER.get()
    )
    return TraceSpanScope(
        name=name,
        correlation=trace_correlation,
        enabled=enabled,
        service_name=_normalize_optional_string(service_name) or "focus-agent",
        otel_tracer_provider=otel_tracer_provider,
        attributes=attributes,
        span_id=span_id,
        parent_span_id=parent_span_id,
    )


def current_trace_runtime_payload() -> dict[str, Any]:
    if not _TRACING_ENABLED.get():
        return {}
    span = _CURRENT_SPAN.get()
    return span.runtime_payload() if span is not None else {}


def build_trace_metadata(
    *,
    settings: Settings,
    thread_id: str,
    user_id: str,
    root_thread_id: str,
    branch_meta: BranchMeta | None = None,
    trace_correlation: TraceCorrelation | None = None,
    scene: str = "long_dialog_research",
) -> dict[str, Any]:
    correlation = trace_correlation or build_trace_correlation(settings=settings)
    metadata: dict[str, Any] = {
        "thread_id": thread_id,
        "root_thread_id": root_thread_id,
        "scene": scene,
        "user_id": user_id,
        "app_version": correlation.app_version,
        "trace_id": correlation.trace_id,
        "root_span_id": correlation.root_span_id,
    }
    if correlation.request_id:
        metadata["request_id"] = correlation.request_id
    if correlation.environment:
        metadata["environment"] = correlation.environment
    if correlation.deployment:
        metadata["deployment"] = correlation.deployment
    if branch_meta is not None:
        metadata.update(
            {
                "parent_thread_id": branch_meta.parent_thread_id,
                "branch_id": branch_meta.branch_id,
                "branch_depth": branch_meta.branch_depth,
                "branch_status": branch_meta.branch_status.value,
                "branch_role": branch_meta.branch_role.value,
            }
        )
    return metadata


def build_trace_tags(*, root_thread_id: str, thread_id: str, branch_meta: BranchMeta | None = None) -> list[str]:
    tags = [
        "focus-agent",
        "long-dialogue",
        "research",
        f"root:{root_thread_id}",
        f"thread:{thread_id}",
    ]
    if branch_meta is not None:
        tags.extend(
            [
                "branch",
                f"branch:{branch_meta.branch_id}",
                f"status:{branch_meta.branch_status.value}",
            ]
        )
    else:
        tags.append("main")
    return tags


def build_invoke_config(
    *,
    settings: Settings,
    thread_id: str,
    user_id: str,
    root_thread_id: str,
    branch_meta: BranchMeta | None = None,
    trace_correlation: TraceCorrelation | None = None,
    run_name: str = "focus_agent_turn",
    scene: str = "long_dialog_research",
) -> dict[str, Any]:
    return {
        "run_name": run_name,
        "configurable": {"thread_id": thread_id},
        "metadata": build_trace_metadata(
            settings=settings,
            thread_id=thread_id,
            user_id=user_id,
            root_thread_id=root_thread_id,
            branch_meta=branch_meta,
            trace_correlation=trace_correlation,
            scene=scene,
        ),
        "tags": build_trace_tags(root_thread_id=root_thread_id, thread_id=thread_id, branch_meta=branch_meta),
    }


def _normalize_optional_string(value: str | None) -> str | None:
    text = str(value or "").strip()
    return text or None


def _normalize_hex_identifier(value: str | None, *, hex_chars: int, fallback_seed: str) -> str:
    candidate = "".join(ch for ch in str(value or "").strip().lower() if ch in "0123456789abcdef")
    if len(candidate) >= hex_chars:
        return candidate[:hex_chars]
    return hashlib.sha256(fallback_seed.encode("utf-8")).hexdigest()[:hex_chars]


def _new_span_id() -> str:
    return uuid4().hex[:16]


class _suppress_otel_errors(AbstractContextManager[None]):
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc, traceback) -> bool:
        return exc is not None
