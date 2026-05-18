from __future__ import annotations

from collections.abc import Sequence

from fastapi import HTTPException, status

from focus_agent.core.repo_call import (
    REPO_METHOD_ERROR,
    REPO_METHOD_MISSING,
    has_repo_method,
    safe_repo_call,
)
from focus_agent.engine.runtime import AppRuntime
from focus_agent.memory import MemoryAuditEvent, MemoryCandidate, MemoryRecord
from focus_agent.memory.models import MemoryScope
from focus_agent.repositories.memory_repository import MemoryRepository
from focus_agent.security.permissions import AuthContext

from .memory_responses import _value


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
    return (
        _can_access_thread_memory(record, user_id=user_id, runtime=runtime)
        or record.user_id == user_id
    )


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
    return has_repo_method(getattr(runtime, "repo", None), "assert_thread_owner")


def _thread_owner_matches(thread_id: str, *, user_id: str, runtime: AppRuntime) -> bool | None:
    result = safe_repo_call(
        getattr(runtime, "repo", None),
        "assert_thread_owner",
        thread_id=thread_id,
        owner_user_id=user_id,
        default_missing=REPO_METHOD_MISSING,
        default_error=REPO_METHOD_ERROR,
        except_errors=(KeyError, PermissionError),
    )
    if result is REPO_METHOD_MISSING:
        return None
    if result is REPO_METHOD_ERROR:
        return False
    return True


def _is_branch_owner(branch_id: str, *, user_id: str, runtime: AppRuntime) -> bool:
    return bool(_branch_owner_matches(branch_id, user_id=user_id, runtime=runtime))


def _branch_owner_matches(branch_id: str, *, user_id: str, runtime: AppRuntime) -> bool | None:
    branch = safe_repo_call(
        getattr(runtime, "repo", None),
        "get",
        branch_id,
        default_missing=None,
        default_error=False,
        except_errors=(KeyError, PermissionError),
    )
    if branch is None:
        return None
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
            part.strip() for part in str(raw_value).replace("/", ",").split(",") if part.strip()
        )
    return tuple(parts) if parts else None


__all__ = [
    "_auth_enabled",
    "_branch_owner_matches",
    "_can_access_audit_event",
    "_can_access_branch_memory",
    "_can_access_candidate",
    "_can_access_memory_record",
    "_can_access_owned_memory_record",
    "_can_access_record_fields",
    "_can_access_thread_memory",
    "_can_forget_memory_record",
    "_effective_user_id_filter",
    "_get_access_checked_record",
    "_get_forget_checked_record",
    "_has_global_memory_access",
    "_has_global_memory_audit_access",
    "_has_global_memory_forget_access",
    "_has_memory_permission",
    "_has_thread_owner_checker",
    "_is_branch_owner",
    "_is_thread_owner",
    "_memory_repository",
    "_parse_namespace",
    "_thread_owner_matches",
]
