from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from langchain.tools import tool
from langgraph.config import get_config

from ...core.request_context import RequestContext
from ...core.types import PromptMode
from ...memory import MemoryRetriever, MemoryService, MemoryWriter
from ...memory.models import MemoryKind, MemoryScope, MemoryVisibility, MemoryWriteRequest
from ...memory.retriever import _build_retrieval_query
from ...storage.namespaces import (
    branch_local_memory_namespace,
    branch_promoted_memory_namespace,
    conversation_main_namespace,
    project_memory_namespace,
    root_thread_episodic_namespace,
    user_profile_namespace,
)
from .common import _require_non_empty_text_arg


def _parse_namespace(value: str) -> tuple[str, ...]:
    parts = [part.strip() for part in re.split(r"[:/,]", value) if part.strip()]
    if not parts:
        raise ValueError("namespace must not be empty.")
    return tuple(parts)


def get_current_thread_id() -> str | None:
    try:
        config = get_config()
    except Exception:  # noqa: BLE001
        return None
    configurable = dict(config.get("configurable") or {})
    value = configurable.get("thread_id")
    return str(value) if value else None


def _default_memory_namespaces(
    *,
    user_id: str | None = None,
    root_thread_id: str | None = None,
    branch_id: str | None = None,
    project_id: str | None = None,
) -> list[tuple[str, ...]]:
    effective_user_id = (user_id or "default").strip() or "default"
    effective_thread_id = (root_thread_id or get_current_thread_id() or "").strip()
    namespaces = [
        user_profile_namespace(effective_user_id),
    ]
    if project_id is None:
        namespaces.append(project_memory_namespace("default"))
    elif project_id.strip():
        namespaces.append(project_memory_namespace(project_id.strip()))
    if effective_thread_id:
        namespaces.append(root_thread_episodic_namespace(effective_thread_id))
        namespaces.append(conversation_main_namespace(effective_thread_id))
        if branch_id and branch_id.strip():
            namespaces.append(branch_local_memory_namespace(effective_thread_id, branch_id.strip()))
            namespaces.append(
                branch_promoted_memory_namespace(effective_thread_id, branch_id.strip())
            )
    return namespaces


def _resolve_memory_namespace(
    *,
    namespace: str | None,
    kind: MemoryKind,
    scope: MemoryScope,
    user_id: str | None = None,
    root_thread_id: str | None = None,
    branch_id: str | None = None,
    project_id: str | None = None,
) -> tuple[str, ...]:
    if namespace and namespace.strip():
        return _parse_namespace(namespace)
    if scope == MemoryScope.PROJECT:
        return project_memory_namespace((project_id or "default").strip() or "default")
    if scope == MemoryScope.BRANCH and branch_id and branch_id.strip():
        effective_thread_id = (
            root_thread_id or get_current_thread_id() or "default"
        ).strip() or "default"
        return branch_local_memory_namespace(effective_thread_id, branch_id.strip())
    if scope == MemoryScope.ROOT_THREAD:
        effective_thread_id = (
            root_thread_id or get_current_thread_id() or "default"
        ).strip() or "default"
        if kind == MemoryKind.TURN_SUMMARY:
            return root_thread_episodic_namespace(effective_thread_id)
        return conversation_main_namespace(effective_thread_id)
    return user_profile_namespace((user_id or "default").strip() or "default")


MEMORY_TOOL_NAMES = frozenset({"memory_save", "memory_search", "memory_forget"})


