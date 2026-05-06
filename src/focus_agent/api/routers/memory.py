from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from focus_agent.engine.runtime import AppRuntime
from focus_agent.memory import MemoryAuditEvent, MemoryCandidate, MemoryRecord, MemoryService
from focus_agent.memory.models import MemoryScope
from focus_agent.repositories.memory_repository import MemoryListQuery, MemoryRepository
from focus_agent.security.permissions import AuthContext

from ..contracts import (
    MemoryAuditEventResponse,
    MemoryAuditEventListResponse,
    MemoryCandidateListResponse,
    MemoryCandidateResponse,
    MemoryRecordDetailResponse,
    ForgetMemoryRecordRequest,
    ForgetMemoryRecordResponse,
    MemoryRecordListResponse,
    MemoryRecordResponse,
)
from ..deps import get_app_runtime, get_current_auth_context

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
        _memory_record_response(item)
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
    return MemoryRecordDetailResponse(item=_memory_record_response(item))


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


def _memory_repository(runtime: AppRuntime) -> MemoryRepository | None:
    return getattr(runtime, "memory_repository", None)


def _auth_enabled(runtime: AppRuntime) -> bool:
    settings = getattr(runtime, "settings", None)
    return bool(getattr(settings, "auth_enabled", False))


def _has_memory_permission(auth: AuthContext, permission: str) -> bool:
    return permission in auth.permissions


def _has_global_memory_access(*, auth: AuthContext, runtime: AppRuntime) -> bool:
    if not _auth_enabled(runtime):
        return True
    return _has_memory_permission(auth, "memory:read")


def _has_global_memory_audit_access(*, auth: AuthContext, runtime: AppRuntime) -> bool:
    if not _auth_enabled(runtime):
        return True
    return _has_memory_permission(auth, "memory:audit")


def _has_global_memory_forget_access(*, auth: AuthContext, runtime: AppRuntime) -> bool:
    if not _auth_enabled(runtime):
        return True
    return _has_memory_permission(auth, "memory:forget")


def _effective_user_id_filter(
    *,
    user_id: str | None,
    auth: AuthContext,
    runtime: AppRuntime,
    root_thread_id: str | None = None,
    source_thread_id: str | None = None,
    source_branch_id: str | None = None,
) -> str | None:
    if _has_global_memory_access(auth=auth, runtime=runtime):
        return user_id
    principal_user_id = auth.principal.user_id
    if user_id is not None and user_id != principal_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot access another user's memory.",
        )
    if root_thread_id or source_thread_id:
        for thread_id in (root_thread_id, source_thread_id):
            thread_owner_matches = (
                _thread_owner_matches(thread_id, user_id=principal_user_id, runtime=runtime)
                if thread_id is not None
                else None
            )
            if thread_owner_matches is False:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Cannot access another user's memory.",
                )
        return user_id if _has_thread_owner_checker(runtime) else principal_user_id
    if source_branch_id is not None:
        branch_owner_matches = _branch_owner_matches(
            source_branch_id, user_id=principal_user_id, runtime=runtime
        )
        if branch_owner_matches is False:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot access another user's memory.",
            )
        return user_id if branch_owner_matches is True else principal_user_id
    return principal_user_id


def _can_access_memory_record(
    record: MemoryRecord,
    *,
    auth: AuthContext,
    runtime: AppRuntime,
) -> bool:
    if _has_global_memory_access(auth=auth, runtime=runtime):
        return True
    return _can_access_owned_memory_record(record, auth=auth, runtime=runtime)


def _can_access_owned_memory_record(
    record: MemoryRecord,
    *,
    auth: AuthContext,
    runtime: AppRuntime,
) -> bool:
    principal_user_id = auth.principal.user_id
    scope = _value(record.scope)
    if scope == MemoryScope.USER.value:
        return record.user_id == principal_user_id
    if scope == MemoryScope.ROOT_THREAD.value:
        return _can_access_thread_memory(record, user_id=principal_user_id, runtime=runtime)
    if scope == MemoryScope.BRANCH.value:
        return _can_access_branch_memory(record, user_id=principal_user_id, runtime=runtime)
    if scope == MemoryScope.PROJECT.value:
        return record.user_id == principal_user_id
    return record.user_id == principal_user_id


