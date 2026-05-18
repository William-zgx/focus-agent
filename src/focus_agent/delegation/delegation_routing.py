from __future__ import annotations

from ..config import Settings
from ..model_registry import canonical_model_id
from ..runtime.model_router import ModelRouter, TaskKind
from .delegation_models import ModelRouteDecision
from .roles import AgentRole, normalize_agent_role


def build_model_route_decision(
    *,
    settings: Settings,
    role: AgentRole | str = AgentRole.EXECUTOR,
    selected_model: str | None = None,
    task_text: str = "",
    tool_risk: str = "low",
    context_size: int = 0,
) -> ModelRouteDecision:
    role_value = normalize_agent_role(role)
    current = canonical_model_id(selected_model or settings.model, settings=settings)
    enabled = bool(getattr(settings, "agent_model_router_enabled", False))
    mode = str(getattr(settings, "agent_model_router_mode", "observe") or "observe").lower()
    mode = "enforce" if mode == "enforce" else "observe"
    router_decision = ModelRouter.from_settings(settings).decide(kind=_role_task_kind(role_value))
    recommended = canonical_model_id(router_decision.selected_model, settings=settings)
    reason = _model_route_reason(
        role_value, task_text=task_text, tool_risk=tool_risk, context_size=context_size
    )
    effective = recommended if enabled and mode == "enforce" else current
    return ModelRouteDecision(
        enabled=enabled,
        mode=mode,  # type: ignore[arg-type]
        role=role_value,
        selected_model=current,
        recommended_model=recommended,
        effective_model=effective,
        route_reason=reason,
        fallback_used=enabled and mode == "enforce" and router_decision.fallback_used,
        candidates=_model_candidates(
            settings, role_value, current, router_decision.fallback_models
        ),
    )


def _model_route_reason(
    role: AgentRole, *, task_text: str, tool_risk: str, context_size: int
) -> str:
    if role == AgentRole.CRITIC:
        return "Critic can start with a lower-cost reviewer model and escalate on low confidence."
    if role == AgentRole.PLANNER:
        return "Planning/decomposition uses the planner/helper model before execution."
    if tool_risk in {"high", "critical"}:
        return "High-risk tool usage requires explicit model route observability."
    if context_size > 12000:
        return "Large context favors a model profile with stronger context handling."
    if task_text and len(task_text) < 120:
        return "Short direct task can stay on the selected executor model."
    return "Role-specific model route selected from current settings."


def _role_task_kind(role: AgentRole) -> TaskKind:
    if role == AgentRole.PLANNER:
        return TaskKind.PLANNING
    if role == AgentRole.CRITIC:
        return TaskKind.CRITIC
    if role == AgentRole.MEMORY_CURATOR:
        return TaskKind.MEMORY_CURATION
    if role == AgentRole.SKILL_SCOUT:
        return TaskKind.SKILL_SCOUT
    return TaskKind.EXECUTION


def _model_candidates(
    settings: Settings,
    role: AgentRole,
    current: str,
    fallbacks: tuple[str, ...],
) -> list[str]:
    router_decision = ModelRouter.from_settings(settings).decide(kind=_role_task_kind(role))
    candidates = [canonical_model_id(router_decision.selected_model, settings=settings), current]
    helper = getattr(settings, "helper_model", None)
    if helper:
        candidates.append(canonical_model_id(helper, settings=settings))
    for fallback in fallbacks:
        candidates.append(canonical_model_id(fallback, settings=settings))
    return list(dict.fromkeys(candidates))


__all__ = ["build_model_route_decision"]
