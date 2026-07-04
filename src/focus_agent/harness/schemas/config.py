from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

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

    planning: bool = True
    memory: RuntimeFeatureSpec = True
    tool_router: bool = True
    guardrails: bool = False
    loop_detection: bool = True
    summarization: bool = True
    subagents: bool = False
    streaming: RuntimeFeatureSpec = True
    observability: bool = True

    branching: RuntimeFeatureSpec = True
    plan_act_reflect: RuntimeFeatureSpec = True
    governance: RuntimeFeatureSpec = True
    background_work: RuntimeFeatureSpec = True
    role_routing: RuntimeFeatureSpec = False
    tool_routing: RuntimeFeatureSpec = False
    delegation: RuntimeFeatureSpec = False
    model_routing: RuntimeFeatureSpec = False
    context_engineering_v2: RuntimeFeatureSpec = False
    task_ledger: RuntimeFeatureSpec = False
    artifact_synthesis: RuntimeFeatureSpec = False
    critic_gate: RuntimeFeatureSpec = False
    custom: dict[str, RuntimeFeatureSpec] = Field(default_factory=dict)

    @field_validator("memory", "streaming", mode="before")
    @classmethod
    def _coerce_bool_strings(cls, value: Any) -> Any:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
        return value

    @classmethod
    def from_settings(cls, settings: Any) -> RuntimeFeatures:
        """Build feature switches from a Focus Agent ``Settings``-like object."""

        delegation = bool(getattr(settings, "agent_delegation_enabled", False))
        tool_routing = bool(getattr(settings, "agent_tool_router_enabled", False))
        return cls(
            memory=bool(getattr(settings, "agent_memory_backend", "")),
            tool_router=tool_routing,
            subagents=delegation,
            branching=True,
            plan_act_reflect=bool(getattr(settings, "plan_act_reflect_enabled", True)),
            governance=True,
            streaming=True,
            background_work=True,
            role_routing=bool(getattr(settings, "agent_role_routing_enabled", False)),
            tool_routing=tool_routing,
            delegation=delegation,
            model_routing=bool(getattr(settings, "agent_model_router_enabled", False)),
            context_engineering_v2=bool(
                getattr(settings, "agent_context_engineering_v2_enabled", False)
            ),
            task_ledger=bool(getattr(settings, "agent_task_ledger_enabled", False)),
            artifact_synthesis=bool(getattr(settings, "agent_artifact_synthesis_enabled", False)),
            critic_gate=bool(getattr(settings, "agent_critic_gate_enabled", False)),
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


class SubagentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    max_concurrent_subagents: int = Field(default=3, ge=1)
    # When True, subagent tasks execute in isolated OS processes via the
    # focus-agent CLI (ProcessSubagentRunner) instead of in-process via
    # AgentTeamSubagentRunner. Defaults to False for backward compatibility.
    use_process_isolation: bool = False
    cli_entry_point: str = "focus-agent"
    process_timeout_seconds: float = Field(default=300.0, ge=1.0)
    graceful_shutdown_seconds: float = Field(default=5.0, ge=0.0)


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
    subagents: SubagentConfig = Field(default_factory=SubagentConfig)
    middleware: tuple[object, ...] = ()
    # Extension / governance / agent-definition toggles
    enable_extensions: bool = True
    extension_dirs: list[str] = Field(default_factory=list)
    enable_permission_system: bool = True
    doom_loop_threshold: int = Field(default=3, ge=1)
    enable_system_agents: bool = True
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
    "SubagentConfig",
]
