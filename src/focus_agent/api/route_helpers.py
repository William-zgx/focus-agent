"""Shared route helpers and re-exported route dependencies."""

from __future__ import annotations

# ruff: noqa: F401

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Sequence
from uuid import uuid4

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from focus_agent.agent_roles import AgentRole, RoleModelResolver, build_role_route_plan
from focus_agent.agent_delegation import (
    apply_review_decision,
    build_agent_delegation_plan,
    build_model_route_decision,
    build_self_repair_preview,
)
from focus_agent.agent_context_engineering import (
    build_context_engineering_decision,
    build_context_policy,
)
from focus_agent.agent_task_ledger import (
    build_agent_task_ledger,
    build_delegated_artifacts,
    build_task_ledger_policy,
    evaluate_critic_gate,
    synthesize_delegated_artifacts,
)
from focus_agent.capabilities.tool_router import build_capability_registry, build_tool_route_plan
from focus_agent.core.request_context import RequestContext
from focus_agent.core.types import ConversationRecord
from focus_agent.memory import MemoryCurator
from focus_agent.security.tokens import Principal, create_access_token
from focus_agent.config import Settings
from focus_agent.core.branching import BranchRecord, BranchRole, BranchStatus, MergeDecision
from focus_agent.engine.runtime import AppRuntime, create_runtime
from focus_agent.observability.trajectory_actions import (
    build_promoted_dataset_payload,
    load_turn_export,
    run_replay_for_turn,
)
from focus_agent.repositories.postgres_trajectory_repository import (
    PostgresTrajectoryRepository,
    TrajectoryTurnQuery,
)
from focus_agent.services.chat import ChatService, ConcurrentTurnError
from focus_agent.web.frontend_app import (
    build_frontend_dev_server_redirect_url,
    render_frontend_entry_html,
    resolve_frontend_dev_server_url,
    resolve_frontend_dist_dir,
)

from .contracts import (
    AgentRoleDecisionListResponse,
    AgentRoleDryRunRequest,
    AgentRoleDryRunResponse,
    AgentRolePolicyResponse,
    AgentCapabilityListResponse,
    AgentMemoryCuratorDecisionListResponse,
    AgentMemoryCuratorEvaluateRequest,
    AgentMemoryCuratorEvaluateResponse,
    AgentMemoryCuratorPolicyResponse,
    AgentDelegationPlanRequest,
    AgentDelegationPlanResponse,
    AgentDelegationPolicyResponse,
    AgentDelegationRunListResponse,
    AgentModelRouteRequest,
    AgentModelRouteResponse,
    AgentModelRouterDecisionListResponse,
    AgentModelRouterPolicyResponse,
    AgentReviewQueueDecisionResponse,
    AgentReviewQueueListResponse,
    AgentContextArtifactListResponse,
    AgentContextDecisionListResponse,
    AgentContextPolicyResponse,
    AgentContextPreviewRequest,
    AgentContextPreviewResponse,
    AgentArtifactListResponse,
    AgentArtifactSynthesisRequest,
    AgentArtifactSynthesisResponse,
    AgentCriticEvaluateRequest,
    AgentCriticEvaluateResponse,
    AgentCriticVerdictListResponse,
    AgentTaskLedgerPlanRequest,
    AgentTaskLedgerPlanResponse,
    AgentTaskLedgerPolicyResponse,
    AgentTaskLedgerRunListResponse,
    AgentSelfRepairFailureListResponse,
    AgentSelfRepairPromotePreviewRequest,
    AgentSelfRepairPromotePreviewResponse,
    AgentToolRouteDecisionListResponse,
    AgentToolRouteRequest,
    AgentToolRouteResponse,
    UpdateAgentTeamTaskRequest,
    RecordAgentTeamTaskOutputRequest,
    CreateAgentTeamTaskRequest,
    CreateAgentTeamSessionRequest,
    DispatchAgentTeamSessionRequest,
    ApplyAgentTeamMergeDecisionRequest,
    AgentTeamDispatchResponse,
    AgentTeamTaskResponse,
    AgentTeamTaskOutputResponse,
    AgentTeamTaskListResponse,
    AgentTeamSessionResponse,
    AgentTeamSessionListResponse,
    AgentTeamMergeDecisionResponse,
    AgentTeamMergeBundleResponse,
    ApplyMergeDecisionRequest,
    ApplyMergeDecisionResponse,
    BranchActionExecuteResponse,
    BranchActionProposal,
    BranchTreeResponse,
    ChatResumeRequest,
    ChatTurnRequest,
    ConversationListResponse,
    ConversationSummaryResponse,
    CreateConversationRequest,
    DemoTokenRequest,
    ForkBranchRequest,
    ModelCatalogResponse,
    ObservabilityOverviewResponse,
    PrepareMergeProposalRequest,
    PrincipalResponse,
    RuntimeComponentStatusResponse,
    RuntimeReadinessResponse,
    TrajectoryBatchPromotionPreviewRequest,
    TrajectoryBatchPromotionPreviewResponse,
    TrajectoryBatchReplayCompareRequest,
    TrajectoryBatchReplayCompareResponse,
    TrajectoryBatchReplaySummaryResponse,
    TrajectoryPromotionRequest,
    TrajectoryPromotionResponse,
    TrajectoryReplayComparisonResponse,
    TrajectoryReplayCaseResponse,
    TrajectoryReplayRequest,
    TrajectoryReplayResponse,
    TrajectoryReplayResultResponse,
    ThreadStateResponse,
    ThreadContextCompactRequest,
    ThreadContextCompactResponse,
    ThreadContextPreviewRequest,
    ThreadContextPreviewResponse,
    TokenResponse,
    TrajectoryStatsBucketResponse,
    TrajectoryStatsOverviewResponse,
    TrajectoryStepResponse,
    TrajectoryTurnDetailEnvelopeResponse,
    TrajectoryTurnDetailResponse,
    TrajectoryTurnListResponse,
    TrajectoryTurnStatsEnvelopeResponse,
    TrajectoryTurnStatsResponse,
    TrajectoryTurnSummaryResponse,
    UpdateBranchNameRequest,
    UpdateConversationRequest,
)
from .deps import get_app_runtime, get_chat_service, get_current_principal
from .errors import register_exception_handlers
from .middleware import configure_middleware
from focus_agent.model_registry import build_model_catalog

