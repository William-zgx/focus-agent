from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .runs import DisconnectMode, MultitaskStrategy

RuntimeFeatureSpec = bool | object


@dataclass(slots=True)
class RuntimeFeatures:
    """Declarative feature switches for an embeddable harness runtime.

    Focus Agent's core runtime is graph-first rather than middleware-first, so
    feature values are deliberately plain: ``True`` uses the built-in behavior,
    ``False`` disables the behavior, and any other object is treated as a
    caller-provided implementation for future assembly code.
    """

    memory: RuntimeFeatureSpec = True
    branching: RuntimeFeatureSpec = True
    plan_act_reflect: RuntimeFeatureSpec = True
    governance: RuntimeFeatureSpec = True
    streaming: RuntimeFeatureSpec = True
    background_work: RuntimeFeatureSpec = True
    role_routing: RuntimeFeatureSpec = False
    tool_routing: RuntimeFeatureSpec = False
    delegation: RuntimeFeatureSpec = False
    model_routing: RuntimeFeatureSpec = False
    context_engineering_v2: RuntimeFeatureSpec = False
    task_ledger: RuntimeFeatureSpec = False
    artifact_synthesis: RuntimeFeatureSpec = False
    critic_gate: RuntimeFeatureSpec = False
    custom: dict[str, RuntimeFeatureSpec] = field(default_factory=dict)

    @classmethod
    def from_settings(cls, settings: Any) -> "RuntimeFeatures":
        """Build feature switches from a Focus Agent ``Settings``-like object."""

        return cls(
            memory=bool(getattr(settings, "agent_memory_backend", "")),
            branching=True,
            plan_act_reflect=bool(getattr(settings, "plan_act_reflect_enabled", True)),
            governance=True,
            streaming=True,
            background_work=True,
            role_routing=bool(getattr(settings, "agent_role_routing_enabled", False)),
            tool_routing=bool(getattr(settings, "agent_tool_router_enabled", False)),
            delegation=bool(getattr(settings, "agent_delegation_enabled", False)),
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


@dataclass(slots=True)
class HarnessConfig:
    """Runtime defaults for harness consumers.

    This object is intentionally separate from the process-wide ``Settings`` so
    embedded callers can construct a small runtime surface without loading env
    files or API configuration.
    """

    assistant_id: str = "focus_agent"
    default_model: str | None = None
    default_thinking_mode: str | None = None
    recursion_limit: int = 100
    stream_modes: tuple[str, ...] = ("messages", "custom", "updates", "tasks")
    stream_subgraphs: bool = False
    stream_queue_maxsize: int = 256
    heartbeat_seconds: float = 1.5
    run_retention_seconds: float = 300.0
    on_disconnect: DisconnectMode = DisconnectMode.CANCEL
    multitask_strategy: MultitaskStrategy = MultitaskStrategy.REJECT
    metadata: dict[str, Any] = field(default_factory=dict)
    features: RuntimeFeatures = field(default_factory=RuntimeFeatures)

    @classmethod
    def from_settings(cls, settings: Any) -> "HarnessConfig":
        """Create harness defaults from a Focus Agent ``Settings``-like object."""

        return cls(
            default_model=getattr(settings, "model", None),
            default_thinking_mode=getattr(settings, "selected_thinking_mode", None),
            heartbeat_seconds=float(getattr(settings, "sse_heartbeat_seconds", 1.5)),
            stream_queue_maxsize=int(getattr(settings, "background_queue_max_size", 256)),
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
    "HarnessConfig",
    "RuntimeFeatureSpec",
    "RuntimeFeatures",
]
