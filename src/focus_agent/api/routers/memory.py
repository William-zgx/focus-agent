from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from focus_agent.engine.runtime import AppRuntime
from focus_agent.memory import MemoryService
from focus_agent.repositories.memory_repository import MemoryListQuery
from focus_agent.security.permissions import AuthContext

from ..contracts import (
    ForgetMemoryRecordRequest,
    ForgetMemoryRecordResponse,
    MemoryAuditEventListResponse,
    MemoryAuditEventResponse,
    MemoryCandidateListResponse,
    MemoryCandidateResponse,
    MemoryRecordDetailResponse,
    MemoryRecordListResponse,
    MemoryRecordResponse,
    MemoryUsageEvidenceResponse,
    MemoryUsageResponse,
)
from ..deps import get_app_runtime, get_current_auth_context
from ..route_utils.agent_governance_operations import _governance_repository
from ..route_utils.memory_access import (
    _auth_enabled,
    _branch_owner_matches,
    _can_access_audit_event,
    _can_access_branch_memory,
    _can_access_candidate,
    _can_access_memory_record,
    _can_access_owned_memory_record,
    _can_access_record_fields,
    _can_access_thread_memory,
    _can_forget_memory_record,
    _effective_user_id_filter,
    _get_access_checked_record,
    _get_forget_checked_record,
    _has_global_memory_access,
    _has_global_memory_audit_access,
    _has_global_memory_forget_access,
    _has_memory_permission,
    _has_thread_owner_checker,
    _is_branch_owner,
    _is_thread_owner,
    _memory_repository,
    _parse_namespace,
    _thread_owner_matches,
)
from ..route_utils.memory_responses import (
    _audit_event_response,
    _candidate_response,
    _dt,
    _embedding_metadata_payload,
    _embedding_response_metadata,
    _memory_list_contains,
    _memory_record_response,
    _memory_usage_response,
    _model_payload,
    _value,
    _without_embedding_vectors,
)

router = APIRouter()


