from __future__ import annotations

from .delegation_models import ModelRouteDecision
from .roles import AgentRole, RoleModelResolver, normalize_agent_role
from ..config import Settings
from ..model_registry import canonical_model_id


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
    resolver = RoleModelResolver(settings)
    recommended = resolver.resolve(role_value, fallback_model=current)
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
        fallback_used=enabled and mode == "enforce" and effective != recommended,
        candidates=_model_candidates(settings, role_value, current),
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


def _model_candidates(settings: Settings, role: AgentRole, current: str) -> list[str]:
    resolver = RoleModelResolver(settings)
    candidates = [resolver.resolve(role, fallback_model=current), current]
    helper = getattr(settings, "helper_model", None)
    if helper:
        candidates.append(canonical_model_id(helper, settings=settings))
    return list(dict.fromkeys(candidates))


__all__ = ["build_model_route_decision"]
