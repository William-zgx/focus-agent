from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class TaskKind(StrEnum):
    PLANNING = "planning"
    EXECUTION = "execution"
    CRITIC = "critic"
    MEMORY_CURATION = "memory_curation"
    SKILL_SCOUT = "skill_scout"


@dataclass(frozen=True, slots=True)
class ModelChoice:
    primary: str
    fallbacks: tuple[str, ...] = ()
    max_tokens_per_min: int | None = None
    cost_budget_usd_per_day: float | None = None
    canary_user_ratio: float = 0.0
    canary_model: str | None = None


@dataclass(frozen=True, slots=True)
class ModelRouterDecision:
    kind: TaskKind
    selected_model: str
    primary_model: str
    fallback_models: tuple[str, ...]
    canary: bool = False
    fallback_used: bool = False
    max_tokens_per_min: int | None = None
    cost_budget_usd_per_day: float | None = None


class ModelRouter:
    def __init__(self, registry: Any, default_policy: dict[TaskKind, ModelChoice]):
        self._registry = registry
        self._policy = dict(default_policy)

    @classmethod
    def from_settings(cls, settings: Any) -> ModelRouter:
        default_model = str(getattr(settings, "model", "") or "").strip()
        helper_model = str(getattr(settings, "helper_model", "") or "").strip()
        global_fallbacks = tuple(
            model
            for model in tuple(getattr(settings, "model_choices", ()) or ())
            if model and model != default_model
        )
        role_fallbacks = dict(getattr(settings, "multi_agent_role_fallback_models", {}) or {})

        def choice(
            *,
            attr: str,
            role: str,
            default: str,
        ) -> ModelChoice:
            primary = str(getattr(settings, attr, None) or default or default_model).strip()
            fallback = str(role_fallbacks.get(role) or "").strip()
            fallbacks = _dedupe(
                model for model in (fallback, *global_fallbacks) if model and model != primary
            )
            return ModelChoice(primary=primary, fallbacks=fallbacks)

        helper_default = helper_model or default_model
        return cls(
            None,
            {
                TaskKind.PLANNING: choice(
                    attr="agent_role_planner_model",
                    role="planner",
                    default=helper_default,
                ),
                TaskKind.EXECUTION: choice(
                    attr="agent_role_executor_model",
                    role="executor",
                    default=default_model,
                ),
                TaskKind.CRITIC: choice(
                    attr="agent_role_critic_model",
                    role="critic",
                    default=helper_default,
                ),
                TaskKind.MEMORY_CURATION: choice(
                    attr="agent_role_memory_model",
                    role="memory",
                    default=helper_default,
                ),
                TaskKind.SKILL_SCOUT: choice(
                    attr="agent_role_skill_model",
                    role="skill_scout",
                    default=helper_default,
                ),
            },
        )

    def pick(
        self,
        *,
        kind: TaskKind | str,
        user_id: str | None = None,
        unavailable_models: Iterable[str] | None = None,
    ) -> str:
        return self.decide(
            kind=kind,
            user_id=user_id,
            unavailable_models=unavailable_models,
        ).selected_model

    def decide(
        self,
        *,
        kind: TaskKind | str,
        user_id: str | None = None,
        unavailable_models: Iterable[str] | None = None,
    ) -> ModelRouterDecision:
        task_kind = kind if isinstance(kind, TaskKind) else TaskKind(str(kind))
        choice = self._policy[task_kind]
        canary = (
            choice.canary_model is not None
            and choice.canary_user_ratio > 0
            and _is_in_canary(user_id, choice.canary_user_ratio)
        )
        selected = choice.canary_model if canary and choice.canary_model else choice.primary
        unavailable = set(unavailable_models or ())
        fallback_used = False
        if selected in unavailable:
            for candidate in choice.fallbacks:
                if candidate not in unavailable:
                    selected = candidate
                    fallback_used = True
                    canary = False
                    break
        return ModelRouterDecision(
            kind=task_kind,
            selected_model=selected,
            primary_model=choice.primary,
            fallback_models=choice.fallbacks,
            canary=canary,
            fallback_used=fallback_used,
            max_tokens_per_min=choice.max_tokens_per_min,
            cost_budget_usd_per_day=choice.cost_budget_usd_per_day,
        )

    def fallbacks(self, kind: TaskKind | str) -> tuple[str, ...]:
        task_kind = kind if isinstance(kind, TaskKind) else TaskKind(str(kind))
        return self._policy[task_kind].fallbacks


def _is_in_canary(user_id: str | None, ratio: float) -> bool:
    if ratio <= 0:
        return False
    if ratio >= 1:
        return True
    seed = str(user_id or "anonymous").encode("utf-8")
    bucket = int.from_bytes(hashlib.sha256(seed).digest()[:4], "big") / 2**32
    return bucket < ratio


def _dedupe(models: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(model).strip() for model in models if str(model).strip()))


__all__ = ["ModelChoice", "ModelRouter", "ModelRouterDecision", "TaskKind"]