def _agent_team_service_or_503(runtime: AppRuntime | Any):
    service = getattr(runtime, "agent_team_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Agent team service is unavailable.")
    return service


def _agent_team_error(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))

def _normalize_token_usage(raw: dict[str, Any] | None = None) -> dict[str, int]:
    payload = dict(raw or {})
    input_tokens = int(payload.get("input_tokens") or 0)
    output_tokens = int(payload.get("output_tokens") or 0)
    total_tokens = int(payload.get("total_tokens") or (input_tokens + output_tokens))
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def _accumulate_token_usage(current: dict[str, int], delta: dict[str, int] | None = None) -> dict[str, int]:
    normalized = _normalize_token_usage(delta)
    return {
        "input_tokens": int(current.get("input_tokens") or 0) + normalized["input_tokens"],
        "output_tokens": int(current.get("output_tokens") or 0) + normalized["output_tokens"],
        "total_tokens": int(current.get("total_tokens") or 0) + normalized["total_tokens"],
    }


def _aggregate_token_usage_from_turns(turns: Sequence[dict[str, Any]]) -> dict[str, int]:
    total = _normalize_token_usage()
    for turn in turns:
        total = _accumulate_token_usage(total, dict(turn.get("metrics") or {}))
    return total


def _token_usage_for_root_thread(*, runtime: AppRuntime, root_thread_id: str) -> dict[str, int]:
    repo = _maybe_get_trajectory_repository(runtime)
    if repo is None:
        return _normalize_token_usage()
    try:
        turns = repo.list_turns(TrajectoryTurnQuery(root_thread_id=root_thread_id, limit=None, newest_first=True))
    except Exception:  # noqa: BLE001
        return _normalize_token_usage()
    return _aggregate_token_usage_from_turns(turns)


def _token_usage_by_thread_for_root(*, runtime: AppRuntime, root_thread_id: str) -> dict[str, dict[str, int]]:
    repo = _maybe_get_trajectory_repository(runtime)
    if repo is None:
        return {}
    try:
        turns = repo.list_turns(TrajectoryTurnQuery(root_thread_id=root_thread_id, limit=None, newest_first=True))
    except Exception:  # noqa: BLE001
        return {}

    grouped: dict[str, dict[str, int]] = {}
    for turn in turns:
        thread_id = str(turn.get("thread_id") or "").strip()
        if not thread_id:
            continue
        grouped[thread_id] = _accumulate_token_usage(grouped.get(thread_id, _normalize_token_usage()), dict(turn.get("metrics") or {}))
    return grouped


def _annotate_branch_tree_token_usage(
    node,
    *,
    by_thread_id: dict[str, dict[str, int]],
    root_thread_usage: dict[str, int] | None = None,
):
    is_root_main_node = not getattr(node, "branch_id", None) and str(getattr(node, "thread_id", "")) == str(getattr(node, "root_thread_id", ""))
    token_usage = root_thread_usage if is_root_main_node and root_thread_usage is not None else by_thread_id.get(node.thread_id)
    return node.model_copy(
        update={
            "token_usage": _normalize_token_usage(token_usage),
            "children": [
                _annotate_branch_tree_token_usage(
                    child,
                    by_thread_id=by_thread_id,
                    root_thread_usage=root_thread_usage,
                )
                for child in list(node.children or [])
            ],
        }
    )


def _conversation_response(record: ConversationRecord) -> ConversationSummaryResponse:
    return ConversationSummaryResponse(
        root_thread_id=record.root_thread_id,
        title=record.title,
        is_archived=record.is_archived,
        archived_at=record.archived_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
        token_usage=_normalize_token_usage(record.token_usage),
    )


def _list_or_bootstrap_conversations(*, runtime: AppRuntime, user_id: str) -> list[ConversationRecord]:
    conversations = runtime.repo.list_conversations(owner_user_id=user_id)
    if conversations:
        return conversations

    default_root_thread_id = f"{user_id}-main"
    runtime.repo.ensure_thread_owner(
        thread_id=default_root_thread_id,
        root_thread_id=default_root_thread_id,
        owner_user_id=user_id,
    )
    runtime.repo.create_conversation(
        ConversationRecord(
            root_thread_id=default_root_thread_id,
            owner_user_id=user_id,
            title="Main",
            title_pending_ai=True,
        )
    )
    return runtime.repo.list_conversations(owner_user_id=user_id)


def _as_scalar_or_sequence(values: Sequence[str] | None) -> str | list[str] | None:
    if not values:
        return None
    normalized = [str(value).strip() for value in values if str(value).strip()]
    if not normalized:
        return None
    if len(normalized) == 1:
        return normalized[0]
    return normalized


