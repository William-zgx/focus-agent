from __future__ import annotations

import re
from typing import Any

from langchain.messages import AIMessage, HumanMessage, ToolMessage

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


class MemoryQualityGate:
    def skip_reason(
        self,
        *,
        record: MemoryWriteRequest,
        context: RequestContext,
        state: dict[str, Any],
    ) -> str | None:
        del context
        if record.kind.value != "turn_summary":
            return None

        messages = list(state.get("messages", []) or [])
        latest_turn = _latest_turn_messages(messages)
        latest_user = _latest_message_text(messages, HumanMessage)
        claim_text = _turn_summary_claim_text(record=record, messages=messages)

        if _has_unstable_self_correction_signal(claim_text):
            return "unstable_self_correction"

        has_tool_result = _has_tool_result(latest_turn)
        if (
            _has_live_web_intent(latest_user, state=state)
            and _claims_query_result(claim_text)
            and not has_tool_result
        ):
            return "claimed_tool_use_without_result"

        if _makes_external_live_claim(claim_text, latest_user=latest_user) and not _has_evidence(
            record=record,
            state=state,
            latest_turn=latest_turn,
        ):
            return "external_claim_without_evidence"

        return None


class MemoryPolicy:
    def __init__(self, *, top_k: int = 8, quality_gate: MemoryQualityGate | None = None):
        self.top_k = top_k
        self.max_content_chars = 4000
        self.quality_gate = quality_gate or MemoryQualityGate()

    def should_persist(
        self,
        *,
        record: MemoryWriteRequest,
        context: RequestContext,
        state: dict,
    ) -> bool:
        return self.persistence_skip_reason(record=record, context=context, state=state) is None

    def persistence_skip_reason(
        self,
        *,
        record: MemoryWriteRequest,
        context: RequestContext,
        state: dict,
    ) -> str | None:
        content = record.content.strip()
        summary = (record.summary or content).strip()
        if not content or not summary:
            return "policy"
        if record.importance < 0.5:
            return "policy"
        if len(content) > self.max_content_chars:
            return "policy"
        if not _turn_is_stable(state):
            return "policy"

        quality_reason = self.quality_gate.skip_reason(
            record=record,
            context=context,
            state=state,
        )
        if quality_reason:
            return quality_reason

        if record.scope == record.scope.USER:
            allowed = record.kind.value in {
                "user_preference",
                "user_profile",
            } and record.namespace == user_profile_namespace(context.user_id)
            return None if allowed else "policy"

        if record.scope == record.scope.PROJECT:
            allowed = bool(
                context.project_id
                and record.kind.value == "project_fact"
                and record.namespace == project_memory_namespace(context.project_id)
            )
            return None if allowed else "policy"

        if record.scope == record.scope.ROOT_THREAD:
            allowed = {"turn_summary", "imported_conclusion"}
            root_namespaces = {
                root_thread_episodic_namespace(context.root_thread_id),
                conversation_main_namespace(context.root_thread_id),
            }
            return (
                None
                if record.kind.value in allowed and record.namespace in root_namespaces
                else "policy"
            )

        if record.scope == record.scope.BRANCH:
            allowed = bool(
                context.branch_id
                and record.kind.value == "branch_finding"
                and record.namespace
                == branch_local_memory_namespace(context.root_thread_id, context.branch_id)
            )
            return None if allowed else "policy"

        return "policy"

    def allowed_namespaces_for_read(self, *, context: RequestContext) -> list[tuple[str, ...]]:
        namespaces: list[tuple[str, ...]] = [
            conversation_main_namespace(context.root_thread_id),
            root_thread_semantic_namespace(context.root_thread_id),
            root_thread_episodic_namespace(context.root_thread_id),
            user_profile_namespace(context.user_id),
        ]
        if context.branch_id:
            namespaces.insert(
                1, branch_local_memory_namespace(context.root_thread_id, context.branch_id)
            )
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
        hits = [
            hit
            for hit in list(bundle.hits)
            if str(getattr(hit.record.status, "value", hit.record.status)) == "active"
            and hit.record.deleted_at is None
            and _memory_relevant_for_query(hit, query=bundle.query)
        ]
        if prompt_mode == PromptMode.SYNTHESIZE:
            hits = [
                hit
                for hit in hits
                if not hit.record.source_branch_id or hit.record.promoted_to_main
            ]
        hits = self._rank_hits_for_prompt(hits, prompt_mode=prompt_mode)
        hits = self._apply_section_budget(hits, prompt_mode=prompt_mode)
        return bundle.model_copy(update={"hits": hits[: self.top_k], "total_hits": len(hits)})

    def _rank_hits_for_prompt(
        self,
        hits: list,
        *,
        prompt_mode: PromptMode,
    ) -> list:
        return sorted(
            hits,
            key=lambda hit: (
                _section_priority(hit.record, prompt_mode=prompt_mode),
                -hit.score,
                -hit.record.importance,
                -(float(hit.record.confidence or 0.0)),
                -hit.record.updated_at.timestamp(),
            ),
        )

    def _apply_section_budget(
        self,
        hits: list,
        *,
        prompt_mode: PromptMode,
    ) -> list:
        limits = _section_limits(prompt_mode=prompt_mode, top_k=self.top_k)
        selected = []
        counts: dict[str, int] = {}
        overflow = []
        for hit in hits:
            section = _section_name(hit.record, prompt_mode=prompt_mode)
            limit = limits.get(section, self.top_k)
            if counts.get(section, 0) < limit:
                selected.append(hit)
                counts[section] = counts.get(section, 0) + 1
            else:
                overflow.append(hit)
        if len(selected) >= self.top_k:
            return selected[: self.top_k]
        for hit in overflow:
            if len(selected) >= self.top_k:
                break
            selected.append(hit)
        return selected[: self.top_k]