def authorize_memory_tool_args(
    tool_name: str,
    args: dict[str, Any],
    context: RequestContext,
) -> tuple[dict[str, Any] | None, str | None]:
    if tool_name not in MEMORY_TOOL_NAMES:
        return dict(args), None
    bound_args = dict(args)
    context_user_id = str(getattr(context, "user_id", "") or "").strip()
    context_root_thread_id = str(getattr(context, "root_thread_id", "") or "").strip()
    if not context_user_id:
        return None, "Memory tools require a runtime user_id."
    if not context_root_thread_id:
        return None, "Memory tools require a runtime root_thread_id."
    for field_name, expected in (
        ("user_id", context_user_id),
        ("root_thread_id", context_root_thread_id),
    ):
        supplied = bound_args.get(field_name)
        if supplied is not None and str(supplied).strip() and str(supplied).strip() != expected:
            return (
                None,
                f"Memory tool argument {field_name} does not match the active request context.",
            )
        bound_args[field_name] = expected

    branch_id = str(getattr(context, "branch_id", "") or "").strip()
    project_id = str(getattr(context, "project_id", "") or "").strip()
    bound_args["branch_id"] = branch_id
    bound_args["project_id"] = project_id

    scope = str(bound_args.get("scope") or "").strip().lower()
    if scope == MemoryScope.SKILL.value:
        return None, "Memory tool access to skill-scoped memory is not allowed."
    if scope == MemoryScope.BRANCH.value and not branch_id:
        return None, "Memory tool access to branch memory requires an active branch_id."
    if scope == MemoryScope.PROJECT.value and not project_id:
        return None, "Memory tool access to project memory requires an active project_id."

    namespace = str(bound_args.get("namespace") or "").strip()
    if namespace:
        try:
            parsed_namespace = _parse_namespace(namespace)
        except ValueError as exc:
            return None, str(exc)
        if parsed_namespace and parsed_namespace[0] == "skill":
            return None, "Memory tool access to skill-scoped memory is not allowed."
        if parsed_namespace not in _allowed_memory_tool_namespaces(context):
            return None, "Memory tool namespace is outside the active request context."
    return bound_args, None


def _allowed_memory_tool_namespaces(context: RequestContext) -> set[tuple[str, ...]]:
    root_thread_id = str(context.root_thread_id).strip()
    user_id = str(context.user_id).strip()
    allowed = {
        user_profile_namespace(user_id),
        conversation_main_namespace(root_thread_id),
        root_thread_episodic_namespace(root_thread_id),
    }
    if context.branch_id:
        branch_id = str(context.branch_id).strip()
        allowed.add(branch_local_memory_namespace(root_thread_id, branch_id))
        allowed.add(branch_promoted_memory_namespace(root_thread_id, branch_id))
    if context.project_id:
        allowed.add(project_memory_namespace(str(context.project_id).strip()))
    return allowed


def _coerce_memory_scope(
    scope: str,
    *,
    namespace: str | None = None,
    branch_id: str | None = None,
) -> MemoryScope:
    normalized_scope = scope.strip().lower()
    if normalized_scope == "conversation":
        return MemoryScope.ROOT_THREAD
    if normalized_scope == MemoryScope.SKILL.value and not (namespace or "").strip():
        raise ValueError(f"scope={normalized_scope!r} requires an explicit namespace.")
    if (
        normalized_scope == MemoryScope.BRANCH.value
        and not (namespace or "").strip()
        and not (branch_id or "").strip()
    ):
        raise ValueError(f"scope={normalized_scope!r} requires an active branch_id.")
    return MemoryScope(normalized_scope)


def _default_memory_visibility(*, kind: MemoryKind, scope: MemoryScope) -> MemoryVisibility:
    if scope == MemoryScope.USER and kind in {MemoryKind.USER_PREFERENCE, MemoryKind.USER_PROFILE}:
        return MemoryVisibility.SHARED
    if scope == MemoryScope.PROJECT and kind == MemoryKind.PROJECT_FACT:
        return MemoryVisibility.SHARED
    if scope == MemoryScope.BRANCH and kind == MemoryKind.BRANCH_FINDING:
        return MemoryVisibility.PROMOTABLE
    if scope == MemoryScope.ROOT_THREAD and kind in {
        MemoryKind.BRANCH_FINDING,
        MemoryKind.IMPORTED_CONCLUSION,
    }:
        return MemoryVisibility.SHARED
    return MemoryVisibility.PRIVATE


def _json_safe_memory_item(item: Any, *, namespace: tuple[str, ...]) -> dict[str, Any]:
    record = getattr(item, "record", None)
    if record is not None and hasattr(record, "model_dump"):
        value = record.model_dump(mode="json")
        key = getattr(record, "memory_id", None)
    else:
        value = getattr(item, "value", item)
        key = getattr(item, "key", None)
        if not isinstance(value, dict):
            value = {"content": str(value)}
    memory_id = str(value.get("memory_id") or key or "")
    payload = {
        "memory_id": memory_id,
        "namespace": list(value.get("namespace") or namespace),
        "kind": value.get("kind"),
        "scope": value.get("scope"),
        "visibility": value.get("visibility"),
        "content": value.get("content") or "",
        "summary": value.get("summary") or "",
        "tags": value.get("tags") or [],
        "confidence": value.get("confidence"),
        "importance": value.get("importance"),
        "created_at": value.get("created_at"),
        "updated_at": value.get("updated_at"),
    }
    score = getattr(item, "score", None)
    matched_terms = getattr(item, "matched_terms", None)
    if score is not None:
        payload["score"] = float(score)
    if matched_terms:
        payload["matched_terms"] = list(matched_terms)
    return payload