def _can_access_audit_event(
    event: MemoryAuditEvent,
    *,
    repository: MemoryRepository,
    auth: AuthContext,
    runtime: AppRuntime,
) -> bool:
    if _has_global_memory_audit_access(auth=auth, runtime=runtime):
        return True
    if event.memory_id:
        record = repository.get_record(event.memory_id)
        if record is not None:
            return _can_access_memory_record(record, auth=auth, runtime=runtime)
    principal_user_id = auth.principal.user_id
    if event.user_id == principal_user_id:
        return True
    if event.root_thread_id and _is_thread_owner(
        event.root_thread_id, user_id=principal_user_id, runtime=runtime
    ):
        return True
    if event.source_thread_id and _is_thread_owner(
        event.source_thread_id, user_id=principal_user_id, runtime=runtime
    ):
        return True
    if event.source_branch_id and _is_branch_owner(
        event.source_branch_id, user_id=principal_user_id, runtime=runtime
    ):
        return True
    return False


def _can_access_candidate(
    candidate: MemoryCandidate,
    *,
    auth: AuthContext,
    runtime: AppRuntime,
) -> bool:
    if _has_global_memory_audit_access(auth=auth, runtime=runtime):
        return True
    principal_user_id = auth.principal.user_id
    if candidate.user_id == principal_user_id:
        return True
    if candidate.root_thread_id and _is_thread_owner(
        candidate.root_thread_id, user_id=principal_user_id, runtime=runtime
    ):
        return True
    if candidate.branch_id and _is_branch_owner(
        candidate.branch_id, user_id=principal_user_id, runtime=runtime
    ):
        return True
    record = candidate.record
    return _can_access_record_fields(
        scope=_value(record.scope),
        user_id=record.user_id,
        root_thread_id=record.root_thread_id,
        source_thread_id=record.source_thread_id,
        source_branch_id=record.source_branch_id,
        principal_user_id=principal_user_id,
        runtime=runtime,
    )


def _get_access_checked_record(
    *,
    repository: MemoryRepository,
    memory_id: str,
    auth: AuthContext,
    runtime: AppRuntime,
) -> MemoryRecord:
    record = repository.get_record(memory_id)
    if record is None or not _can_access_memory_record(record, auth=auth, runtime=runtime):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found.")
    return record


def _get_forget_checked_record(
    *,
    repository: MemoryRepository,
    memory_id: str,
    auth: AuthContext,
    runtime: AppRuntime,
) -> MemoryRecord:
    record = repository.get_record(memory_id)
    if record is None or not _can_forget_memory_record(record, auth=auth, runtime=runtime):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found.")
    return record


def _can_forget_memory_record(
    record: MemoryRecord,
    *,
    auth: AuthContext,
    runtime: AppRuntime,
) -> bool:
    if _has_global_memory_forget_access(auth=auth, runtime=runtime):
        return True
    return _can_access_owned_memory_record(record, auth=auth, runtime=runtime)


def _can_access_thread_memory(
    record: MemoryRecord,
    *,
    user_id: str,
    runtime: AppRuntime,
) -> bool:
    thread_ids = (record.root_thread_id, record.source_thread_id)
    checked = False
    for thread_id in thread_ids:
        if thread_id is None:
            continue
        checked = True
        if _thread_owner_matches(thread_id, user_id=user_id, runtime=runtime):
            return True
    if checked and _has_thread_owner_checker(runtime):
        return False
    return record.user_id == user_id


def _can_access_branch_memory(
    record: MemoryRecord,
    *,
    user_id: str,
    runtime: AppRuntime,
) -> bool:
    if record.source_branch_id is not None:
        branch_owner_matches = _branch_owner_matches(
            record.source_branch_id, user_id=user_id, runtime=runtime
        )
        if branch_owner_matches is not None:
            return branch_owner_matches
        return record.user_id == user_id
    return _can_access_thread_memory(record, user_id=user_id, runtime=runtime) or record.user_id == user_id


def _can_access_record_fields(
    *,
    scope: str | None,
    user_id: str | None,
    root_thread_id: str | None,
    source_thread_id: str | None,
    source_branch_id: str | None,
    principal_user_id: str,
    runtime: AppRuntime,
) -> bool:
    if scope == MemoryScope.USER.value:
        return user_id == principal_user_id
    if scope == MemoryScope.ROOT_THREAD.value:
        for thread_id in (root_thread_id, source_thread_id):
            if thread_id and _thread_owner_matches(
                thread_id, user_id=principal_user_id, runtime=runtime
            ):
                return True
        if (root_thread_id or source_thread_id) and _has_thread_owner_checker(runtime):
            return False
        return user_id == principal_user_id
    if scope == MemoryScope.BRANCH.value:
        if source_branch_id:
            branch_owner_matches = _branch_owner_matches(
                source_branch_id, user_id=principal_user_id, runtime=runtime
            )
            if branch_owner_matches is not None:
                return branch_owner_matches
        return user_id == principal_user_id
    if scope == MemoryScope.PROJECT.value:
        return user_id == principal_user_id
    return user_id == principal_user_id