def _turn_is_stable(state: dict) -> bool:
    reflection = state.get("reflection")
    status = getattr(reflection, "status", None) or (
        reflection.get("status") if isinstance(reflection, dict) else None
    )
    if status == "replan":
        return False
    messages = list(state.get("messages", []) or [])
    if not messages:
        return False
    last_message = messages[-1]
    if isinstance(last_message, AIMessage) and getattr(last_message, "tool_calls", None):
        return False
    return True


def _latest_turn_messages(messages: list[Any]) -> list[Any]:
    for index in range(len(messages) - 1, -1, -1):
        if isinstance(messages[index], HumanMessage):
            return messages[index:]
    return messages


def _latest_message_text(messages: list[Any], message_type: type) -> str:
    for message in reversed(messages):
        if isinstance(message, message_type):
            content = getattr(message, "content", "")
            return str(content).strip()
    return ""


def _latest_final_ai_text(messages: list[Any]) -> str:
    for message in reversed(messages):
        if isinstance(message, AIMessage) and not getattr(message, "tool_calls", None):
            content = getattr(message, "content", "")
            return str(content).strip()
    return ""


def _turn_summary_claim_text(
    *,
    record: MemoryWriteRequest,
    messages: list[Any],
) -> str:
    latest_ai = _latest_final_ai_text(messages)
    if latest_ai:
        return " ".join(part for part in [record.summary, latest_ai] if part).strip()
    text = " ".join(part for part in [record.summary, record.content] if part).strip()
    if "Assistant:" in text:
        return text.rsplit("Assistant:", maxsplit=1)[-1].strip()
    return text


def _has_tool_result(messages: list[Any]) -> bool:
    return any(isinstance(message, ToolMessage) for message in messages)


def _has_evidence(
    *,
    record: MemoryWriteRequest,
    state: dict[str, Any],
    latest_turn: list[Any],
) -> bool:
    return bool(
        record.evidence_refs
        or state.get("citations")
        or state.get("evidence_bundle")
        or _has_tool_result(latest_turn)
    )