def _trajectory_query_from_request(
    *,
    turn_ids: Sequence[str] | None = None,
    request_id: str | None = None,
    trace_id: str | None = None,
    thread_id: str | None = None,
    root_thread_id: str | None = None,
    parent_thread_id: str | None = None,
    branch_id: str | None = None,
    branch_role: Sequence[str] | None = None,
    status: Sequence[str] | None = None,
    scene: Sequence[str] | None = None,
    kind: Sequence[str] | None = None,
    tool: Sequence[str] | None = None,
    model: Sequence[str] | None = None,
    fallback_used: bool | None = None,
    cache_hit: bool | None = None,
    has_error: bool | None = None,
    started_after: datetime | None = None,
    started_before: datetime | None = None,
    min_latency_ms: float | None = None,
    max_latency_ms: float | None = None,
    min_tool_calls: int | None = None,
    max_tool_calls: int | None = None,
    limit: int | None = None,
    offset: int = 0,
    newest_first: bool = True,
) -> TrajectoryTurnQuery:
    return TrajectoryTurnQuery(
        turn_ids=[str(turn_id) for turn_id in turn_ids or [] if str(turn_id).strip()] or None,
        request_id=request_id,
        trace_id=trace_id,
        thread_id=thread_id,
        root_thread_id=root_thread_id,
        parent_thread_id=parent_thread_id,
        branch_id=branch_id,
        branch_role=_as_scalar_or_sequence(branch_role),
        status=_as_scalar_or_sequence(status),
        scene=_as_scalar_or_sequence(scene),
        kind=_as_scalar_or_sequence(kind),
        tool=_as_scalar_or_sequence(tool),
        selected_model=_as_scalar_or_sequence(model),
        fallback_used=fallback_used,
        cache_hit=cache_hit,
        has_error=has_error,
        since=started_after,
        until=started_before,
        min_latency_ms=min_latency_ms,
        max_latency_ms=max_latency_ms,
        min_tool_calls=min_tool_calls,
        max_tool_calls=max_tool_calls,
        limit=limit,
        offset=offset,
        newest_first=newest_first,
    )


def _get_trajectory_repository(runtime: AppRuntime) -> PostgresTrajectoryRepository | Any:
    candidate = runtime.trajectory_recorder
    required_methods = ("list_turns", "get_turn", "list_steps_by_turn_ids", "get_turn_stats")
    if candidate is not None and all(callable(getattr(candidate, name, None)) for name in required_methods):
        return candidate
    if runtime.settings.database_uri:
        return PostgresTrajectoryRepository(runtime.settings.database_uri)
    raise HTTPException(
        status_code=503,
        detail=(
            "Trajectory observability requires a configured Postgres database "
            "or an initialized trajectory recorder."
        ),
    )


def _build_trajectory_summary_response(item: dict[str, Any]) -> TrajectoryTurnSummaryResponse:
    return TrajectoryTurnSummaryResponse.model_validate(item)


def _build_trajectory_detail_response(
    *,
    record: Any,
    step_rows: Sequence[dict[str, Any]],
    created_at: Any = None,
) -> TrajectoryTurnDetailResponse:
    metrics = dict(getattr(record, "metrics", {}) or {})
    payload = {
        "id": str(record.id),
        "schema_version": int(record.schema_version),
        "kind": str(record.kind),
        "status": str(record.status),
        "thread_id": str(record.thread_id),
        "root_thread_id": str(record.root_thread_id),
        "request_id": getattr(record, "request_id", None),
        "trace_id": getattr(record, "trace_id", None),
        "root_span_id": getattr(record, "root_span_id", None),
        "environment": getattr(record, "environment", None),
        "deployment": getattr(record, "deployment", None),
        "app_version": getattr(record, "app_version", None),
        "parent_thread_id": record.parent_thread_id,
        "branch_id": record.branch_id,
        "branch_role": record.branch_role,
        "user_id_hash": str(record.user_id_hash),
        "scene": str(record.scene),
        "turn_index": record.turn_index,
        "task_brief": record.task_brief,
        "user_message": record.user_message,
        "answer": record.answer,
        "selected_model": record.selected_model,
        "selected_thinking_mode": record.selected_thinking_mode,
        "plan": record.plan,
        "reflection": record.reflection,
        "plan_meta": dict(getattr(record, "plan_meta", {}) or {}),
        "metrics": metrics,
        "error": record.error,
        "started_at": record.started_at,
        "finished_at": record.finished_at,
        "created_at": created_at,
        "latency_ms": float(metrics.get("latency_ms") or 0.0),
        "tool_calls": int(metrics.get("tool_calls") or 0),
        "llm_calls": int(metrics.get("llm_calls") or 0),
        "cache_hits": int(metrics.get("cache_hits") or 0),
        "fallback_uses": int(metrics.get("fallback_uses") or 0),
        "trajectory": [TrajectoryStepResponse.model_validate(step) for step in step_rows],
    }
    return TrajectoryTurnDetailResponse.model_validate(payload)


def _build_trajectory_stats_response(stats: dict[str, Any]) -> TrajectoryTurnStatsResponse:
    return TrajectoryTurnStatsResponse(
        overview=TrajectoryStatsOverviewResponse.model_validate(stats.get("overview") or {}),
        by_status=[
            TrajectoryStatsBucketResponse.model_validate(item)
            for item in (stats.get("by_status") or [])
        ],
        by_scene=[
            TrajectoryStatsBucketResponse.model_validate(item)
            for item in (stats.get("by_scene") or [])
        ],
        by_branch_role=[
            TrajectoryStatsBucketResponse.model_validate(item)
            for item in (stats.get("by_branch_role") or [])
        ],
        by_model=[
            TrajectoryStatsBucketResponse.model_validate(item)
            for item in (stats.get("by_model") or [])
        ],
        by_day=[
            TrajectoryStatsBucketResponse.model_validate(item)
            for item in (stats.get("by_day") or [])
        ],
        by_tool=[
            TrajectoryStatsBucketResponse.model_validate(item)
            for item in (stats.get("by_tool") or [])
        ],
    )


