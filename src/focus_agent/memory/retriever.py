from __future__ import annotations

from ..core.request_context import RequestContext
from ..core.types import PromptMode
from .models import (
    MemoryRecord,
    MemorySearchHit,
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
        del state
        namespaces = self._candidate_namespaces(context=context)
        hits: list[MemorySearchHit] = []
        for namespace in namespaces:
            hits.extend(self._search_namespace(namespace, query, limit=self.default_limit))
        reranked = self._rerank_hits(hits, query=query, prompt_mode=prompt_mode)
        deduped = self._dedupe_hits(reranked)
        bundle = RetrievedMemoryBundle(
            query=query,
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
                "created_at": value.get("created_at"),
                "updated_at": value.get("updated_at"),
            }
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
        deduped: list[MemorySearchHit] = []
        seen: set[str] = set()
        for hit in hits:
            fingerprint = hit.record.fingerprint or f"{hit.record.kind.value}:{hit.record.summary}:{hit.record.content}"
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            deduped.append(hit)
        return deduped


def _matched_terms(query: str, record: MemoryRecord) -> list[str]:
    haystack = f"{record.summary} {record.content}".casefold()
    return [term for term in query.split() if term and term.casefold() in haystack]