def _has_unstable_self_correction_signal(text: str) -> bool:
    normalized = (text or "").casefold()
    return any(
        phrase in normalized
        for phrase in (
            "我错了",
            "搞错了",
            "弄错了",
            "没查",
            "还没查",
            "未查询",
            "没有查询",
            "可能",
            "不确定",
            "没有实际调用工具",
            "没有调用工具",
            "实际未调用工具",
            "失误",
            "抱歉",
            "maybe",
            "possibly",
            "probably",
            "not sure",
            "i was wrong",
            "i did not check",
            "didn't check",
            "without actually calling",
            "mistake",
        )
    )


def _claims_query_result(text: str) -> bool:
    normalized = (text or "").casefold()
    return any(
        phrase in normalized
        for phrase in (
            "已查",
            "查到",
            "查询结果",
            "根据查询",
            "根据搜索",
            "搜索结果",
            "检索结果",
            "查询显示",
            "搜索显示",
            "according to the search",
            "search results",
            "query results",
            "i found",
        )
    )


def _has_live_web_intent(text: str, *, state: dict[str, Any]) -> bool:
    normalized = (text or "").casefold()
    if any(
        phrase in normalized
        for phrase in (
            "联网",
            "上网",
            "实时",
            "最新",
            "最近",
            "今天",
            "当前",
            "新闻",
            "股价",
            "天气",
            "价格",
            "官网",
            "api 文档",
            "web search",
            "live web",
            "latest",
            "recent",
            "today",
            "current",
            "news",
            "stock price",
            "weather",
        )
    ):
        return True
    return _state_mentions_live_tool(state)


def _state_mentions_live_tool(state: dict[str, Any]) -> bool:
    for key in ("tool_intent_plan", "tool_route_plan", "pending_tool_action"):
        value = state.get(key)
        if not isinstance(value, dict):
            continue
        normalized = str(value).casefold()
        if any(token in normalized for token in ("web_search", "live_web", "search_web")):
            return True
    return False


def _makes_external_live_claim(text: str, *, latest_user: str) -> bool:
    normalized = (text or "").casefold()
    if any(
        phrase in normalized
        for phrase in (
            "最新",
            "最近",
            "今天",
            "当前",
            "实时",
            "新闻",
            "股价",
            "天气",
            "价格",
            "官网",
            "发布",
            "更新",
            "查询显示",
            "搜索显示",
            "latest",
            "recent",
            "today",
            "current",
            "news",
            "stock price",
            "weather",
            "price",
            "released",
            "announced",
        )
    ):
        return True
    return _has_live_web_intent(latest_user, state={}) and _looks_like_factual_claim(text)


def _looks_like_factual_claim(text: str) -> bool:
    normalized = (text or "").casefold()
    if not normalized:
        return False
    return any(char.isdigit() for char in normalized) or any(
        marker in normalized
        for marker in (
            "显示",
            "为",
            "是",
            "有",
            "上涨",
            "下跌",
            "增长",
            "下降",
            "announced",
            "released",
            "is",
            "are",
            "was",
            "were",
        )
    )


def _memory_relevant_for_query(hit: Any, *, query: str) -> bool:
    record = hit.record
    if record.kind.value not in {"user_preference", "user_profile"}:
        return True

    if _has_query_overlap(hit, query=query):
        return True

    text = f"{record.summary} {record.content}".casefold()
    if _contains_sensitive_or_handle_preference(text):
        return _query_mentions_sensitive_or_handle(query)

    return _is_sticky_response_preference(text)


def _has_query_overlap(hit: Any, *, query: str) -> bool:
    query_terms = set(_memory_query_terms(query))
    matched_terms = {str(term).casefold() for term in getattr(hit, "matched_terms", []) or []}
    if matched_terms.intersection(query_terms):
        return True
    haystack = f"{hit.record.summary} {hit.record.content}".casefold()
    return any(term in haystack for term in query_terms)