def _is_thread_owner(thread_id: str, *, user_id: str, runtime: AppRuntime) -> bool:
    return bool(_thread_owner_matches(thread_id, user_id=user_id, runtime=runtime))


def _has_thread_owner_checker(runtime: AppRuntime) -> bool:
    branch_repo = getattr(runtime, "repo", None)
    assert_thread_owner = getattr(branch_repo, "assert_thread_owner", None)
    return callable(assert_thread_owner)


def _thread_owner_matches(thread_id: str, *, user_id: str, runtime: AppRuntime) -> bool | None:
    branch_repo = getattr(runtime, "repo", None)
    assert_thread_owner = getattr(branch_repo, "assert_thread_owner", None)
    if not callable(assert_thread_owner):
        return None
    try:
        assert_thread_owner(thread_id=thread_id, owner_user_id=user_id)
    except (KeyError, PermissionError):
        return False
    return True


def _is_branch_owner(branch_id: str, *, user_id: str, runtime: AppRuntime) -> bool:
    return bool(_branch_owner_matches(branch_id, user_id=user_id, runtime=runtime))


def _branch_owner_matches(branch_id: str, *, user_id: str, runtime: AppRuntime) -> bool | None:
    branch_repo = getattr(runtime, "repo", None)
    get_branch = getattr(branch_repo, "get", None)
    if callable(get_branch):
        try:
            branch = get_branch(branch_id)
        except (KeyError, PermissionError):
            return False
        owner_user_id = getattr(branch, "owner_user_id", None)
        if owner_user_id is not None:
            return owner_user_id == user_id
    return None


def _parse_namespace(value: str | Sequence[str] | None) -> tuple[str, ...] | None:
    if not value:
        return None
    raw_values = [value] if isinstance(value, str) else list(value)
    parts: list[str] = []
    for raw_value in raw_values:
        parts.extend(
            part.strip()
            for part in str(raw_value).replace("/", ",").split(",")
            if part.strip()
        )
    return tuple(parts) if parts else None


def _dt(value: object) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value)


def _value(value: object) -> str | None:
    if value is None:
        return None
    resolved = value.value if hasattr(value, "value") else value
    return str(resolved)


def _model_payload(value: object) -> dict[str, Any]:
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    if isinstance(value, dict):
        return dict(value)
    return {}


def _memory_record_response(record: MemoryRecord) -> MemoryRecordResponse:
    payload_redacted = _value(record.status) == "forgotten" or record.deleted_at is not None
    return MemoryRecordResponse(
        memory_id=record.memory_id,
        kind=_value(record.kind),
        scope=_value(record.scope),
        visibility=_value(record.visibility),
        status=_value(record.status),
        namespace=list(record.namespace),
        content="" if payload_redacted else record.content,
        summary="[forgotten]" if payload_redacted else record.summary,
        tags=list(record.tags),
        evidence_refs=list(record.evidence_refs),
        source_thread_id=record.source_thread_id,
        source_branch_id=record.source_branch_id,
        root_thread_id=record.root_thread_id,
        user_id=record.user_id,
        confidence=record.confidence,
        importance=record.importance,
        promoted_to_main=record.promoted_to_main,
        semantic_key=record.semantic_key,
        fingerprint=record.fingerprint,
        created_at=_dt(record.created_at),
        updated_at=_dt(record.updated_at),
        deleted_at=_dt(record.deleted_at),
        payload_redacted=payload_redacted,
    )


def _audit_event_response(event: MemoryAuditEvent) -> MemoryAuditEventResponse:
    decision = event.decision.value if hasattr(event.decision, "value") else str(event.decision)
    return MemoryAuditEventResponse(
        event_id=event.event_id,
        action=event.action,
        decision=decision,
        memory_id=event.memory_id,
        candidate_id=event.candidate_id,
        actor=event.actor,
        reason=event.reason,
        namespace=list(event.namespace),
        user_id=event.user_id,
        root_thread_id=event.root_thread_id,
        source_thread_id=event.source_thread_id,
        source_branch_id=event.source_branch_id,
        request_id=event.request_id,
        data=dict(event.data),
        created_at=_dt(event.created_at),
    )


def _candidate_response(candidate: MemoryCandidate) -> MemoryCandidateResponse:
    return MemoryCandidateResponse(
        candidate_id=candidate.candidate_id,
        status=candidate.status,
        agent_id=candidate.agent_id,
        task_id=candidate.task_id,
        branch_id=candidate.branch_id,
        root_thread_id=candidate.root_thread_id,
        user_id=candidate.user_id,
        evidence_refs=list(candidate.evidence_refs),
        record=_model_payload(candidate.record),
        reason=candidate.reason,
        created_at=_dt(candidate.created_at),
        updated_at=_dt(candidate.updated_at),
    )


__all__ = ["router"]
