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
        latest_user = _latest_message_text(state.get("messages", []), HumanMessage)
        inferred = self._extract_explicit_user_memory(latest_user=latest_user, context=context)
        if inferred is not None:
            records.append(inferred)
        return records

    def _extract_project_facts(self, *, context: RequestContext, state: dict[str, Any]) -> list[MemoryWriteRequest]:
        active_goal = str(state.get("active_goal") or "").strip()
        if not context.project_id or not active_goal or not _looks_like_project_fact(active_goal):
            return []
        return [
            MemoryWriteRequest(
                kind=MemoryKind.PROJECT_FACT,
                scope=MemoryScope.PROJECT,
                visibility=MemoryVisibility.SHARED,
                namespace=project_memory_namespace(context.project_id),
                content=active_goal,
                summary=active_goal[:240],
                root_thread_id=context.root_thread_id,
                user_id=context.user_id,
                importance=0.65,
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
                    importance=max(0.65, float(item.confidence or 0.0)),
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
        if _looks_like_low_signal_ack(last_ai):
            return None
        if not last_ai:
            return None
        if last_user:
            content = f"User: {last_user} Assistant: {last_ai}".strip()
        else:
            content = f"Assistant: {last_ai}".strip()
        return MemoryWriteRequest(
            kind=MemoryKind.TURN_SUMMARY,
            scope=MemoryScope.ROOT_THREAD,
            visibility=MemoryVisibility.PRIVATE,
            namespace=root_thread_episodic_namespace(context.root_thread_id),
            content=content,
            summary=content[:240],
            source_thread_id=context.branch_id or context.root_thread_id,
            root_thread_id=context.root_thread_id,
            user_id=context.user_id,
            importance=0.55,
        )

    def _extract_explicit_user_memory(
        self,
        *,
        latest_user: str,
        context: RequestContext,
    ) -> MemoryWriteRequest | None:
        text = latest_user.strip()
        if not text or len(text) > 240:
            return None
        if _looks_like_user_profile(text):
            return MemoryWriteRequest(
                kind=MemoryKind.USER_PROFILE,
                scope=MemoryScope.USER,
                visibility=MemoryVisibility.SHARED,
                namespace=user_profile_namespace(context.user_id),
                content=text,
                summary=text[:240],
                user_id=context.user_id,
                importance=0.75,
            )
        if _looks_like_user_preference(text):
            return MemoryWriteRequest(
                kind=MemoryKind.USER_PREFERENCE,
                scope=MemoryScope.USER,
                visibility=MemoryVisibility.SHARED,
                namespace=user_profile_namespace(context.user_id),
                content=text,
                summary=text[:240],
                user_id=context.user_id,
                importance=0.8,
            )
        return None


def _latest_message_text(messages: list[Any], message_type: type) -> str:
    for message in reversed(messages):
        if isinstance(message, message_type):
            content = getattr(message, "content", "")
            return str(content).strip()
    return ""


def _looks_like_user_profile(text: str) -> bool:
    if _looks_like_task_request(text):
        return False
    return any(
        phrase in text
        for phrase in (
            "我是",
            "我主要",
            "我不熟",
            "我更偏好",
            "我习惯",
        )
    )


def _looks_like_user_preference(text: str) -> bool:
    if _looks_like_task_request(text):
        return False
    return any(
        phrase in text
        for phrase in (
            "回答里不要",
            "请不要",
            "不要使用",
            "别用",
            "不用",
            "请用中文",
            "请用英文",
            "请叫我",
            "以后都",
            "以后请",
            "尽量简洁",
            "尽量详细",
        )
    )


def _looks_like_project_fact(text: str) -> bool:
    if _looks_like_task_request(text):
        return False
    return any(
        phrase in text
        for phrase in (
            "默认",
            "统一",
            "约定",
            "规范",
            "架构",
            "配置",
            "只读",
            "必须",
            "禁止",
        )
    )


def _looks_like_task_request(text: str) -> bool:
    lowered = text.casefold()
    return (
        any(
            token in lowered
            for token in (
                "帮我",
                "请帮",
                "请继续",
                "请根据",
                "请先",
                "请直接",
                "能不能",
                "可以帮",
                "写一",
                "列出",
                "解释",
                "我在做",
            )
        )
        or "?" in text
        or "？" in text
        or lowered.endswith("吗")
    )


def _looks_like_low_signal_ack(text: str) -> bool:
    normalized = " ".join((text or "").strip().casefold().split())
    if not normalized:
        return True
    return normalized in {
        "ok",
        "okay",
        "好的",
        "好的。",
        "收到",
        "明白",
        "了解",
        "done",
        "已完成",
    }
