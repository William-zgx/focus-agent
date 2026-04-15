from __future__ import annotations

from typing import Any

from langchain.messages import AIMessage, HumanMessage

from ..core.request_context import RequestContext
from ..core.types import FindingItem
from ..storage.namespaces import (
    branch_local_memory_namespace,
    project_memory_namespace,
    root_thread_episodic_namespace,
    user_profile_namespace,
)
from .models import (
    MemoryExtractionResult,
    MemoryKind,
    MemoryScope,
    MemoryVisibility,
    MemoryWriteRequest,
)


class MemoryExtractor:
    def extract_from_turn(self, *, context: RequestContext, state: dict[str, Any]) -> MemoryExtractionResult:
        records: list[MemoryWriteRequest] = []
        records.extend(self._extract_user_preferences(state=state, context=context))
        records.extend(self._extract_project_facts(context=context, state=state))
        records.extend(self._extract_branch_findings(context=context, state=state))
        episodic = self._extract_episodic_summary(context=context, state=state)
        if episodic is not None:
            records.append(episodic)
        return MemoryExtractionResult(records=records, summary=f"{len(records)} memory writes prepared")

    def _extract_user_preferences(
        self,
        *,
        state: dict[str, Any],
        context: RequestContext,
    ) -> list[MemoryWriteRequest]:
        records: list[MemoryWriteRequest] = []
        for item in state.get("pinned_facts", []):
            fact = getattr(item, "fact", None) or (item.get("fact") if isinstance(item, dict) else None)
            if not fact:
                continue
            records.append(
                MemoryWriteRequest(
                    kind=MemoryKind.USER_PREFERENCE,
                    scope=MemoryScope.USER,
                    visibility=MemoryVisibility.SHARED,
                    namespace=user_profile_namespace(context.user_id),
                    content=str(fact),
                    summary=str(fact),
                    user_id=context.user_id,
                )
            )
        return records

    def _extract_project_facts(self, *, context: RequestContext, state: dict[str, Any]) -> list[MemoryWriteRequest]:
        if not context.project_id or not state.get("active_goal"):
            return []
        return [
            MemoryWriteRequest(
                kind=MemoryKind.PROJECT_FACT,
                scope=MemoryScope.PROJECT,
                visibility=MemoryVisibility.SHARED,
                namespace=project_memory_namespace(context.project_id),
                content=str(state["active_goal"]),
                summary=str(state["active_goal"]),
                root_thread_id=context.root_thread_id,
                user_id=context.user_id,
            )
        ]

    def _extract_branch_findings(
        self,
        *,
        context: RequestContext,
        state: dict[str, Any],
    ) -> list[MemoryWriteRequest]:
        if not context.branch_id:
            return []
        records: list[MemoryWriteRequest] = []
        for value in state.get("branch_local_findings", []):
            item = value if isinstance(value, FindingItem) else FindingItem.model_validate(value)
            records.append(
                MemoryWriteRequest(
                    kind=MemoryKind.BRANCH_FINDING,
                    scope=MemoryScope.BRANCH,
                    visibility=MemoryVisibility.PROMOTABLE,
                    namespace=branch_local_memory_namespace(context.root_thread_id, context.branch_id),
                    content=item.finding,
                    summary=item.finding,
                    evidence_refs=item.evidence_refs,
                    source_branch_id=context.branch_id,
                    root_thread_id=context.root_thread_id,
                    user_id=context.user_id,
                    confidence=item.confidence,
                )
            )
        return records

    def _extract_episodic_summary(
        self,
        *,
        context: RequestContext,
        state: dict[str, Any],
    ) -> MemoryWriteRequest | None:
        messages = state.get("messages", [])
        last_user = _latest_message_text(messages, HumanMessage)
        last_ai = _latest_message_text(messages, AIMessage)
        summary = " ".join(part for part in [last_user, last_ai] if part).strip()
        if not summary:
            return None
        return MemoryWriteRequest(
            kind=MemoryKind.TURN_SUMMARY,
            scope=MemoryScope.ROOT_THREAD,
            visibility=MemoryVisibility.PRIVATE,
            namespace=root_thread_episodic_namespace(context.root_thread_id),
            content=summary,
            summary=summary[:240],
            source_thread_id=context.branch_id or context.root_thread_id,
            root_thread_id=context.root_thread_id,
            user_id=context.user_id,
        )


def _latest_message_text(messages: list[Any], message_type: type) -> str:
    for message in reversed(messages):
        if isinstance(message, message_type):
            content = getattr(message, "content", "")
            return str(content).strip()
    return ""