def build_memory_tools(
    *,
    store: Any,
    memory_repository: Any = None,
    memory_embedding_service: Any = None,
    tool_catalog: Any,
    emit_tool_event: Callable[..., None],
    get_current_thread_id: Callable[[], str | None],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    def _validate_memory_save_args(args: dict[str, Any]) -> None:
        _require_non_empty_text_arg(args, "content")

    def _validate_memory_forget_args(args: dict[str, Any]) -> None:
        _require_non_empty_text_arg(args, "memory_id")

    @tool
    def memory_save(
        content: str,
        kind: str = "user_preference",
        scope: str = "user",
        namespace: str | None = None,
        summary: str = "",
        tags: list[str] | None = None,
        user_id: str | None = None,
        root_thread_id: str | None = None,
        branch_id: str | None = None,
        project_id: str | None = None,
        confidence: float | None = None,
        importance: float = 0.6,
    ) -> str:
        """Save an explicit durable memory such as a user preference or project fact."""
        tool_name = "memory_save"
        emit_tool_event(
            tool_name=tool_name, stage="start", kind=kind, scope=scope, namespace=namespace
        )
        try:
            if store is None and memory_repository is None:
                raise RuntimeError("Memory store is not configured.")
            if not content.strip():
                raise ValueError("content must not be empty.")
            memory_kind = MemoryKind(kind.strip())
            memory_scope = _coerce_memory_scope(
                scope,
                namespace=namespace,
                branch_id=branch_id,
            )
            resolved_namespace = _resolve_memory_namespace(
                namespace=namespace,
                kind=memory_kind,
                scope=memory_scope,
                user_id=user_id,
                root_thread_id=root_thread_id,
                branch_id=branch_id,
                project_id=project_id,
            )
            record = MemoryWriteRequest(
                kind=memory_kind,
                scope=memory_scope,
                visibility=_default_memory_visibility(kind=memory_kind, scope=memory_scope),
                namespace=resolved_namespace,
                content=content.strip(),
                summary=(summary or content).strip()[:240],
                tags=tags or [],
                root_thread_id=root_thread_id or get_current_thread_id(),
                user_id=(user_id or "default").strip() or "default",
                confidence=confidence,
                importance=importance,
            )
            if memory_repository is not None:
                decision = MemoryService(
                    repository=memory_repository,
                    embedding_service=memory_embedding_service,
                ).upsert_request(
                    record,
                    actor="memory_save_tool",
                    reason="explicit_tool_save",
                )
                memory_id = decision.memory_id or ""
                action = decision.action or decision.status.value
            else:
                action, memory_id = MemoryWriter(store=store)._upsert_record(record)
            payload = {
                "memory_id": memory_id,
                "namespace": list(resolved_namespace),
                "kind": memory_kind.value,
                "scope": memory_scope.value,
                "visibility": record.visibility.value,
                "saved": action in {"written", "merged"},
                "action": action,
            }
            result = json.dumps(payload, ensure_ascii=False)
            emit_tool_event(tool_name=tool_name, stage="end", output=result[:800])
            return result
        except Exception as exc:  # noqa: BLE001
            emit_tool_event(tool_name=tool_name, stage="error", error=str(exc))
            raise

    @tool
    def memory_search(
        query: str,
        namespace: str | None = None,
        user_id: str | None = None,
        root_thread_id: str | None = None,
        branch_id: str | None = None,
        project_id: str | None = None,
        limit: int | None = None,
    ) -> str:
        """Search durable memories by query across the default memory namespaces."""
        tool_name = "memory_search"
        emit_tool_event(
            tool_name=tool_name, stage="start", query=query, namespace=namespace, limit=limit
        )
        try:
            if store is None and memory_repository is None:
                raise RuntimeError("Memory store is not configured.")
            if not query.strip():
                raise ValueError("query must not be empty.")
            requested_limit = (
                tool_catalog.memory_search.default_limit if limit is None else int(limit)
            )
            capped_limit = max(1, min(requested_limit, tool_catalog.memory_search.max_limit))
            search_limit = min(
                tool_catalog.memory_search.max_limit,
                max(capped_limit, tool_catalog.memory_search.default_limit),
            )
            namespaces = (
                [_parse_namespace(namespace)]
                if namespace and namespace.strip()
                else _default_memory_namespaces(
                    user_id=user_id,
                    root_thread_id=root_thread_id,
                    branch_id=branch_id,
                    project_id=project_id,
                )
            )
            effective_query = _build_retrieval_query(
                query=query.strip(),
                state={},
                prompt_mode=PromptMode.EXPLORE,
            )
            retriever = MemoryRetriever(
                store=store,
                repository=memory_repository,
                default_limit=search_limit,
            )
            hits = []
            for candidate_namespace in namespaces:
                hits.extend(
                    retriever._search_namespace(
                        candidate_namespace,
                        effective_query,
                        limit=search_limit,
                    )
                )
            reranked_hits = retriever._rerank_hits(
                hits,
                query=effective_query,
                prompt_mode=PromptMode.EXPLORE,
            )
            deduped_hits = retriever._dedupe_hits(reranked_hits)
            results = [
                _json_safe_memory_item(item, namespace=item.namespace)
                for item in deduped_hits[:capped_limit]
            ]
            payload = {
                "query": query,
                "namespaces": [list(item) for item in namespaces],
                "results": results,
                "truncated": len(deduped_hits) > capped_limit,
            }
            result = json.dumps(payload, ensure_ascii=False)
            emit_tool_event(
                tool_name=tool_name, stage="end", result_count=len(results), output=result[:800]
            )
            return result
        except Exception as exc:  # noqa: BLE001
            emit_tool_event(tool_name=tool_name, stage="error", error=str(exc), query=query)
            raise

    @tool
    def memory_forget(
        memory_id: str,
        namespace: str | None = None,
        user_id: str | None = None,
        root_thread_id: str | None = None,
        branch_id: str | None = None,
        project_id: str | None = None,
    ) -> str:
        """Delete a saved memory by id from an explicit or default memory namespace."""
        tool_name = "memory_forget"
        emit_tool_event(
            tool_name=tool_name, stage="start", memory_id=memory_id, namespace=namespace
        )
        try:
            if store is None and memory_repository is None:
                raise RuntimeError("Memory store is not configured.")
            normalized_id = memory_id.strip()
            if not normalized_id:
                raise ValueError("memory_id must not be empty.")
            namespaces = (
                [_parse_namespace(namespace)]
                if namespace and namespace.strip()
                else _default_memory_namespaces(
                    user_id=user_id,
                    root_thread_id=root_thread_id,
                    branch_id=branch_id,
                    project_id=project_id,
                )
            )
            deleted_namespace: tuple[str, ...] | None = None
            if memory_repository is not None:
                service = MemoryService(
                    repository=memory_repository,
                    embedding_service=memory_embedding_service,
                )
                for candidate_namespace in namespaces:
                    decision = service.forget(
                        memory_id=normalized_id,
                        namespace=candidate_namespace,
                        actor="memory_forget_tool",
                        reason="explicit_tool_forget",
                    )
                    if decision.status.value == "forgotten":
                        deleted_namespace = candidate_namespace
                        break
            else:
                for candidate_namespace in namespaces:
                    if store.get(candidate_namespace, normalized_id) is None:
                        continue
                    store.delete(candidate_namespace, normalized_id)
                    deleted_namespace = candidate_namespace
                    break
            payload = {
                "memory_id": normalized_id,
                "deleted": deleted_namespace is not None,
                "namespace": list(deleted_namespace) if deleted_namespace else None,
                "searched_namespaces": [list(item) for item in namespaces],
            }
            result = json.dumps(payload, ensure_ascii=False)
            emit_tool_event(tool_name=tool_name, stage="end", output=result[:800])
            return result
        except Exception as exc:  # noqa: BLE001
            emit_tool_event(tool_name=tool_name, stage="error", error=str(exc), memory_id=memory_id)
            raise

    return (
        {
            "memory_save": memory_save,
            "memory_search": memory_search,
            "memory_forget": memory_forget,
        },
        {
            "memory_save": {
                "side_effect": True,
                "validator": _validate_memory_save_args,
                "max_observation_chars": 800,
            },
            "memory_search": {
                "parallel_safe": True,
                "max_observation_chars": 6000,
            },
            "memory_forget": {
                "side_effect": True,
                "validator": _validate_memory_forget_args,
                "max_observation_chars": 800,
            },
        },
    )
