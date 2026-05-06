from __future__ import annotations

from typing import Any, MutableMapping

from .common import _env_bool, _normalize_agent_delegation_execution_mode, _split_csv


def load_agent_config(env: MutableMapping[str, str], defaults: Any) -> dict[str, object]:
    return {
        "plan_act_reflect_enabled": _env_bool(
            env, "PLAN_ACT_REFLECT_ENABLED", default=defaults.plan_act_reflect_enabled
        ),
        "plan_scenes": (
            _split_csv(env.get("PLAN_SCENES"))
            if env.get("PLAN_SCENES") is not None
            else defaults.plan_scenes
        ),
        "plan_task_brief_min_chars": int(
            env.get("PLAN_TASK_BRIEF_MIN_CHARS", str(defaults.plan_task_brief_min_chars))
        ),
        "plan_max_replans": int(env.get("PLAN_MAX_REPLANS", str(defaults.plan_max_replans))),
        "agent_role_routing_enabled": _env_bool(
            env, "AGENT_ROLE_ROUTING_ENABLED", default=defaults.agent_role_routing_enabled
        ),
        "agent_role_orchestrator_model": (
            env.get("AGENT_ROLE_ORCHESTRATOR_MODEL") or defaults.agent_role_orchestrator_model
        ),
        "agent_role_planner_model": (
            env.get("AGENT_ROLE_PLANNER_MODEL") or defaults.agent_role_planner_model
        ),
        "agent_role_executor_model": (
            env.get("AGENT_ROLE_EXECUTOR_MODEL") or defaults.agent_role_executor_model
        ),
        "agent_role_critic_model": (
            env.get("AGENT_ROLE_CRITIC_MODEL") or defaults.agent_role_critic_model
        ),
        "agent_role_memory_model": (
            env.get("AGENT_ROLE_MEMORY_MODEL") or defaults.agent_role_memory_model
        ),
        "agent_role_skill_model": (
            env.get("AGENT_ROLE_SKILL_MODEL") or defaults.agent_role_skill_model
        ),
        "agent_role_max_parallel_runs": max(
            1,
            int(
                env.get(
                    "AGENT_ROLE_MAX_PARALLEL_RUNS",
                    str(defaults.agent_role_max_parallel_runs),
                )
            ),
        ),
        "agent_memory_backend": str(
            env.get("AGENT_MEMORY_BACKEND") or defaults.agent_memory_backend
        ).strip().lower(),
        "agent_memory_read_source": str(
            env.get("AGENT_MEMORY_READ_SOURCE") or defaults.agent_memory_read_source
        ).strip().lower(),
        "agent_memory_extractor_mode": str(
            env.get("AGENT_MEMORY_EXTRACTOR_MODE") or defaults.agent_memory_extractor_mode
        ).strip().lower(),
        "agent_memory_postgres_trigram_enabled": _env_bool(
            env,
            "AGENT_MEMORY_POSTGRES_TRIGRAM_ENABLED",
            default=defaults.agent_memory_postgres_trigram_enabled,
        ),
        "agent_memory_approval_for_shared_writes": _env_bool(
            env,
            "AGENT_MEMORY_APPROVAL_FOR_SHARED_WRITES",
            default=defaults.agent_memory_approval_for_shared_writes,
        ),
        "agent_memory_curator_enabled": _env_bool(
            env, "AGENT_MEMORY_CURATOR_ENABLED", default=defaults.agent_memory_curator_enabled
        ),
        "agent_memory_auto_promote_on_merge": _env_bool(
            env,
            "AGENT_MEMORY_AUTO_PROMOTE_ON_MERGE",
            default=defaults.agent_memory_auto_promote_on_merge,
        ),
        "agent_tool_router_enabled": _env_bool(
            env, "AGENT_TOOL_ROUTER_ENABLED", default=defaults.agent_tool_router_enabled
        ),
        "agent_tool_router_enforce": _env_bool(
            env, "AGENT_TOOL_ROUTER_ENFORCE", default=defaults.agent_tool_router_enforce
        ),
        "agent_delegation_enabled": _env_bool(
            env, "AGENT_DELEGATION_ENABLED", default=defaults.agent_delegation_enabled
        ),
        "agent_delegation_enforce": _env_bool(
            env, "AGENT_DELEGATION_ENFORCE", default=defaults.agent_delegation_enforce
        ),
        "agent_delegation_execution_mode": _normalize_agent_delegation_execution_mode(
            env.get(
                "AGENT_DELEGATION_EXECUTION_MODE",
                defaults.agent_delegation_execution_mode,
            )
        ),
        "agent_model_router_enabled": _env_bool(
            env, "AGENT_MODEL_ROUTER_ENABLED", default=defaults.agent_model_router_enabled
        ),
        "agent_model_router_mode": (
            "enforce"
            if str(env.get("AGENT_MODEL_ROUTER_MODE", defaults.agent_model_router_mode)).lower()
            == "enforce"
            else "observe"
        ),
        "agent_self_repair_enabled": _env_bool(
            env, "AGENT_SELF_REPAIR_ENABLED", default=defaults.agent_self_repair_enabled
        ),
        "agent_review_queue_enabled": _env_bool(
            env, "AGENT_REVIEW_QUEUE_ENABLED", default=defaults.agent_review_queue_enabled
        ),
        "agent_task_ledger_enabled": _env_bool(
            env, "AGENT_TASK_LEDGER_ENABLED", default=defaults.agent_task_ledger_enabled
        ),
        "agent_artifact_synthesis_enabled": _env_bool(
            env,
            "AGENT_ARTIFACT_SYNTHESIS_ENABLED",
            default=defaults.agent_artifact_synthesis_enabled,
        ),
        "agent_critic_gate_enabled": _env_bool(
            env, "AGENT_CRITIC_GATE_ENABLED", default=defaults.agent_critic_gate_enabled
        ),
        "agent_critic_gate_enforce": _env_bool(
            env, "AGENT_CRITIC_GATE_ENFORCE", default=defaults.agent_critic_gate_enforce
        ),
    }
