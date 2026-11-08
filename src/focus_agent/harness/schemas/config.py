from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from focus_agent.config_parts.env import parse_bool

RuntimeFeatureSpec = bool | object


def _default_on_disconnect() -> Any:
    from ..runtime.runs import DisconnectMode

    return DisconnectMode.CANCEL


def _default_multitask_strategy() -> Any:
    from ..runtime.runs import MultitaskStrategy

    return MultitaskStrategy.REJECT


class RuntimeFeatures(BaseModel):
    """Declarative feature switches for the reusable harness runtime."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    memory: RuntimeFeatureSpec = True
    guardrails: bool = False
    loop_detection: bool = True
    summarization: bool = True
    streaming: RuntimeFeatureSpec = True
    observability: bool = True

    branching: RuntimeFeatureSpec = True
    governance: RuntimeFeatureSpec = True
    background_work: RuntimeFeatureSpec = True
    context_engineering_v2: RuntimeFeatureSpec = False
    custom: dict[str, RuntimeFeatureSpec] = Field(default_factory=dict)

    @field_validator("memory", "streaming", mode="before")
    @classmethod
    def _coerce_bool_strings(cls, value: Any) -> Any:
        if isinstance(value, str):
            parsed = parse_bool(value)
            if parsed is not None:
                return parsed
        return value

    @classmethod
    def from_settings(cls, settings: Any) -> RuntimeFeatures:
        """Build feature switches from a Focus Agent ``Settings``-like object."""

        return cls(
            memory=bool(getattr(settings, "agent_memory_backend", "")),
            branching=True,
            governance=True,
            streaming=True,
            background_work=True,
            context_engineering_v2=bool(
                getattr(settings, "agent_context_engineering_v2_enabled", False)
            ),
        )

    def enabled(self, name: str) -> bool:
        value = getattr(self, name, self.custom.get(name, False))
        return value is not False

    def implementation(self, name: str) -> object | None:
        value = getattr(self, name, self.custom.get(name, False))
        if isinstance(value, bool):
            return None
        return value


class RetryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_attempts: int = Field(default=3, ge=1, le=10)
    base_delay_ms: int = Field(default=500, ge=0)
    max_delay_ms: int = Field(default=8000, ge=0)


class CircuitBreakerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    failure_threshold: int = Field(default=5, ge=1)
    recovery_timeout_seconds: float = Field(default=30.0, ge=0.0)


class StreamingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    heartbeat_seconds: float = Field(default=1.5, ge=0.0)
    event_buffer_size: int = Field(default=1000, ge=1)
    cleanup_delay_seconds: float = Field(default=60.0, ge=0.0)


class HarnessConfig(BaseModel):
    """Top-level harness configuration.

    This intentionally contains only reusable runtime policy.  App-specific
    auth, branch ownership, and storage wiring are injected separately.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="allow")

    name: str = "focus-agent"
    model: str | None = None
    assistant_id: str = "focus_agent"
    default_model: str | None = None
    default_thinking_mode: str | None = None
    recursion_limit: int = 100
    stream_modes: tuple[str, ...] = ("messages", "custom", "updates", "tasks")
    stream_subgraphs: bool = False
    stream_queue_maxsize: int = 256
    heartbeat_seconds: float = 1.5
    run_retention_seconds: float = 300.0
    on_disconnect: Any = Field(default_factory=_default_on_disconnect)
    multitask_strategy: Any = Field(default_factory=_default_multitask_strategy)
    metadata: dict[str, Any] = Field(default_factory=dict)
    features: RuntimeFeatures = Field(default_factory=RuntimeFeatures)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)
    streaming: StreamingConfig = Field(default_factory=StreamingConfig)
    middleware: tuple[object, ...] = ()
    # Extension / governance / agent-definition toggles
    enable_extensions: bool = True
    extension_dirs: list[str] = Field(default_factory=list)
    enable_permission_system: bool = True
    doom_loop_threshold: int = Field(default=3, ge=1)
    agent_definition_dirs: list[str] = Field(default_factory=list)

    @classmethod
    def from_settings(cls, settings: Any) -> HarnessConfig:
        """Create harness defaults from a Focus Agent ``Settings``-like object."""

        from ..runtime.runs import DisconnectMode, MultitaskStrategy

        model = getattr(settings, "model", None)
        heartbeat_seconds = float(getattr(settings, "sse_heartbeat_seconds", 1.5))
        return cls(
            model=model,
            default_model=model,
            default_thinking_mode=getattr(settings, "selected_thinking_mode", None),
            heartbeat_seconds=heartbeat_seconds,
            stream_queue_maxsize=int(getattr(settings, "background_queue_max_size", 256)),
            streaming={"heartbeat_seconds": heartbeat_seconds},
            on_disconnect=DisconnectMode.CANCEL,
            multitask_strategy=MultitaskStrategy.REJECT,
            metadata={
                "app_version": getattr(settings, "app_version", None),
                "environment": getattr(settings, "app_environment", None),
                "deployment": getattr(settings, "deployment_name", None),
            },
            features=RuntimeFeatures.from_settings(settings),
        )

    def runnable_config(
        self,
        thread_id: str,
        *,
        overrides: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a LangGraph-style config dict for a thread run."""

        config: dict[str, Any] = {
            "recursion_limit": self.recursion_limit,
            "configurable": {"thread_id": thread_id},
        }
        if overrides:
            config.update(dict(overrides))
            configurable = config.setdefault("configurable", {})
            if isinstance(configurable, dict):
                configurable.setdefault("thread_id", thread_id)
        merged_metadata = {**self.metadata, **dict(metadata or {})}
        clean_metadata = {key: value for key, value in merged_metadata.items() if value is not None}
        if clean_metadata:
            config.setdefault("metadata", {}).update(clean_metadata)
        return config


__all__ = [
    "CircuitBreakerConfig",
    "HarnessConfig",
    "RetryConfig",
    "RuntimeFeatureSpec",
    "RuntimeFeatures",
    "StreamingConfig",
]