def _contains_sensitive_or_handle_preference(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "叫我",
            "称呼我",
            "怎么称呼",
            "call me",
            "refer to me",
            "测试口令",
            "口令",
            "密码",
            "密钥",
            "secret",
            "token",
            "api key",
            "api_key",
        )
    )


def _query_mentions_sensitive_or_handle(query: str) -> bool:
    normalized = str(query or "").casefold()
    return any(
        marker in normalized
        for marker in (
            "叫我",
            "叫你",
            "称呼",
            "名字",
            "name",
            "call me",
            "口令",
            "密码",
            "密钥",
            "secret",
            "token",
            "api key",
            "api_key",
        )
    )


def _is_sticky_response_preference(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "用中文",
            "用英文",
            "中文回答",
            "英文回答",
            "language",
            "回答语言",
            "语气",
            "tone",
            "简洁",
            "详细",
            "concise",
            "brief",
            "detailed",
            "markdown",
            "表格",
            "列表",
            "bullet",
            "format",
            "格式",
        )
    )


def _memory_query_terms(query: str) -> list[str]:
    lowered = str(query or "").casefold()
    terms: list[str] = []
    for token in re.findall(r"[a-z0-9]{2,}", lowered):
        if token not in terms:
            terms.append(token)
    for sequence in re.findall(r"[\u4e00-\u9fff]+", str(query or "")):
        compact = "".join(sequence.split())
        if len(compact) <= 2:
            if compact and compact not in terms:
                terms.append(compact)
            continue
        for index in range(len(compact) - 1):
            token = compact[index : index + 2]
            if token not in terms:
                terms.append(token)
    return terms


def _section_name(record: MemoryRecord, *, prompt_mode: PromptMode) -> str:
    if record.kind.value in {"user_preference", "user_profile"}:
        return "user"
    if record.kind.value == "project_fact":
        return "project"
    if record.kind.value == "imported_conclusion":
        return "approved"
    if record.kind.value == "branch_finding":
        if record.promoted_to_main or record.scope.value == "root_thread":
            return "approved"
        return "branch"
    if record.kind.value == "turn_summary":
        return "episodic"
    return "other"


def _section_priority(record: MemoryRecord, *, prompt_mode: PromptMode) -> int:
    section = _section_name(record, prompt_mode=prompt_mode)
    if prompt_mode == PromptMode.SYNTHESIZE:
        ordering = {"user": 0, "project": 1, "approved": 2, "episodic": 3, "branch": 4, "other": 5}
        return ordering.get(section, 5)
    if prompt_mode == PromptMode.BRANCH_REVIEW:
        ordering = {"branch": 0, "approved": 1, "project": 2, "user": 3, "episodic": 4, "other": 5}
        return ordering.get(section, 5)
    if prompt_mode == PromptMode.EXECUTE:
        ordering = {"user": 0, "project": 1, "approved": 2, "branch": 3, "episodic": 4, "other": 5}
        return ordering.get(section, 5)
    ordering = {"approved": 0, "branch": 1, "project": 2, "user": 3, "episodic": 4, "other": 5}
    return ordering.get(section, 5)


def _section_limits(*, prompt_mode: PromptMode, top_k: int) -> dict[str, int]:
    if prompt_mode == PromptMode.SYNTHESIZE:
        return {
            "user": min(2, top_k),
            "project": min(2, top_k),
            "approved": min(3, top_k),
            "episodic": 1,
            "other": 1,
        }
    if prompt_mode == PromptMode.BRANCH_REVIEW:
        return {
            "branch": min(3, top_k),
            "approved": min(2, top_k),
            "project": 1,
            "user": 1,
            "episodic": 1,
            "other": 1,
        }
    if prompt_mode == PromptMode.EXECUTE:
        return {
            "user": min(2, top_k),
            "project": min(2, top_k),
            "approved": min(2, top_k),
            "branch": 1,
            "episodic": 1,
            "other": 1,
        }
    return {
        "approved": min(2, top_k),
        "branch": min(2, top_k),
        "project": 1,
        "user": 1,
        "episodic": 1,
        "other": 1,
    }
