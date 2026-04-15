from __future__ import annotations

import uuid

from ..core.branching import ImportedConclusion
from ..core.request_context import RequestContext
from .namespaces import (
    branch_namespace,
    conversation_main_namespace,
    user_profile_namespace,
)


def main_conversation_namespace(context: RequestContext) -> tuple[str, ...]:
    return conversation_main_namespace(context.root_thread_id)


def branch_memory_namespace(context: RequestContext) -> tuple[str, ...]:
    branch_id = context.branch_id or "main"
    return branch_namespace(context.root_thread_id, branch_id)


def user_profile_memory_namespace(context: RequestContext) -> tuple[str, ...]:
    return user_profile_namespace(context.user_id)


def persist_imported_conclusion(store, context: RequestContext, conclusion: ImportedConclusion) -> str:
    key = str(uuid.uuid4())
    store.put(
        main_conversation_namespace(context),
        key,
        {
            "type": "imported_conclusion",
            "branch_id": conclusion.branch_id,
            "branch_name": conclusion.branch_name,
            "mode": conclusion.mode.value,
            "summary": conclusion.summary,
            "key_findings": conclusion.key_findings,
            "evidence_refs": conclusion.evidence_refs,
            "artifacts": conclusion.artifacts,
        },
    )
    return key
