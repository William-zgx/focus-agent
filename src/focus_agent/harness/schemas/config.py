from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RuntimeFeatures(BaseModel):
    """Declarative feature switches for the reusable harness runtime."""

    model_config = ConfigDict(extra="forbid")

    planning: bool = True
    memory: bool = True
    tool_router: bool = True
    guardrails: bool = False
    loop_detection: bool = True
    summarization: bool = True
    subagents: bool = False
    streaming: bool = True
    observability: bool = True


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


class SubagentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    max_concurrent_subagents: int = Field(default=3, ge=1)


class HarnessConfig(BaseModel):
    """Top-level harness configuration.

    This intentionally contains only reusable runtime policy.  App-specific
    auth, branch ownership, and storage wiring are injected separately.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="allow")

    name: str = "focus-agent"
    model: str | None = None
    features: RuntimeFeatures = Field(default_factory=RuntimeFeatures)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)
    streaming: StreamingConfig = Field(default_factory=StreamingConfig)
    subagents: SubagentConfig = Field(default_factory=SubagentConfig)
    middleware: tuple[object, ...] = ()
