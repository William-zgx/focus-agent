from __future__ import annotations

from typing import Any

from focus_agent.memory.models import MemoryStatus

from .memory_repository import MemoryEmbeddingListQuery, MemoryListQuery

MEMORY_LIST_FILTER_FIELDS = (
    "kind",
    "scope",
    "visibility",
    "status",
    "user_id",
    "root_thread_id",
    "source_thread_id",
    "source_branch_id",
)


def memory_list_filters(query: MemoryListQuery) -> tuple[list[str], dict[str, Any]]:
    clauses = [] if query.status == MemoryStatus.FORGOTTEN.value else ["deleted_at IS NULL"]
    params: dict[str, Any] = {
        "limit": max(1, int(query.limit)),
        "offset": max(0, int(query.offset)),
    }
    for field in MEMORY_LIST_FILTER_FIELDS:
        value = getattr(query, field)
        if value is not None:
            clauses.append(f"{field} = %({field})s")
            params[field] = value
    if query.namespace is not None:
        clauses.append("namespace = %(namespace)s")
        params["namespace"] = list(query.namespace)
    return clauses, params


def embedding_list_filters(
    query: MemoryEmbeddingListQuery | None = None,
    *,
    namespace: tuple[str, ...] | None = None,
    provider_id: str | None = None,
    model_id: str | None = None,
    model: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[str], dict[str, Any]]:
    if query is not None:
        namespace = query.namespace
        provider_id = query.provider_id
        model_id = query.model_id
        status = query.status
        limit = query.limit
        offset = query.offset
    if model_id is None:
        model_id = model
    params: dict[str, Any] = {
        "limit": max(1, int(limit)),
        "offset": max(0, int(offset)),
    }
    clauses: list[str] = ["deleted_at IS NULL"]
    if namespace is not None:
        clauses.append("namespace = %(namespace)s")
        params["namespace"] = list(namespace)
    if provider_id is not None:
        clauses.append("provider_id = %(provider_id)s")
        params["provider_id"] = provider_id
    if model_id is not None:
        clauses.append("model_id = %(model_id)s")
        params["model_id"] = model_id
    if status is not None:
        clauses.append("status = %(status)s")
        params["status"] = status
    return clauses, params


def audit_event_filters(
    *,
    memory_id: str | None = None,
    user_id: str | None = None,
    root_thread_id: str | None = None,
    source_thread_id: str | None = None,
    source_branch_id: str | None = None,
    limit: int = 50,
) -> tuple[list[str], dict[str, Any]]:
    params: dict[str, Any] = {"limit": max(1, int(limit))}
    clauses: list[str] = []
    for field, value in (
        ("memory_id", memory_id),
        ("user_id", user_id),
        ("root_thread_id", root_thread_id),
        ("source_thread_id", source_thread_id),
        ("source_branch_id", source_branch_id),
    ):
        if value is not None:
            clauses.append(f"{field} = %({field})s")
            params[field] = value
    return clauses, params


def candidate_filters(
    *,
    status: str | None = None,
    root_thread_id: str | None = None,
    user_id: str | None = None,
    branch_id: str | None = None,
    limit: int = 50,
) -> tuple[list[str], dict[str, Any]]:
    clauses: list[str] = []
    params: dict[str, Any] = {"limit": max(1, int(limit))}
    if status:
        clauses.append("status = %(status)s")
        params["status"] = status
    if root_thread_id:
        clauses.append("root_thread_id = %(root_thread_id)s")
        params["root_thread_id"] = root_thread_id
    if user_id:
        clauses.append("user_id = %(user_id)s")
        params["user_id"] = user_id
    if branch_id:
        clauses.append("branch_id = %(branch_id)s")
        params["branch_id"] = branch_id
    return clauses, params


def where_clause(clauses: list[str]) -> str:
    return f"WHERE {' AND '.join(clauses)}" if clauses else ""
