from __future__ import annotations

import re

from ..core.request_context import RequestContext
from ..core.types import Plan, PromptMode
from ..core.types import FindingItem
from .dedupe import memory_resolution_key, memory_semantic_key
from .models import (
    MemoryRecord,
    MemoryScope,
    MemorySearchHit,
    MemoryVisibility,
    RetrievedMemoryBundle,
)
from .policy import MemoryPolicy
from .scorer import score_memory_hit


class MemoryRetriever:
    def __init__(self, *, store=None, policy: MemoryPolicy | None = None, default_limit: int = 8):
        self.store = store
        self.policy = policy or MemoryPolicy(top_k=default_limit)
        self.default_limit = default_limit

    def retrieve_for_turn(
        self,
        *,
        context: RequestContext,
        state: dict,
        query: str,
        prompt_mode: PromptMode,
    ) -> RetrievedMemoryBundle:
        effective_query = _build_retrieval_query(
            query=query,
            state=state,
            prompt_mode=prompt_mode,
        )
        namespaces = self._candidate_namespaces(context=context)
        hits: list[MemorySearchHit] = []
        for namespace in namespaces:
            hits.extend(self._search_namespace(namespace, effective_query, limit=self.default_limit))
        reranked = self._rerank_hits(hits, query=effective_query, prompt_mode=prompt_mode)
        deduped = self._dedupe_hits(reranked)
        bundle = RetrievedMemoryBundle(
            query=effective_query,
            hits=deduped[: self.default_limit],
            namespaces=namespaces,
            total_hits=len(deduped),
        )
        return self.policy.filter_bundle_for_prompt(bundle, prompt_mode=prompt_mode)

    def _candidate_namespaces(self, *, context: RequestContext) -> list[tuple[str, ...]]:
        return self.policy.allowed_namespaces_for_read(context=context)

    def _search_namespace(self, namespace: tuple[str, ...], query: str, limit: int) -> list[MemorySearchHit]:
        if self.store is None:
            return []
        raw_hits = self.store.search(namespace, query=query, limit=limit) or []
        hits: list[MemorySearchHit] = []
        for raw in raw_hits:
            value = getattr(raw, "value", raw)
            if not isinstance(value, dict):
                value = {"content": str(value), "summary": str(value)}
            payload = {
                "memory_id": str(value.get("memory_id") or getattr(raw, "key", "")),
                "kind": value.get("kind", value.get("type", "turn_summary")),
                "scope": value.get("scope", "root_thread"),
                "visibility": value.get("visibility", "private"),
                "namespace": tuple(value.get("namespace") or getattr(raw, "namespace", namespace)),
                "content": value.get("content") or value.get("summary") or str(value),
                "summary": value.get("summary") or value.get("content") or "",
                "tags": value.get("tags", []),
                "evidence_refs": value.get("evidence_refs", []),
                "source_thread_id": value.get("source_thread_id"),
                "source_branch_id": value.get("source_branch_id") or value.get("branch_id"),
                "root_thread_id": value.get("root_thread_id"),
                "user_id": value.get("user_id"),
                "confidence": value.get("confidence"),
                "importance": value.get("importance", 0.5),
                "promoted_to_main": value.get("promoted_to_main", False),
                "fingerprint": value.get("fingerprint"),
                "semantic_key": value.get("semantic_key"),
            }
            created_at = value.get("created_at")
            updated_at = value.get("updated_at")
            if created_at is not None:
                payload["created_at"] = created_at
            if updated_at is not None:
                payload["updated_at"] = updated_at
            record = MemoryRecord.model_validate(payload)
            hits.append(
                MemorySearchHit(
                    record=record,
                    score=float(getattr(raw, "score", 0.0) or 0.0),
                    matched_terms=_matched_terms(query, record),
                    namespace=record.namespace or namespace,
                )
            )
        return hits

    def _rerank_hits(self, hits: list[MemorySearchHit], *, query: str, prompt_mode: PromptMode) -> list[MemorySearchHit]:
        reranked = [
            hit.model_copy(update={"score": score_memory_hit(hit, query=query, prompt_mode=prompt_mode)})
            for hit in hits
        ]
        return sorted(reranked, key=lambda item: item.score, reverse=True)

    def _dedupe_hits(self, hits: list[MemorySearchHit]) -> list[MemorySearchHit]:
        deduped_by_key: dict[str, MemorySearchHit] = {}
        for hit in hits:
            resolution_key = memory_resolution_key(
                hit.record.model_copy(
                    update={
                        "semantic_key": hit.record.semantic_key or memory_semantic_key(hit.record),
                    }
                )
            )
            current = deduped_by_key.get(resolution_key)
            if current is None or _hit_preference(hit) > _hit_preference(current):
                deduped_by_key[resolution_key] = hit
        return sorted(deduped_by_key.values(), key=lambda item: item.score, reverse=True)


def _matched_terms(query: str, record: MemoryRecord) -> list[str]:
    haystack = f"{record.summary} {record.content}".casefold()
    terms = []
    for term in _query_terms(query):
        if term.casefold() in haystack and term not in terms:
            terms.append(term)
    return terms


def _hit_preference(hit: MemorySearchHit) -> tuple[float, ...]:
    record = hit.record
    return (
        1.0 if record.promoted_to_main else 0.0,
        1.0 if record.visibility == MemoryVisibility.SHARED else 0.0,
        1.0 if record.scope == MemoryScope.ROOT_THREAD else 0.0,
        float(record.confidence or 0.0),
        record.importance,
        float(len(record.evidence_refs)),
        record.updated_at.timestamp(),
        hit.score,
    )


def _build_retrieval_query(*, query: str, state: dict, prompt_mode: PromptMode) -> str:
    parts: list[str] = []
    for candidate in (
        str(query or "").strip(),
        str(state.get("active_goal") or "").strip(),
        str(state.get("task_brief") or "").strip(),
        _current_plan_step_goal(state),
    ):
        if not candidate:
            continue
        normalized = " ".join(candidate.split())
        if normalized and normalized not in parts:
            parts.append(normalized)

    if prompt_mode == PromptMode.SYNTHESIZE:
        imported_lines = []
        for item in list(state.get("imported_findings", []) or [])[:2]:
            if isinstance(item, FindingItem):
                line = item.finding.strip()
            elif isinstance(item, dict):
                line = str(item.get("finding") or item.get("summary") or "").strip()
            else:
                line = str(item or "").strip()
            if line:
                imported_lines.append(line)
        for line in imported_lines:
            if line and line not in parts:
                parts.append(line)

    combined = " | ".join(parts)
    return combined[:240]


def _current_plan_step_goal(state: dict) -> str:
    plan = state.get("plan")
    current_step_id = str(state.get("current_step_id") or "").strip()
    if not isinstance(plan, Plan) or not current_step_id:
        return ""
    for step in plan.steps:
        if step.id == current_step_id:
            return str(step.goal or "").strip()
    return ""


def _query_terms(query: str) -> list[str]:
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
