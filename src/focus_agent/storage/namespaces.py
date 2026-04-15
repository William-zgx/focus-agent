from __future__ import annotations

from typing import Any

from ..core.request_context import RequestContext


def user_profile_namespace(user_id: str) -> tuple[str, ...]:
    return ("user", user_id, "profile")


def conversation_main_namespace(root_thread_id: str) -> tuple[str, ...]:
    return ("conversation", root_thread_id, "main")


def root_thread_episodic_namespace(root_thread_id: str) -> tuple[str, ...]:
    return ("conversation", root_thread_id, "episodic")


def root_thread_semantic_namespace(root_thread_id: str) -> tuple[str, ...]:
    return ("conversation", root_thread_id, "semantic")


def branch_namespace(root_thread_id: str, branch_id: str) -> tuple[str, ...]:
    return ("conversation", root_thread_id, "branch", branch_id)


def branch_local_memory_namespace(root_thread_id: str, branch_id: str) -> tuple[str, ...]:
    return ("conversation", root_thread_id, "branch", branch_id, "local_memory")


def branch_promoted_memory_namespace(root_thread_id: str, branch_id: str) -> tuple[str, ...]:
    return ("conversation", root_thread_id, "branch", branch_id, "promoted_memory")


def project_memory_namespace(project_id: str) -> tuple[str, ...]:
    return ("project", project_id, "memory")


def skill_memory_namespace(skill_id: str) -> tuple[str, ...]:
    return ("skill", skill_id, "memory")


def conversation_namespace_for_context(context: RequestContext) -> tuple[str, ...]:
    if context.branch_id:
        return branch_namespace(context.root_thread_id, context.branch_id)
    return conversation_main_namespace(context.root_thread_id)


def is_user_profile_payload_allowed(payload: dict[str, Any]) -> bool:
    payload_type = str(payload.get("type", ""))
    return payload_type in {"user_preference", "user_profile", "account_setting"}
