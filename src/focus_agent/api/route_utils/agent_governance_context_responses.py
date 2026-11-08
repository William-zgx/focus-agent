from __future__ import annotations

from typing import Any

from focus_agent.config import Settings
from focus_agent.core.context.engineering import (
    build_context_engineering_decision,
    build_context_policy,
)
from focus_agent.engine.runtime import AppRuntime

from ..contracts import (
    AgentArtifactListResponse,
    AgentContextArtifactListResponse,
    AgentContextDecisionListResponse,
    AgentContextPolicyResponse,
    AgentContextPreviewRequest,
    AgentContextPreviewResponse,
)
from .agent_governance_trajectory_responses import _list_response_fields


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
        **_list_response_fields(
            runtime=runtime, key="context_budget_decision", limit=limit, decisions=True
        )
    )


def _agent_context_artifacts_response(
    *,
    runtime: AppRuntime | Any,
    limit: int,
) -> AgentContextArtifactListResponse:
    return AgentContextArtifactListResponse(
        **_list_response_fields(runtime=runtime, key="context_artifact_refs", limit=limit)
    )


def _agent_artifacts_response(
    *,
    runtime: AppRuntime | Any,
    limit: int,
) -> AgentArtifactListResponse:
    return AgentArtifactListResponse(
        **_list_response_fields(runtime=runtime, key="delegated_artifacts", limit=limit)
    )


__all__ = [
    "_agent_artifacts_response",
    "_agent_context_artifacts_response",
    "_agent_context_decisions_response",
    "_agent_context_policy_response",
    "_agent_context_preview_response",
]