def _trajectory_filters_payload(
    *,
    turn_ids: Sequence[str] | None = None,
    request_id: str | None = None,
    trace_id: str | None = None,
    thread_id: str | None = None,
    root_thread_id: str | None = None,
    parent_thread_id: str | None = None,
    branch_id: str | None = None,
    branch_role: Sequence[str] | None = None,
    status: Sequence[str] | None = None,
    scene: Sequence[str] | None = None,
    kind: Sequence[str] | None = None,
    tool: Sequence[str] | None = None,
    model: Sequence[str] | None = None,
    fallback_used: bool | None = None,
    cache_hit: bool | None = None,
    has_error: bool | None = None,
    started_after: datetime | None = None,
    started_before: datetime | None = None,
    min_latency_ms: float | None = None,
    max_latency_ms: float | None = None,
    min_tool_calls: int | None = None,
    max_tool_calls: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    normalized_turn_ids = [str(turn_id) for turn_id in turn_ids or [] if str(turn_id).strip()]
    if normalized_turn_ids:
        payload["turn_ids"] = normalized_turn_ids
    if request_id:
        payload["request_id"] = request_id
    if trace_id:
        payload["trace_id"] = trace_id
    if thread_id:
        payload["thread_id"] = thread_id
    if root_thread_id:
        payload["root_thread_id"] = root_thread_id
    if parent_thread_id:
        payload["parent_thread_id"] = parent_thread_id
    if branch_id:
        payload["branch_id"] = branch_id
    if branch_role:
        payload["branch_role"] = list(branch_role)
    if status:
        payload["status"] = list(status)
    if scene:
        payload["scene"] = list(scene)
    if kind:
        payload["kind"] = list(kind)
    if tool:
        payload["tool"] = list(tool)
    if model:
        payload["model"] = list(model)
    if fallback_used is not None:
        payload["fallback_used"] = fallback_used
    if cache_hit is not None:
        payload["cache_hit"] = cache_hit
    if has_error is not None:
        payload["has_error"] = has_error
    if started_after is not None:
        payload["started_after"] = started_after.isoformat()
    if started_before is not None:
        payload["started_before"] = started_before.isoformat()
    if min_latency_ms is not None:
        payload["min_latency_ms"] = min_latency_ms
    if max_latency_ms is not None:
        payload["max_latency_ms"] = max_latency_ms
    if min_tool_calls is not None:
        payload["min_tool_calls"] = min_tool_calls
    if max_tool_calls is not None:
        payload["max_tool_calls"] = max_tool_calls
    return payload


def _trajectory_filters_from_batch_payload(payload: Any) -> dict[str, Any]:
    return _trajectory_filters_payload(
        turn_ids=payload.turn_ids,
        request_id=payload.request_id,
        trace_id=payload.trace_id,
        thread_id=payload.thread_id,
        root_thread_id=payload.root_thread_id,
        parent_thread_id=payload.parent_thread_id,
        branch_id=payload.branch_id,
        branch_role=payload.branch_role,
        status=payload.status,
        scene=payload.scene,
        kind=payload.kind,
        tool=payload.tool,
        model=payload.model,
        fallback_used=payload.fallback_used,
        cache_hit=payload.cache_hit,
        has_error=payload.has_error,
        started_after=payload.started_after,
        started_before=payload.started_before,
        min_latency_ms=payload.min_latency_ms,
        max_latency_ms=payload.max_latency_ms,
        min_tool_calls=payload.min_tool_calls,
        max_tool_calls=payload.max_tool_calls,
    )


def _trajectory_query_from_batch_payload(payload: Any) -> TrajectoryTurnQuery:
    return _trajectory_query_from_request(
        turn_ids=payload.turn_ids,
        request_id=payload.request_id,
        trace_id=payload.trace_id,
        thread_id=payload.thread_id,
        root_thread_id=payload.root_thread_id,
        parent_thread_id=payload.parent_thread_id,
        branch_id=payload.branch_id,
        branch_role=payload.branch_role,
        status=payload.status,
        scene=payload.scene,
        kind=payload.kind,
        tool=payload.tool,
        model=payload.model,
        fallback_used=payload.fallback_used,
        cache_hit=payload.cache_hit,
        has_error=payload.has_error,
        started_after=payload.started_after,
        started_before=payload.started_before,
        min_latency_ms=payload.min_latency_ms,
        max_latency_ms=payload.max_latency_ms,
        min_tool_calls=payload.min_tool_calls,
        max_tool_calls=payload.max_tool_calls,
        limit=payload.limit,
        offset=payload.offset,
        newest_first=payload.newest_first,
    )


def _export_trajectory_records(repo: Any, query: TrajectoryTurnQuery) -> list[dict[str, Any]]:
    export_turns = getattr(repo, "export_turns", None)
    if not callable(export_turns):
        raise HTTPException(
            status_code=503,
            detail="Trajectory batch observability requires a repository that can export turns.",
        )
    return [dict(record) for record in export_turns(query)]


def _build_batch_replay_summary(results: Sequence[TrajectoryReplayResponse]) -> TrajectoryBatchReplaySummaryResponse:
    return TrajectoryBatchReplaySummaryResponse(
        total=len(results),
        passed=sum(1 for item in results if item.comparison.replay_passed),
        failed=sum(1 for item in results if not item.comparison.replay_passed),
        source_failed=sum(1 for item in results if item.comparison.source_failed),
        tool_path_changed=sum(1 for item in results if item.comparison.tool_path_changed),
    )


def _trajectory_expected(settings: Settings | Any) -> bool:
    enabled = getattr(settings, "trajectory_enabled", None)
    database_uri = getattr(settings, "database_uri", None)
    if enabled is None:
        return bool(database_uri)
    return bool(enabled and database_uri)


def _build_runtime_readiness(runtime: AppRuntime | Any) -> RuntimeReadinessResponse:
    settings = getattr(runtime, "settings", None)
    otel_runtime = getattr(runtime, "otel_runtime", None)
    checks = [
        RuntimeComponentStatusResponse(
            name="graph",
            ready=getattr(runtime, "graph", None) is not None,
            detail="langgraph pipeline initialized" if getattr(runtime, "graph", None) is not None else "graph missing",
        ),
        RuntimeComponentStatusResponse(
            name="branch_repository",
            ready=getattr(runtime, "repo", None) is not None,
            detail="branch persistence ready" if getattr(runtime, "repo", None) is not None else "branch repository missing",
        ),
        RuntimeComponentStatusResponse(
            name="branch_service",
            ready=getattr(runtime, "branch_service", None) is not None,
            detail="branch service initialized" if getattr(runtime, "branch_service", None) is not None else "branch service missing",
        ),
        RuntimeComponentStatusResponse(
            name="tool_registry",
            ready=getattr(runtime, "tool_registry", None) is not None,
            detail="tool registry loaded" if getattr(runtime, "tool_registry", None) is not None else "tool registry missing",
        ),
        RuntimeComponentStatusResponse(
            name="skill_registry",
            ready=getattr(runtime, "skill_registry", None) is not None,
            detail="skill registry loaded" if getattr(runtime, "skill_registry", None) is not None else "skill registry missing",
        ),
    ]
    if getattr(settings, "database_uri", None):
        checks.append(
            RuntimeComponentStatusResponse(
                name="persistence_backend",
                ready=True,
                detail="postgres-primary",
            )
        )
    else:
        checks.append(
            RuntimeComponentStatusResponse(
                name="persistence_backend",
                ready=True,
                detail="local-fallback",
            )
        )

    tracing_enabled = bool(getattr(settings, "tracing_enabled", False))
    tracing_exporters = tuple(getattr(settings, "otel_traces_exporters", ()) or ())
    if tracing_enabled:
        if otel_runtime is not None:
            checks.append(
                RuntimeComponentStatusResponse(
                    name="tracing_exporter",
                    ready=bool(getattr(otel_runtime, "ready", False)),
                    detail=str(getattr(otel_runtime, "detail", "tracing exporter state unavailable")),
                )
            )
        elif tracing_exporters:
            checks.append(
                RuntimeComponentStatusResponse(
                    name="tracing_exporter",
                    ready=False,
                    detail="tracing exporters requested but runtime exporter state is missing",
                )
            )
        else:
            checks.append(
                RuntimeComponentStatusResponse(
                    name="tracing_exporter",
                    ready=True,
                    detail="tracing enabled without exporter",
                )
            )
    else:
        checks.append(
            RuntimeComponentStatusResponse(
                name="tracing_exporter",
                ready=True,
                detail="tracing disabled",
            )
        )

    trajectory_expected = _trajectory_expected(settings)
    trajectory_recorder = getattr(runtime, "trajectory_recorder", None)
    if trajectory_expected:
        checks.append(
            RuntimeComponentStatusResponse(
                name="trajectory_recorder",
                ready=trajectory_recorder is not None,
                detail=(
                    "trajectory recorder ready"
                    if trajectory_recorder is not None
                    else "trajectory recorder missing while trajectory persistence is configured"
                ),
            )
        )
    else:
        checks.append(
            RuntimeComponentStatusResponse(
                name="trajectory_recorder",
                ready=True,
                detail="trajectory persistence disabled",
            )
        )

    ready = all(check.ready for check in checks)
    return RuntimeReadinessResponse(
        status="ok" if ready else "degraded",
        ready=ready,
        app_version=getattr(settings, "app_version", None),
        environment=getattr(settings, "app_environment", None),
        deployment=getattr(settings, "deployment_name", None),
        checks=checks,
    )


def _maybe_get_trajectory_repository(runtime: AppRuntime | Any) -> PostgresTrajectoryRepository | Any | None:
    candidate = getattr(runtime, "trajectory_recorder", None)
    required_methods = ("list_turns", "get_turn", "list_steps_by_turn_ids", "get_turn_stats")
    if candidate is not None and all(callable(getattr(candidate, name, None)) for name in required_methods):
        return candidate
    database_uri = getattr(getattr(runtime, "settings", None), "database_uri", None)
    if database_uri:
        return PostgresTrajectoryRepository(database_uri)
    return None


def _agent_role_policy_response(settings: Settings | Any) -> AgentRolePolicyResponse:
    resolver = RoleModelResolver(settings)
    return AgentRolePolicyResponse(
        enabled=bool(getattr(settings, "agent_role_routing_enabled", False)),
        default_model=str(getattr(settings, "model", "")),
        helper_model=getattr(settings, "helper_model", None),
        max_parallel_runs=max(1, int(getattr(settings, "agent_role_max_parallel_runs", 1) or 1)),
        roles=[role.value for role in AgentRole],
        role_models={role.value: resolver.resolve(role) for role in AgentRole},
        fallback_order=[
            "role-specific model override",
            "executor selected model",
            "helper model for planning and critique roles",
            "default model",
        ],
    )


def _agent_delegation_policy_response(settings: Settings | Any) -> AgentDelegationPolicyResponse:
    return AgentDelegationPolicyResponse(
        enabled=bool(getattr(settings, "agent_delegation_enabled", False)),
        enforce=bool(getattr(settings, "agent_delegation_enforce", False)),
        max_parallel_runs=max(1, int(getattr(settings, "agent_role_max_parallel_runs", 1) or 1)),
    )


def _agent_model_router_policy_response(settings: Settings | Any) -> AgentModelRouterPolicyResponse:
    resolver = RoleModelResolver(settings)
    return AgentModelRouterPolicyResponse(
        enabled=bool(getattr(settings, "agent_model_router_enabled", False)),
        mode=str(getattr(settings, "agent_model_router_mode", "observe") or "observe"),
        default_model=str(getattr(settings, "model", "")),
        helper_model=getattr(settings, "helper_model", None),
        role_models={role.value: resolver.resolve(role) for role in AgentRole},
    )


def _agent_task_ledger_policy_response(settings: Settings | Any) -> AgentTaskLedgerPolicyResponse:
    return AgentTaskLedgerPolicyResponse(**build_task_ledger_policy(settings))


def _available_tool_names(runtime: AppRuntime | Any) -> list[str]:
    registry = getattr(runtime, "tool_registry", None)
    return [
        str(getattr(tool, "name", "")).strip()
        for tool in tuple(getattr(registry, "tools", ()) or ())
        if str(getattr(tool, "name", "")).strip()
    ]


def _role_route_decision_items(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in rows:
        plan_meta = dict(row.get("plan_meta") or {})
        role_route_plan = plan_meta.get("role_route_plan")
        if not isinstance(role_route_plan, dict):
            continue
        decisions = role_route_plan.get("decisions")
        if not isinstance(decisions, list):
            decisions = []
        items.append(
            {
                "turn_id": row.get("id"),
                "request_id": row.get("request_id"),
                "trace_id": row.get("trace_id"),
                "thread_id": row.get("thread_id"),
                "root_thread_id": row.get("root_thread_id"),
                "status": row.get("status"),
                "started_at": row.get("started_at"),
                "enabled": bool(role_route_plan.get("enabled", False)),
                "route_reason": role_route_plan.get("route_reason"),
                "max_parallel_runs": role_route_plan.get("max_parallel_runs"),
                "orchestrator_model_id": role_route_plan.get("orchestrator_model_id"),
                "role_count": len(decisions),
                "decisions": decisions,
            }
        )
    return items


def _plan_meta_items(rows: Sequence[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in rows:
        plan_meta = dict(row.get("plan_meta") or {})
        payload = plan_meta.get(key)
        if not isinstance(payload, dict):
            continue
        items.append(
            {
                "turn_id": row.get("id"),
                "request_id": row.get("request_id"),
                "trace_id": row.get("trace_id"),
                "thread_id": row.get("thread_id"),
                "root_thread_id": row.get("root_thread_id"),
                "status": row.get("status"),
                "started_at": row.get("started_at"),
                **payload,
            }
        )
    return items


def _list_plan_meta_decisions(
    *,
    runtime: AppRuntime | Any,
    key: str,
    limit: int,
) -> tuple[list[dict[str, Any]], bool, str | None]:
    repo = _maybe_get_trajectory_repository(runtime)
    if repo is None:
        return [], False, None
    try:
        rows = repo.list_turns(TrajectoryTurnQuery(limit=limit, newest_first=True))
    except Exception as exc:  # noqa: BLE001
        return [], False, str(exc)
    return _plan_meta_items(rows, key), True, None


def _list_plan_meta_list_items(
    *,
    runtime: AppRuntime | Any,
    key: str,
    limit: int,
) -> tuple[list[dict[str, Any]], bool, str | None]:
    repo = _maybe_get_trajectory_repository(runtime)
    if repo is None:
        return [], False, None
    try:
        rows = repo.list_turns(TrajectoryTurnQuery(limit=limit, newest_first=True))
    except Exception as exc:  # noqa: BLE001
        return [], False, str(exc)
    items: list[dict[str, Any]] = []
    for row in rows:
        plan_meta = dict(row.get("plan_meta") or {})
        payload: Any = plan_meta
        for part in key.split("."):
            payload = payload.get(part) if isinstance(payload, dict) else None
        if not isinstance(payload, list):
            continue
        for raw in payload:
            if not isinstance(raw, dict):
                continue
            items.append(
                {
                    "turn_id": row.get("id"),
                    "request_id": row.get("request_id"),
                    "trace_id": row.get("trace_id"),
                    "thread_id": row.get("thread_id"),
                    "root_thread_id": row.get("root_thread_id"),
                    "status": row.get("status"),
                    "started_at": row.get("started_at"),
                    **raw,
                }
            )
    return items[:limit], True, None


def _escape_prometheus_label_value(value: Any) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _prometheus_metric_line(name: str, value: int | float, labels: dict[str, Any] | None = None) -> str:
    if labels:
        rendered = ",".join(
            f'{key}="{_escape_prometheus_label_value(label_value)}"'
            for key, label_value in labels.items()
            if label_value is not None
        )
        return f"{name}{{{rendered}}} {value}"
    return f"{name} {value}"


def _build_prometheus_metrics_payload(
    *,
    runtime_status: RuntimeReadinessResponse,
    trajectory_stats: dict[str, Any] | None,
    trajectory_available: bool,
    agent_governance_metrics: dict[str, int] | None = None,
) -> str:
    lines = [
        "# HELP focus_agent_runtime_ready Whether the application runtime is ready to serve traffic.",
        "# TYPE focus_agent_runtime_ready gauge",
        _prometheus_metric_line("focus_agent_runtime_ready", 1 if runtime_status.ready else 0),
    ]
    lines.extend(
        [
            "# HELP focus_agent_runtime_build_info Build metadata for the running service.",
            "# TYPE focus_agent_runtime_build_info gauge",
            _prometheus_metric_line(
                "focus_agent_runtime_build_info",
                1,
                labels={
                    "version": runtime_status.app_version or "unknown",
                    "environment": runtime_status.environment or "unknown",
                    "deployment": runtime_status.deployment or "unknown",
                },
            ),
            "# HELP focus_agent_runtime_component_ready Per-component readiness for the running service.",
            "# TYPE focus_agent_runtime_component_ready gauge",
        ]
    )
    for check in runtime_status.checks:
        lines.append(
            _prometheus_metric_line(
                "focus_agent_runtime_component_ready",
                1 if check.ready else 0,
                labels={"component": check.name, "detail": check.detail or ""},
            )
        )

    lines.extend(
        [
            "# HELP focus_agent_trajectory_metrics_available Whether trajectory metrics were available for this scrape.",
            "# TYPE focus_agent_trajectory_metrics_available gauge",
            _prometheus_metric_line("focus_agent_trajectory_metrics_available", 1 if trajectory_available else 0),
        ]
    )
    if not trajectory_available or not trajectory_stats:
        lines.extend(_agent_governance_metric_lines(agent_governance_metrics or {}))
        return "\n".join(lines) + "\n"

    overview = trajectory_stats.get("overview") or {}
    lines.extend(
        [
            "# HELP focus_agent_trajectory_turn_count Total recorded trajectory turns in the selected scope.",
            "# TYPE focus_agent_trajectory_turn_count gauge",
            _prometheus_metric_line("focus_agent_trajectory_turn_count", int(overview.get("turn_count") or 0)),
            "# HELP focus_agent_trajectory_non_succeeded_count Total non-succeeded trajectory turns in the selected scope.",
            "# TYPE focus_agent_trajectory_non_succeeded_count gauge",
            _prometheus_metric_line(
                "focus_agent_trajectory_non_succeeded_count",
                int(overview.get("non_succeeded_count") or 0),
            ),
            "# HELP focus_agent_trajectory_avg_latency_ms Average end-to-end turn latency in milliseconds.",
            "# TYPE focus_agent_trajectory_avg_latency_ms gauge",
            _prometheus_metric_line(
                "focus_agent_trajectory_avg_latency_ms",
                float(overview.get("avg_latency_ms") or 0.0),
            ),
            "# HELP focus_agent_trajectory_max_latency_ms Maximum end-to-end turn latency in milliseconds.",
            "# TYPE focus_agent_trajectory_max_latency_ms gauge",
            _prometheus_metric_line(
                "focus_agent_trajectory_max_latency_ms",
                float(overview.get("max_latency_ms") or 0.0),
            ),
            "# HELP focus_agent_trajectory_total_tool_calls Total tool invocations across recorded turns.",
            "# TYPE focus_agent_trajectory_total_tool_calls gauge",
            _prometheus_metric_line(
                "focus_agent_trajectory_total_tool_calls",
                int(overview.get("total_tool_calls") or 0),
            ),
            "# HELP focus_agent_trajectory_total_fallback_uses Total fallback tool executions across recorded turns.",
            "# TYPE focus_agent_trajectory_total_fallback_uses gauge",
            _prometheus_metric_line(
                "focus_agent_trajectory_total_fallback_uses",
                int(overview.get("total_fallback_uses") or 0),
            ),
            "# HELP focus_agent_trajectory_turns_by_status Turn counts grouped by trajectory status.",
            "# TYPE focus_agent_trajectory_turns_by_status gauge",
        ]
    )
    for row in trajectory_stats.get("by_status") or []:
        lines.append(
            _prometheus_metric_line(
                "focus_agent_trajectory_turns_by_status",
                int(row.get("turn_count") or 0),
                labels={"status": row.get("key") or "unknown"},
            )
        )
    lines.extend(_agent_governance_metric_lines(agent_governance_metrics or {}))
    return "\n".join(lines) + "\n"


def _agent_governance_metric_lines(metrics: dict[str, int]) -> list[str]:
    return [
        "# HELP focus_agent_memory_promotion_count Total memory promotions observed in trajectory plan_meta.",
        "# TYPE focus_agent_memory_promotion_count gauge",
        _prometheus_metric_line("focus_agent_memory_promotion_count", int(metrics.get("memory_promotions") or 0)),
        "# HELP focus_agent_memory_conflict_count Total memory curator conflicts observed in trajectory plan_meta.",
        "# TYPE focus_agent_memory_conflict_count gauge",
        _prometheus_metric_line("focus_agent_memory_conflict_count", int(metrics.get("memory_conflicts") or 0)),
        "# HELP focus_agent_tool_router_denied_count Total denied tools observed in tool_route_plan records.",
        "# TYPE focus_agent_tool_router_denied_count gauge",
        _prometheus_metric_line("focus_agent_tool_router_denied_count", int(metrics.get("tool_router_denied") or 0)),
        "# HELP focus_agent_tool_router_enforced_count Total enforced tool_route_plan records.",
        "# TYPE focus_agent_tool_router_enforced_count gauge",
        _prometheus_metric_line("focus_agent_tool_router_enforced_count", int(metrics.get("tool_router_enforced") or 0)),
        "# HELP focus_agent_delegation_run_count Total delegated agent runs observed in trajectory plan_meta.",
        "# TYPE focus_agent_delegation_run_count gauge",
        _prometheus_metric_line("focus_agent_delegation_run_count", int(metrics.get("agent_delegation_runs") or 0)),
        "# HELP focus_agent_critic_reject_count Total critic rejection failures observed in trajectory plan_meta.",
        "# TYPE focus_agent_critic_reject_count gauge",
        _prometheus_metric_line("focus_agent_critic_reject_count", int(metrics.get("critic_rejects") or 0)),
        "# HELP focus_agent_review_pending_count Pending agent review queue items observed in trajectory plan_meta.",
        "# TYPE focus_agent_review_pending_count gauge",
        _prometheus_metric_line("focus_agent_review_pending_count", int(metrics.get("agent_review_pending") or 0)),
        "# HELP focus_agent_model_router_fallback_count Model Router fallback events observed in trajectory plan_meta.",
        "# TYPE focus_agent_model_router_fallback_count gauge",
        _prometheus_metric_line("focus_agent_model_router_fallback_count", int(metrics.get("model_router_fallback") or 0)),
        "# HELP focus_agent_failure_count Agent failure records observed in trajectory plan_meta.",
        "# TYPE focus_agent_failure_count gauge",
        _prometheus_metric_line("focus_agent_failure_count", int(metrics.get("agent_failures") or 0)),
        "# HELP focus_agent_context_artifact_ref_count Context Engineering artifact refs observed in trajectory plan_meta.",
        "# TYPE focus_agent_context_artifact_ref_count gauge",
        _prometheus_metric_line("focus_agent_context_artifact_ref_count", int(metrics.get("context_artifact_refs") or 0)),
        "# HELP focus_agent_context_over_budget_count Context Engineering over-budget decisions observed in trajectory plan_meta.",
        "# TYPE focus_agent_context_over_budget_count gauge",
        _prometheus_metric_line("focus_agent_context_over_budget_count", int(metrics.get("context_over_budget") or 0)),
        "# HELP focus_agent_task_ledger_task_count Agent Task Ledger tasks observed in trajectory plan_meta.",
        "# TYPE focus_agent_task_ledger_task_count gauge",
        _prometheus_metric_line("focus_agent_task_ledger_task_count", int(metrics.get("agent_task_ledger_tasks") or 0)),
        "# HELP focus_agent_delegated_artifact_count Delegated artifacts observed in trajectory plan_meta.",
        "# TYPE focus_agent_delegated_artifact_count gauge",
        _prometheus_metric_line("focus_agent_delegated_artifact_count", int(metrics.get("delegated_artifacts") or 0)),
        "# HELP focus_agent_critic_gate_rejected_count Rejected artifacts observed in critic gate results.",
        "# TYPE focus_agent_critic_gate_rejected_count gauge",
        _prometheus_metric_line("focus_agent_critic_gate_rejected_count", int(metrics.get("critic_gate_rejected") or 0)),
    ]


def _agent_governance_metrics_from_turns(rows: Sequence[dict[str, Any]]) -> dict[str, int]:
    metrics = {
        "memory_promotions": 0,
        "memory_conflicts": 0,
        "tool_router_denied": 0,
        "tool_router_enforced": 0,
        "agent_delegation_runs": 0,
        "critic_rejects": 0,
        "agent_review_pending": 0,
        "model_router_fallback": 0,
        "agent_failures": 0,
        "context_artifact_refs": 0,
        "context_over_budget": 0,
        "agent_task_ledger_tasks": 0,
        "delegated_artifacts": 0,
        "critic_gate_rejected": 0,
    }
    for row in rows:
        plan_meta = dict(row.get("plan_meta") or {})
        memory_decision = plan_meta.get("memory_curator_decision")
        if isinstance(memory_decision, dict):
            metrics["memory_promotions"] += len(memory_decision.get("promoted_memory_ids") or [])
            metrics["memory_conflicts"] += len(memory_decision.get("conflicts") or [])
        tool_plan = plan_meta.get("tool_route_plan")
        if isinstance(tool_plan, dict):
            metrics["tool_router_denied"] += len(tool_plan.get("denied_tools") or [])
            metrics["tool_router_enforced"] += 1 if tool_plan.get("enforce") else 0
        delegation_plan = plan_meta.get("agent_delegation_plan")
        if isinstance(delegation_plan, dict):
            metrics["agent_delegation_runs"] += len(delegation_plan.get("runs") or [])
        model_decision = plan_meta.get("model_route_decision")
        if isinstance(model_decision, dict):
            metrics["model_router_fallback"] += 1 if model_decision.get("fallback_used") else 0
        failures = plan_meta.get("agent_failure_records")
        if isinstance(failures, list):
            metrics["agent_failures"] += len(failures)
            metrics["critic_rejects"] += len(
                [item for item in failures if isinstance(item, dict) and item.get("failure_type") == "critic_rejected"]
            )
        review_queue = plan_meta.get("agent_review_queue")
        if isinstance(review_queue, list):
            metrics["agent_review_pending"] += len(
                [item for item in review_queue if isinstance(item, dict) and item.get("status") == "pending"]
            )
        context_refs = plan_meta.get("context_artifact_refs")
        if isinstance(context_refs, list):
            metrics["context_artifact_refs"] += len(context_refs)
        context_budget = plan_meta.get("context_budget_decision")
        if isinstance(context_budget, dict):
            metrics["context_over_budget"] += 1 if int(context_budget.get("over_budget_chars") or 0) > 0 else 0
        task_ledger = plan_meta.get("agent_task_ledger")
        if isinstance(task_ledger, dict):
            metrics["agent_task_ledger_tasks"] += len(task_ledger.get("tasks") or [])
        delegated_artifacts = plan_meta.get("delegated_artifacts")
        if isinstance(delegated_artifacts, list):
            metrics["delegated_artifacts"] += len(delegated_artifacts)
        critic_gate = plan_meta.get("critic_gate_result")
        if isinstance(critic_gate, dict):
            metrics["critic_gate_rejected"] += len(critic_gate.get("rejected_artifact_ids") or [])
    return metrics


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    runtime = create_runtime(Settings.from_env())
    app.state.runtime = runtime
    app.state.chat_service = ChatService(runtime)
    try:
        yield
    finally:
        runtime.close()


def _event_stream_response(stream: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(
        stream,
        media_type='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',
        },
    )


def _render_frontend_or_raise(*, settings: Settings) -> str:
    try:
        return render_frontend_entry_html(settings=settings)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Frontend build is missing. Run `pnpm web:build` or `make web-build` "
                "before opening /app."
            ),
        ) from exc


def _frontend_dev_redirect(
    *,
    settings: Settings,
    path: str = "",
    query: str = "",
) -> RedirectResponse | None:
    target = build_frontend_dev_server_redirect_url(settings=settings, path=path, query=query)
    if target is None:
        return None
    return RedirectResponse(url=target, status_code=307)



__all__ = [name for name in globals() if not name.startswith("__")]