@router.get("/v1/memory", response_model=MemoryRecordListResponse)
def list_memory(
    namespace: list[str] | None = Query(default=None),
    kind: str | None = Query(default=None),
    scope: str | None = Query(default=None),
    visibility: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    user_id: str | None = Query(default=None),
    root_thread_id: str | None = Query(default=None),
    source_thread_id: str | None = Query(default=None),
    source_branch_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    auth: AuthContext = Depends(get_current_auth_context),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> MemoryRecordListResponse:
    repository = _memory_repository(runtime)
    if repository is None:
        return MemoryRecordListResponse(
            items=[],
            count=0,
            available=False,
            backend="local_fallback",
            filters={},
            limit=limit,
            offset=offset,
        )
    effective_user_id = _effective_user_id_filter(
        user_id=user_id,
        auth=auth,
        runtime=runtime,
        root_thread_id=root_thread_id,
        source_thread_id=source_thread_id,
        source_branch_id=source_branch_id,
    )
    query = MemoryListQuery(
        namespace=_parse_namespace(namespace),
        kind=kind,
        scope=scope,
        visibility=visibility,
        status=status_filter,
        user_id=effective_user_id,
        root_thread_id=root_thread_id,
        source_thread_id=source_thread_id,
        source_branch_id=source_branch_id,
        limit=limit,
        offset=offset,
    )
    items = [
        _memory_record_response(item, repository=repository)
        for item in repository.list_records(query)
        if _can_access_memory_record(item, auth=auth, runtime=runtime)
    ]
    filters = {
        "namespace": list(query.namespace) if query.namespace else None,
        "kind": kind,
        "scope": scope,
        "visibility": visibility,
        "status": status_filter,
        "user_id": query.user_id,
        "root_thread_id": root_thread_id,
        "source_thread_id": source_thread_id,
        "source_branch_id": source_branch_id,
    }
    return MemoryRecordListResponse(items=items, count=len(items), filters=filters, limit=limit, offset=offset)


@router.get("/v1/memory/audit", response_model=MemoryAuditEventListResponse)
def list_memory_audit(
    memory_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    auth: AuthContext = Depends(get_current_auth_context),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> MemoryAuditEventListResponse:
    repository = _memory_repository(runtime)
    if repository is None:
        return MemoryAuditEventListResponse(
            items=[],
            count=0,
            available=False,
            backend="local_fallback",
            filters={"memory_id": memory_id},
            limit=limit,
        )
    if memory_id is not None:
        _get_access_checked_record(
            repository=repository,
            memory_id=memory_id,
            auth=auth,
            runtime=runtime,
        )
    audit_user_id = None if _has_global_memory_audit_access(auth=auth, runtime=runtime) else auth.principal.user_id
    items = [
        _audit_event_response(item)
        for item in repository.list_audit_events(
            memory_id=memory_id,
            user_id=audit_user_id,
            limit=limit,
        )
        if _can_access_audit_event(item, repository=repository, auth=auth, runtime=runtime)
    ]
    return MemoryAuditEventListResponse(
        items=items,
        count=len(items),
        filters={"memory_id": memory_id},
        limit=limit,
    )


@router.get("/v1/memory/{memory_id}/audit", response_model=MemoryAuditEventListResponse)
def list_memory_record_audit(
    memory_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    auth: AuthContext = Depends(get_current_auth_context),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> MemoryAuditEventListResponse:
    return list_memory_audit(memory_id=memory_id, limit=limit, auth=auth, runtime=runtime)


@router.get("/v1/memory/{memory_id}/usage", response_model=MemoryUsageResponse)
def list_memory_usage(
    memory_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    auth: AuthContext = Depends(get_current_auth_context),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> MemoryUsageResponse:
    repository = _memory_repository(runtime)
    if repository is None:
        return MemoryUsageResponse(
            memory_id=memory_id,
            items=[],
            count=0,
            limit=limit,
            available=False,
            backend="local_fallback",
            error="Postgres memory repository is not configured.",
        )
    _get_access_checked_record(
        repository=repository,
        memory_id=memory_id,
        auth=auth,
        runtime=runtime,
    )
    governance_repository = _governance_repository(runtime)
    user_id = None if _has_global_memory_access(auth=auth, runtime=runtime) else auth.principal.user_id
    evidence_rows = governance_repository.list_context_evidence(
        memory_id=memory_id,
        user_id=user_id,
        limit=limit,
    )
    items = [_memory_usage_response(memory_id=memory_id, evidence=evidence) for evidence in evidence_rows]
    return MemoryUsageResponse(memory_id=memory_id, items=items, count=len(items), limit=limit)


@router.get("/v1/memory/candidates", response_model=MemoryCandidateListResponse)
def list_memory_candidates(
    status_filter: str | None = Query(default=None, alias="status"),
    root_thread_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    auth: AuthContext = Depends(get_current_auth_context),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> MemoryCandidateListResponse:
    repository = _memory_repository(runtime)
    if repository is None:
        return MemoryCandidateListResponse(
            items=[],
            count=0,
            available=False,
            backend="local_fallback",
            filters={"status": status_filter, "root_thread_id": root_thread_id},
            limit=limit,
        )
    candidate_user_id = None if _has_global_memory_audit_access(auth=auth, runtime=runtime) else auth.principal.user_id
    items = [
        _candidate_response(item)
        for item in repository.list_candidates(
            status=status_filter,
            root_thread_id=root_thread_id,
            user_id=candidate_user_id,
            limit=limit,
        )
        if _can_access_candidate(item, auth=auth, runtime=runtime)
    ]
    return MemoryCandidateListResponse(
        items=items,
        count=len(items),
        filters={"status": status_filter, "root_thread_id": root_thread_id},
        limit=limit,
    )


@router.get("/v1/memory/{memory_id}", response_model=MemoryRecordDetailResponse)
def get_memory(
    memory_id: str,
    auth: AuthContext = Depends(get_current_auth_context),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> MemoryRecordDetailResponse:
    repository = _memory_repository(runtime)
    if repository is None:
        return MemoryRecordDetailResponse(item=None, available=False, backend="local_fallback")
    item = _get_access_checked_record(
        repository=repository,
        memory_id=memory_id,
        auth=auth,
        runtime=runtime,
    )
    return MemoryRecordDetailResponse(item=_memory_record_response(item, repository=repository))


@router.post("/v1/memory/{memory_id}/forget", response_model=ForgetMemoryRecordResponse)
def forget_memory(
    memory_id: str,
    payload: ForgetMemoryRecordRequest | None = None,
    auth: AuthContext = Depends(get_current_auth_context),
    runtime: AppRuntime = Depends(get_app_runtime),
) -> ForgetMemoryRecordResponse:
    repository = _memory_repository(runtime)
    if repository is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Postgres memory repository is not configured.",
        )
    _get_forget_checked_record(
        repository=repository,
        memory_id=memory_id,
        auth=auth,
        runtime=runtime,
    )
    request = payload or ForgetMemoryRecordRequest()
    decision = MemoryService(repository=repository).forget(
        memory_id=memory_id,
        namespace=_parse_namespace(request.namespace),
        actor=auth.principal.user_id,
        reason=request.reason,
    )
    return ForgetMemoryRecordResponse(
        memory_id=memory_id,
        forgotten=decision.status.value == "forgotten",
        status=decision.status.value,
        tombstone_id=decision.tombstone_id,
        audit_id=decision.audit_id,
        decision=decision.model_dump(mode="json"),
    )


__all__ = [
    "MemoryAuditEventResponse",
    "MemoryCandidateResponse",
    "MemoryRecordResponse",
    "MemoryUsageEvidenceResponse",
    "_auth_enabled",
    "_audit_event_response",
    "_branch_owner_matches",
    "_can_access_audit_event",
    "_can_access_branch_memory",
    "_can_access_candidate",
    "_can_access_memory_record",
    "_can_access_owned_memory_record",
    "_can_access_record_fields",
    "_can_access_thread_memory",
    "_can_forget_memory_record",
    "_candidate_response",
    "_dt",
    "_effective_user_id_filter",
    "_embedding_metadata_payload",
    "_embedding_response_metadata",
    "_get_access_checked_record",
    "_get_forget_checked_record",
    "_has_global_memory_access",
    "_has_global_memory_audit_access",
    "_has_global_memory_forget_access",
    "_has_memory_permission",
    "_has_thread_owner_checker",
    "_is_branch_owner",
    "_is_thread_owner",
    "_memory_list_contains",
    "_memory_record_response",
    "_memory_repository",
    "_memory_usage_response",
    "_model_payload",
    "_parse_namespace",
    "_thread_owner_matches",
    "_value",
    "_without_embedding_vectors",
    "router",
]
