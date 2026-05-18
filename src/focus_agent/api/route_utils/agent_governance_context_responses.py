from __future__ import annotations

from typing import Any

from focus_agent.delegation.context_engineering import (
    build_context_engineering_decision,
    build_context_policy,
)
from focus_agent.delegation.delegation import build_agent_delegation_plan
from focus_agent.delegation.roles import build_role_route_plan
from focus_agent.delegation.task_ledger import (
    build_agent_task_ledger,
    build_delegated_artifacts,
    build_task_ledger_policy,
    evaluate_critic_gate,
    synthesize_delegated_artifacts,
)
from focus_agent.config import Settings
from focus_agent.engine.runtime import AppRuntime

from ..contracts import (
    AgentArtifactListResponse,
    AgentArtifactSynthesisRequest,
    AgentArtifactSynthesisResponse,
    AgentContextArtifactListResponse,
    AgentContextDecisionListResponse,
    AgentContextPolicyResponse,
    AgentContextPreviewRequest,
    AgentContextPreviewResponse,
    AgentCriticEvaluateRequest,
    AgentCriticEvaluateResponse,
    AgentCriticVerdictListResponse,
    AgentTaskLedgerPlanRequest,
    AgentTaskLedgerPlanResponse,
    AgentTaskLedgerPolicyResponse,
    AgentTaskLedgerRunListResponse,
)
from .agent_governance_role_tool_responses import _available_tool_names
from .agent_governance_trajectory_responses import _list_response_fields


def _agent_task_ledger_policy_response(settings: Settings | Any) -> AgentTaskLedgerPolicyResponse:
    return AgentTaskLedgerPolicyResponse(**build_task_ledger_policy(settings))


def _agent_context_policy_response(settings: Settings | Any) -> AgentContextPolicyResponse:
    return AgentContextPolicyResponse(**build_context_policy(settings))


def _agent_context_preview_response(
    *,
    payload: AgentContextPreviewRequest,
    runtime: AppRuntime | Any,
) -> AgentContextPreviewResponse:
    decision = build_context_engineering_decision(
        settings=runtime.settings,
        state=dict(payload.state or {}),
        prompt_mode=payload.prompt_mode,
        assembled_context=payload.assembled_context,
        role=payload.role,
        artifact_dir=runtime.settings.artifact_dir,
        materialize=payload.materialize_artifacts,
    )
    return AgentContextPreviewResponse(decision=decision.model_dump(mode="json"))


def _agent_context_decisions_response(
    *,
    runtime: AppRuntime | Any,
    limit: int,
) -> AgentContextDecisionListResponse:
    return AgentContextDecisionListResponse(
        **_list_response_fields(runtime=runtime, key="context_budget_decision", limit=limit, decisions=True)
    )


def _agent_context_artifacts_response(
    *,
    runtime: AppRuntime | Any,
    limit: int,
) -> AgentContextArtifactListResponse:
    return AgentContextArtifactListResponse(
        **_list_response_fields(runtime=runtime, key="context_artifact_refs", limit=limit)
    )


def _task_ledger_delegation_plan(
    *,
    payload: AgentTaskLedgerPlanRequest,
    runtime: AppRuntime | Any,
) -> dict[str, Any]:
    delegation_plan = dict(payload.delegation_plan or {})
    if delegation_plan or not payload.message:
        return delegation_plan
    available_tools = _available_tool_names(runtime)
    role_route = build_role_route_plan(
        settings=runtime.settings,
        task_text=payload.message,
        available_tool_names=available_tools,
        tool_policy="agent_task_ledger_console",
    )
    return build_agent_delegation_plan(
        settings=runtime.settings,
        task_text=payload.message,
        role_route_plan=role_route.model_dump(mode="json"),
        available_tool_names=available_tools,
        tool_policy="agent_task_ledger_console",
    ).model_dump(mode="json")


def _agent_task_ledger_plan_response(
    *,
    payload: AgentTaskLedgerPlanRequest,
    runtime: AppRuntime | Any,
) -> AgentTaskLedgerPlanResponse:
    delegation_plan = _task_ledger_delegation_plan(payload=payload, runtime=runtime)
    ledger = build_agent_task_ledger(
        settings=runtime.settings,
        delegation_plan=delegation_plan,
    ).model_dump(mode="json")
    artifacts = [
        item.model_dump(mode="json")
        for item in build_delegated_artifacts(
            ledger=ledger,
            delegation_plan=delegation_plan,
        )
    ]
    critic_result = (
        evaluate_critic_gate(
            settings=runtime.settings,
            ledger=ledger,
            artifacts=artifacts,
        ).model_dump(mode="json")
        if getattr(runtime.settings, "agent_critic_gate_enabled", False)
        else None
    )
    synthesis_result = (
        synthesize_delegated_artifacts(
            settings=runtime.settings,
            artifacts=artifacts,
            critic_gate_result=critic_result,
        ).model_dump(mode="json")
        if getattr(runtime.settings, "agent_artifact_synthesis_enabled", False)
        else None
    )
    return AgentTaskLedgerPlanResponse(
        policy=_agent_task_ledger_policy_response(runtime.settings),
        ledger=ledger,
        artifacts=artifacts,
        critic_gate_result=critic_result,
        synthesis_result=synthesis_result,
    )


def _agent_task_ledger_runs_response(
    *,
    runtime: AppRuntime | Any,
    limit: int,
) -> AgentTaskLedgerRunListResponse:
    return AgentTaskLedgerRunListResponse(
        **_list_response_fields(runtime=runtime, key="agent_task_ledger.tasks", limit=limit)
    )


def _agent_artifacts_response(
    *,
    runtime: AppRuntime | Any,
    limit: int,
) -> AgentArtifactListResponse:
    return AgentArtifactListResponse(
        **_list_response_fields(runtime=runtime, key="delegated_artifacts", limit=limit)
    )


def _agent_artifact_synthesis_response_with_runtime(
    *,
    payload: AgentArtifactSynthesisRequest,
    runtime: AppRuntime | Any,
) -> AgentArtifactSynthesisResponse:
    result = synthesize_delegated_artifacts(
        settings=runtime.settings,
        artifacts=payload.artifacts,
        critic_gate_result=payload.critic_gate_result,
    )
    return AgentArtifactSynthesisResponse(result=result.model_dump(mode="json"))


def _agent_critic_verdicts_response(
    *,
    runtime: AppRuntime | Any,
    limit: int,
) -> AgentCriticVerdictListResponse:
    return AgentCriticVerdictListResponse(
        **_list_response_fields(runtime=runtime, key="critic_gate_result", limit=limit, decisions=True)
    )


def _agent_critic_evaluate_response(
    *,
    payload: AgentCriticEvaluateRequest,
    runtime: AppRuntime | Any,
) -> AgentCriticEvaluateResponse:
    result = evaluate_critic_gate(
        settings=runtime.settings,
        ledger=payload.ledger,
        artifacts=payload.artifacts,
    )
    return AgentCriticEvaluateResponse(result=result.model_dump(mode="json"))


__all__ = [
    "_agent_artifact_synthesis_response_with_runtime",
    "_agent_artifacts_response",
    "_agent_context_artifacts_response",
    "_agent_context_decisions_response",
    "_agent_context_policy_response",
    "_agent_context_preview_response",
    "_agent_critic_evaluate_response",
    "_agent_critic_verdicts_response",
    "_agent_task_ledger_plan_response",
    "_agent_task_ledger_policy_response",
    "_agent_task_ledger_runs_response",
    "_task_ledger_delegation_plan",
]
