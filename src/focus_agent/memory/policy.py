from __future__ import annotations

from ..core.request_context import RequestContext
from ..core.types import PromptMode
from ..storage.namespaces import (
    branch_local_memory_namespace,
    conversation_main_namespace,
    project_memory_namespace,
    root_thread_episodic_namespace,
    root_thread_semantic_namespace,
    skill_memory_namespace,
    user_profile_namespace,
)
from .models import MemoryRecord, MemoryVisibility, MemoryWriteRequest, RetrievedMemoryBundle


class MemoryPolicy:
    def __init__(self, *, top_k: int = 8):
        self.top_k = top_k

    def should_persist(
        self,
        *,
        record: MemoryWriteRequest,
        context: RequestContext,
        state: dict,
    ) -> bool:
        del context, state
        return bool(record.content.strip())

    def allowed_namespaces_for_read(self, *, context: RequestContext) -> list[tuple[str, ...]]:
        namespaces: list[tuple[str, ...]] = [
            conversation_main_namespace(context.root_thread_id),
            root_thread_semantic_namespace(context.root_thread_id),
            root_thread_episodic_namespace(context.root_thread_id),
            user_profile_namespace(context.user_id),
        ]
        if context.branch_id:
            namespaces.insert(1, branch_local_memory_namespace(context.root_thread_id, context.branch_id))
        if context.project_id:
            namespaces.append(project_memory_namespace(context.project_id))
        for skill_id in context.skill_hints:
            namespaces.append(skill_memory_namespace(skill_id))
        return namespaces

    def can_promote_branch_record(self, *, record: MemoryRecord) -> bool:
        return record.scope.value == "branch" and record.visibility in {
            MemoryVisibility.PROMOTABLE,
            MemoryVisibility.SHARED,
        }

    def filter_bundle_for_prompt(
        self,
        bundle: RetrievedMemoryBundle,
        *,
        prompt_mode: PromptMode,
    ) -> RetrievedMemoryBundle:
        hits = bundle.hits
        if prompt_mode == PromptMode.SYNTHESIZE:
            hits = [
                hit
                for hit in hits
                if not hit.record.source_branch_id or hit.record.promoted_to_main
            ]
        return bundle.model_copy(update={"hits": hits[: self.top_k], "total_hits": len(hits)})
